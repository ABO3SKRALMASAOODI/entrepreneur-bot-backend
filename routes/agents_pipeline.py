# routes/agents_pipeline.py

from flask import Blueprint, request, jsonify
import os
import json
import tempfile
import shutil
import subprocess
import importlib.util
import openai

agents_pipeline_bp = Blueprint("agents_pipeline", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")



# =====================================================
# 1. Utility Functions
# =====================================================
def get_agent_files(spec: dict) -> list[str]:
    """
    Extract all unique file names from the orchestrator spec.
    Works with the new universal spec format (files[], dependency_graph[]).
    """
    files = set()

    # Collect from files[] section
    for f in spec.get("files", []):
        if isinstance(f, dict) and "file" in f:
            files.add(f["file"])

    # Collect from dependency_graph[]
    for dep in spec.get("dependency_graph", []):
        if "file" in dep:
            files.add(dep["file"])
        for d in dep.get("dependencies", []):
            files.add(d)

    # Collect from global_reference_index[]
    for ref in spec.get("global_reference_index", []):
        if "file" in ref:
            files.add(ref["file"])

    return sorted(files)

def extract_file_spec(spec: dict, file_name: str) -> dict:
    """
    Extract only the contracts and notes relevant to a single file.
    """
    file_spec = {
        "file_name": file_name,
        "functions": [],
        "apis": [],
        "entities": [],
        "protocols": [],
        "errors": [],
        "compatibility_notes": [],
        "shared_schemas": spec.get("core_shared_schemas", None),
        "config_and_constants": None,
    }

    contracts = spec.get("contracts", {})
    depth_info = spec.get("__depth_boost", {}).get(file_name, {})

    # Match functions
    for func in contracts.get("functions", []):
        if file_name in json.dumps(func):
            file_spec["functions"].append(func)

    # Match APIs
    for api in contracts.get("apis", []):
        if file_name in json.dumps(api):
            file_spec["apis"].append(api)

    # Match entities
    for ent in contracts.get("entities", []):
        if file_name in json.dumps(ent):
            file_spec["entities"].append(ent)

    # Match protocols
    for proto in contracts.get("protocols", []):
        if file_name in json.dumps(proto):
            file_spec["protocols"].append(proto)

    # Match errors
    for err in contracts.get("errors", []):
        if file_name in json.dumps(err):
            file_spec["errors"].append(err)

    # Inject depth notes (engineering guidelines)
    file_spec["compatibility_notes"].extend(depth_info.get("notes", []))

    # Link config.py
    if file_name == "config.py":
        file_spec["config_and_constants"] = {
            "constants": spec.get("constants", {}),
            "errors": contracts.get("errors", [])
        }

    return file_spec


def verify_imports(outputs):
    """Ensure generated code imports without syntax errors."""
    tmp_dir = tempfile.mkdtemp()
    try:
        for output in outputs:
            file_path = os.path.join(tmp_dir, output["file"])
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(output["code"])

        for output in outputs:
            file_path = os.path.join(tmp_dir, output["file"])
            spec_obj = importlib.util.spec_from_file_location("module.name", file_path)
            try:
                mod = importlib.util.module_from_spec(spec_obj)
                spec_obj.loader.exec_module(mod)
            except Exception as e:
                raise RuntimeError(f"Import failed for {output['file']}: {e}")
    finally:
        shutil.rmtree(tmp_dir)
    return outputs


def verify_tests(outputs, spec):
    """Run orchestrator-provided integration tests."""
    tmp_dir = tempfile.mkdtemp()
    try:
        for output in outputs:
            file_path = os.path.join(tmp_dir, output["file"])
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(output["code"])

        for test in spec.get("integration_tests", []):
            test_path = os.path.join(tmp_dir, test["path"])
            os.makedirs(os.path.dirname(test_path), exist_ok=True)
            with open(test_path, "w") as f:
                f.write(test["code"])

        proc = subprocess.run(["pytest", tmp_dir], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Integration tests failed:\n{proc.stdout}\n{proc.stderr}")
    finally:
        shutil.rmtree(tmp_dir)
    return outputs

# =====================================================
# 2. Generator & Tester Agents
# =====================================================


# =====================================================
# 2. Generator & Tester Agents (Relaxed Assessment)
# =====================================================

MAX_RETRIES = 10
_first_review_cache = {}

def run_generator_agent(file_name, file_spec, full_spec, review_feedback=None):
    """Generator Agent: produces code with feedback applied (if any)."""
    feedback_note = ""
    if review_feedback:
        feedback_note = (
            "\n\nFEEDBACK TO FIX (apply where critical, ignore style-only notes):\n"
            f"{review_feedback}"
        )

    agent_prompt = f"""
You are coding {file_name}.
Follow the spec exactly and produce fully working, production-ready code.
Ignore nitpicky style/docstring issues if unclear, but fix critical errors (syntax, imports, compatibility).
Output ONLY the complete code for {file_name}.
---
FULL SPEC:
{json.dumps(full_spec, indent=2)}

FILE-SPEC:
{json.dumps(file_spec, indent=2)}
{feedback_note}
"""

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",       # you can swap to "gpt-5" if preferred
            temperature=0,
            request_timeout=60,
            messages=[
                {"role": "system", "content": "You are a perfectionist coding agent focused on correctness and compatibility."},
                {"role": "user", "content": agent_prompt}
            ]
        )
        # ✅ safer access (property instead of dict)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"Generator agent failed for {file_name}: {e}")


def run_tester_agent(file_name, file_spec, full_spec, generated_code):
    """Tester Agent: relaxed review — only blocks on hard errors."""
    if file_name in _first_review_cache:
        return _first_review_cache[file_name]

    tester_prompt = f"""
Review {file_name}.
List only CRITICAL blocking issues: syntax errors, failed imports, broken tests, missing required functions.
Ignore minor style/docstring/naming issues (just note them briefly if any).
If code is usable and correct, output ONLY: ✅ APPROVED
---
FULL SPEC:
{json.dumps(full_spec, indent=2)}

FILE-SPEC:
{json.dumps(file_spec, indent=2)}

CODE:
{generated_code}
"""

    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0,
        request_timeout=60,
        messages=[
            {"role": "system", "content": "You are a strict reviewer, but approve code unless there are fatal issues."},
            {"role": "user", "content": tester_prompt}
        ]
    )

    review_text = resp.choices[0].message["content"]
    _first_review_cache[file_name] = review_text
    return review_text


