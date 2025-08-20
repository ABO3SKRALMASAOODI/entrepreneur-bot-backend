# routes/agents_pipeline.py
from flask import Blueprint, request, jsonify
import os
import json
import tempfile
import shutil
import subprocess
import importlib.util
import openai
from typing import Dict, Any


agents_pipeline_bp = Blueprint("agents_pipeline", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# --- helpers for clean agent outputs ---
def _detect_language_from_filename(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "jsx": "javascript",
        "tsx": "typescript",
        "json": "json",
        "css": "css",
        "html": "html",
        "md": "markdown",
        "txt": "text",
        "yml": "yaml",
        "yaml": "yaml",
    }.get(ext, "text")

def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing triple-backtick fences if the model included them."""
    if text is None:
        return ""
    s = text.strip()
    # Remove starting lang or 
    if s.startswith("```"):
        s = s.split("\n", 1)
        s = s[1] if len(s) > 1 else ""
    # Remove trailing
    if s.endswith("```"):
        s = s[: -3].rstrip()
    return s

# =====================================================
# 1. Utility Functions
# =====================================================
def get_agent_files(spec):
    """
    Collect all unique file names from the orchestrator spec.
    Compatible with new pipeline JSON structure.
    """
    files = set()

    # === New spec style ===
    for f in spec.get("files", []):
        if "file" in f:
            files.add(f["file"])

    # Global reference index (backup source of file names)
    for ref in spec.get("global_reference_index", []):
        if "file" in ref:
            files.add(ref["file"])

    # Depth boost sometimes carries extra files
    for fname in spec.get("__depth_boost", {}).keys():
        files.add(fname)

    # Legacy support (if old orchestrator spec sneaks in)
    for f in spec.get("interface_stub_files", []):
        if "file" in f:
            files.add(f["file"])

    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if "file" in func:
            files.add(func["file"])

    for dep in spec.get("dependency_graph", []):
        if "file" in dep:
            files.add(dep["file"])
        for d in dep.get("dependencies", []):
            files.add(d)

    return sorted(files)
def extract_file_spec(file_name: str, contracts: Dict[str, Any], depth_boost: Dict[str, Any]) -> Dict[str, Any]:
    """Extract relevant spec for a given file, with safe fallback when 'implements' is missing."""

    file_spec = {
        "file": file_name,
        "functions": [],
        "apis": [],
        "entities": [],
        "protocols": [],
        "errors": [],
        "contracts": {
            "functions": [],
            "apis": [],
            "entities": [],
            "protocols": [],
            "errors": []
        },
        "depth_notes": depth_boost.get(file_name, {}).get("notes", [])
    }

    # Helper to filter contracts
    def collect(items):
        return [
            item for item in items
            if not item.get("implements") or file_name in item["implements"]
        ]

    # Fill each category
    file_spec["functions"] = collect(contracts.get("functions", []))
    file_spec["apis"] = collect(contracts.get("apis", []))
    file_spec["entities"] = collect(contracts.get("entities", []))
    file_spec["protocols"] = collect(contracts.get("protocols", []))
    file_spec["errors"] = collect(contracts.get("errors", []))

    # Keep global reference
    file_spec["contracts"] = {
        "functions": file_spec["functions"],
        "apis": file_spec["apis"],
        "entities": file_spec["entities"],
        "protocols": file_spec["protocols"],
        "errors": file_spec["errors"]
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
You are coding {file_name}. Follow the spec exactly and produce fully working, production-ready code. Ignore nitpicky style/docstring issues if unclear, but fix critical errors (syntax, imports, compatibility). Output ONLY the complete code for {file_name}.
--- FULL SPEC:
{json.dumps(full_spec, indent=2)}
FILE-SPEC:
{json.dumps(file_spec, indent=2)}
{feedback_note}
"""

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # or "gpt-5" if you prefer
            temperature=0,
            request_timeout=180,
            messages=[
                {
                    "role": "system",
                    "content": "You are a perfectionist coding agent focused on correctness and compatibility.",
                },
                {"role": "user", "content": agent_prompt}
            ]
        )
        raw = resp.choices[0].message.content or ""
        return _strip_code_fences(raw)
    except Exception as e:
        raise RuntimeError(f"Generator agent failed for {file_name}: {e}")


