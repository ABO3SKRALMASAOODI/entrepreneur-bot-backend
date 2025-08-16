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

def run_tester_agent(file_name, code, spec):
    """Runs the tester agent on a generated file and returns feedback."""
    prompt = f"""
    You are the tester agent. Review the file: {file_name}.
    Check the following:
    1. Code matches the spec.
    2. No syntax errors.
    3. No missing imports.
    4. Production-ready quality.

    Respond with either:
    - '✅ APPROVED' if the file is flawless.
    - A list of blocking issues otherwise.

    File content:
    {code}
    """
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a strict file-specific reviewer."},
                {"role": "user", "content": prompt}
            ]
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"Tester error: {e}"

def is_hard_failure(review: str) -> bool:
    """
    Check if review indicates a real blocking failure.
    Includes syntax, import, test, and hoisting/ordering issues.
    """
    critical_terms = [
        "SyntaxError",
        "ImportError",
        "integration tests failed",
        "missing required",
        "ReferenceError",
        "defined after it is called",
        "hoisting"
    ]
    return any(term.lower() in review.lower() for term in critical_terms)
def run_agents_for_spec(spec):
    """Run generator, tester, and fixer agents for each file in the spec."""
    final_outputs = {}
    failures = {}

    # Step 1: Extract files from spec
    files = get_agent_files(spec)

    for file_name in files:
        file_spec = extract_file_spec(file_name, spec)

        # --- Generate Code ---
        generated_code = run_generator_agent(file_name, file_spec, spec)
        if not generated_code:
            failures[file_name] = "❌ Generator failed"
            continue

        # --- Tester Review ---
        review_feedback = run_tester_agent(file_name, generated_code, spec)

        # Check approval more flexibly
        if (
            not review_feedback
            or "approved" in review_feedback.lower()
            or "✅" in review_feedback
        ):
            final_outputs[file_name] = {"file": file_name, "code": generated_code}
        else:
            # --- Attempt Fix ---
            fixed_code = run_fixer_agent(file_name, generated_code, review_feedback, spec)
            recheck_feedback = run_tester_agent(file_name, fixed_code, spec)

            if (
                recheck_feedback
                and ("approved" in recheck_feedback.lower() or "✅" in recheck_feedback)
            ):
                final_outputs[file_name] = {"file": file_name, "code": fixed_code}
            else:
                failures[file_name] = review_feedback

    # --- Final Verification: imports + tests ---
    if final_outputs:
        try:
            outputs_as_dicts = list(final_outputs.values())
            verify_imports(outputs_as_dicts)
            verify_tests(outputs_as_dicts, spec)
        except Exception as e:
            return {
                "status": "tests_failed",
                "approved_files": final_outputs,
                "failed_files": failures,
                "message": f"Verification failed: {e}",
            }

    return {
        "status": "success" if final_outputs else "failed",
        "approved_files": final_outputs,
        "failed_files": failures,
    }

def run_fixer_agent(file_name, file_spec, full_spec, prev_code, review_feedback):
    """
    Fixer Agent: takes previous code and tester feedback,
    applies corrections without rewriting from scratch.
    Ensures functions are reordered so they are defined before being called.
    """
    fixer_prompt = f"""
You are fixing {file_name}.
Here is the last version of the code and the tester feedback.
Apply ONLY the required corrections. Keep working code unchanged.

⚠️ CRITICAL RULE:
- Ensure all functions are defined BEFORE they are called
- Fix hoisting / ordering problems
- Do not ignore ReferenceErrors related to hoisting
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
            {"role": "system", "content": "You are a Fixer Agent. Patch broken code without rewriting everything, but always fix ordering/hoisting issues."},
            {"role": "user", "content": fixer_prompt}
        ]
    )
    return resp.choices[0].message.content.strip()

def run_restructuring_agent(file_name, file_spec, full_spec, prev_code, review_feedback):
    """
    Restructuring Agent: aggressive fallback when the same issue repeats.
    Ensures all functions are ordered correctly and the file has a clean structure.
    """
    restructure_prompt = f"""
You are restructuring {file_name}.
The code repeatedly failed due to ordering/hoisting issues.
Rewrite the file so that:
- All functions are defined before they are called
- Imports/constants at top
- Helper functions next
- Main logic last
- Preserve all working parts of the code
---
FILE-SPEC:
{json.dumps(file_spec, indent=2)}

PREVIOUS CODE:
{prev_code}

REPEATED REVIEW FEEDBACK:
{review_feedback}
"""
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0,
        request_timeout=60,
        messages=[
            {"role": "system", "content": "You are a restructuring agent. Fix ordering issues aggressively and ensure code correctness."},
            {"role": "user", "content": restructure_prompt}
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