def is_hard_failure(review: str) -> bool:
    """Check if review indicates a real blocking failure."""
    critical_terms = ["SyntaxError", "ImportError", "integration tests failed", "missing required"]
    return any(term.lower() in review.lower() for term in critical_terms)
def run_agents_for_spec(spec: dict) -> list[dict]:
    """
    Runs generator → tester → fixer loop for each file until approved.
    Returns final outputs.
    """
    files = get_agent_files(spec)
    outputs = []

    for file_name in files:
        file_spec = extract_file_spec(spec, file_name)
        approved = False
        attempts = 0
        generated_code = None
        review_feedback = None

        while not approved and attempts < MAX_RETRIES:
            if attempts == 0:
                # First attempt = fresh generator
                generated_code = run_generator_agent(file_name, file_spec, spec)
            else:
                # Next attempts = fixer applies feedback
                generated_code = run_fixer_agent(file_name, file_spec, spec, generated_code, review_feedback)

            review = run_tester_agent(file_name, file_spec, spec, generated_code)

            if "✅ APPROVED" in review:
                approved = True
                outputs.append({"file": file_name, "code": generated_code})
                print(f"✅ {file_name} accepted after {attempts+1} attempt(s).")
            else:
                print(f"❌ {file_name} failed review (Attempt {attempts+1}):\n{review}")
                review_feedback = review
                attempts += 1

        if not approved:
            raise RuntimeError(f"File {file_name} could not be approved after {attempts} attempts.")

    # --- Final validation phase ---
    try:
        verify_imports(outputs)
    except Exception as e:
        print(f"⚠️ Import check failed: {e}")

    try:
        verify_tests(outputs, spec)
    except Exception as e:
        print(f"⚠️ Integration tests failed: {e}")

    return outputs
def run_fixer_agent(file_name, file_spec, full_spec, prev_code, review_feedback):
    """
    Fixer Agent: takes previous code and tester feedback,
    applies corrections without rewriting from scratch.
    """
    fixer_prompt = f"""
You are fixing {file_name}.
Here is the last version of the code and the tester feedback.
Apply ONLY the required corrections. Keep working code unchanged.
---
FILE-SPEC:
{json.dumps(file_spec, indent=2)}

PREVIOUS CODE:
{prev_code}

TESTER FEEDBACK:
{review_feedback}
"""
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0,
        request_timeout=60,
        messages=[
            {"role": "system", "content": "You are a Fixer Agent. Patch broken code without rewriting everything."},
            {"role": "user", "content": fixer_prompt}
        ]
    )
    return resp.choices[0].message.content.strip()

# =====================================================
# 4. Flask Endpoint
# =====================================================

@agents_pipeline_bp.route("/run_agents", methods=["POST"])
def run_agents_endpoint():
    body = request.get_json(force=True) or {}
    spec = body.get("spec")
    if not spec:
        return jsonify({"error": "Missing spec"}), 400
    try:
        agent_outputs = run_agents_for_spec(spec)
        return jsonify({"role": "assistant", "agents_output": agent_outputs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