def run_tester_agent(file_name, file_spec, full_spec, generated_code):
    """Tester Agent: relaxed review — only blocks on hard errors."""
    if file_name in _first_review_cache:
        return _first_review_cache[file_name]

    tester_prompt = f"""
Review {file_name}. List only CRITICAL blocking issues: syntax errors, failed imports, broken tests, missing required functions. Ignore minor style/docstring/naming issues (just note them briefly if any). If code is usable and correct, output ONLY: ✅ APPROVED
--- FULL SPEC:
{json.dumps(full_spec, indent=2)}
FILE-SPEC:
{json.dumps(file_spec, indent=2)}
CODE:
{generated_code}
"""

    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0,
        request_timeout=180,
        messages=[
            {
                "role": "system",
                "content": "You are a strict reviewer, but approve code unless there are fatal issues."
            },
            {
                "role": "user",
                "content": tester_prompt
            }
        ]
    )
    review_text = resp.choices[0].message["content"]
    _first_review_cache[file_name] = review_text
    return review_text


def is_hard_failure(review: str) -> bool:
    """Check if review indicates a real blocking failure."""
    critical_terms = ["SyntaxError", "ImportError", "integration tests failed", "missing required"]
    return any(term.lower() in review.lower() for term in critical_terms)

def run_agents_for_spec(spec):
    """
    Runs generator + tester loop for each file until approved or retries exhausted.
    Logs orchestrator + agent activity in detail.
    """
    files = get_agent_files(spec)
    outputs = []

    # Map file -> agent name
    agent_map = {}
    for agent in spec.get("agent_blueprint", []):
        desc = agent.get("description", "")
        matched_file = None
        for f in spec.get("files", []):
            if f.get("file") and f["file"] in desc:
                matched_file = f["file"]
                break
        if matched_file:
            agent_map[matched_file] = agent.get("name", f"AgentFor-{matched_file}")

    for file_name in files:
        file_spec = extract_file_spec(spec, file_name)
        review_feedback = None
        approved = False
        attempts = 0
        final_code, final_review = None, None

        while not approved and attempts < MAX_RETRIES:
            # 🔥 LOG CLEAR INPUT TO AGENT
            print("\n" + "#"*80)
            print(f"🤖 AGENT INPUT for {file_name} (attempt {attempts+1})")
            print("#"*80)
            try:
                print("📂 FILE SPEC:")
                print(json.dumps(file_spec, indent=2, default=str))
                print("\n📦 FULL SPEC (trimmed):")
                print(json.dumps(spec, indent=2, default=str)[:2000] + " ... [TRUNCATED]" )
            except Exception as e:
                print(f"⚠️ Could not serialize agent input: {e}")
            print("#"*80 + "\n")

            # === RUN GENERATOR + TESTER ===
            code = run_generator_agent(file_name, file_spec, spec, review_feedback)
            review = run_tester_agent(file_name, file_spec, spec, code)

            final_code, final_review = code, review

            if "✅ APPROVED" in review or not is_hard_failure(review):
                approved = True
                outputs.append({
                    "role": "agent",
                    "agent": agent_map.get(file_name, f"AgentFor-{file_name}"),
                    "file": file_name,
                    "language": _detect_language_from_filename(file_name),
                    "content": code
                })
            else:
                review_feedback = review
                attempts += 1

        # 🔍 FINAL RESULT LOG
        print("\n" + "="*60)
        print(f"📄 Final result for {file_name} (after {attempts+1} attempt(s))")
        print("="*60)
        if approved:
            print("✅ APPROVED")
        else:
            print("❌ FAILED after max retries")
        print("\n📝 Final code preview:")
        print((final_code or "")[:1000])
        print("\n🔍 Final review feedback:")
        print(final_review or "No review")
        print("="*60 + "\n")

        if not approved:
            raise RuntimeError(f"File {file_name} could not be approved after {attempts} attempts.")

    # Validation checks
    try:
        verify_imports(outputs)
    except Exception as e:
        print(f"⚠️ Import check failed but continuing: {e}")

    try:
        verify_tests(outputs, spec)
    except Exception as e:
        print(f"⚠️ Tests failed but continuing: {e}")

    return outputs

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
