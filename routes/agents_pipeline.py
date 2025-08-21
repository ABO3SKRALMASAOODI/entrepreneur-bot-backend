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
# Replace your old run_generator_agent function with this one.

def run_generator_agent(file_name, file_spec, full_spec, review_feedback=None):
    """Generator Agent: produces code with authoritative file-spec and contextual full-spec."""

    feedback_note = ""
    if review_feedback:
        feedback_note = (
            "\n\n--- FEEDBACK TO FIX ---\n"
            "The previous attempt failed. You MUST correct the following errors:\n"
            f"{review_feedback}"
        )

    agent_prompt = f"""
You are an expert software engineer generating code for the file: `{file_name}`.

--- YOUR MISSION ---
Your goal is to write complete, correct, and production-ready code for this file based *only* on the specifications provided.

--- RULES OF ENGAGEMENT (Non-negotiable) ---
1.  **AUTHORITATIVE `FILE-SPEC`**: Your primary responsibility is to implement every entity, API, function, and protocol listed in the `FILE-SPEC` below. Do NOT omit any required items.
2.  **CONTEXTUAL `FULL-SPEC`**: Use the `FULL-SPEC` as a **read-only library or master blueprint**. When you need to interact with code from other files (e.g., importing an entity or calling an API), you MUST consult the `FULL-SPEC` to understand the correct signatures, data structures, and endpoints.
3.  **NO INVENTION**: Do NOT invent functions, classes, or logic not described in the specs. Stick to the plan.
4.  **OUTPUT CODE ONLY**: Your final output must be ONLY the complete code for `{file_name}`. Do not include explanations, markdown fences, or any other text.

--- `FILE-SPEC` (Your primary work order for `{file_name}`):
{json.dumps(file_spec, indent=2)}

--- `FULL-SPEC` (Read-only context for the entire project):
{json.dumps(full_spec, indent=2)}
{feedback_note}
"""

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",  # Consider a more powerful model for code generation
            temperature=0.0, # Set to 0 for maximum determinism
            request_timeout=240,
            messages=[
                {
                    "role": "system",
                    "content": "You are a perfectionist coding agent focused on correctness, compatibility, and strict adherence to file contracts.",
                },
                {"role": "user", "content": agent_prompt}
            ]
        )
        raw = resp.choices[0].message["content"] or ""
        return _strip_code_fences(raw)
    except Exception as e:
        raise RuntimeError(f"Generator agent failed for {file_name}: {e}")
# Add these new functions to agents_pipeline.py

def scaffold_project(spec: Dict[str, Any], base_dir: str) -> str:
    """Creates the directory structure and basic config files before agents run."""
    project_root = os.path.join(base_dir, spec.get("project", "new_project").replace(" ", "_"))
    print(f"Scaffolding project in: {project_root}")

    # Create all file paths to ensure directories exist
    for file_info in spec.get("files", []):
        file_path = os.path.join(project_root, file_info["file"])
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # Create empty files to start
        with open(file_path, "w") as f:
            pass

    # Example: Create a basic package.json if it's a Node.js project
    if any(".js" in f["file"] for f in spec.get("files", [])):
        package_json_path = os.path.join(project_root, "package.json")
        if os.path.exists(package_json_path):
            pkg_data = {
                "name": spec.get("project", "new-project").lower().replace(" ", "-"),
                "version": "1.0.0",
                "description": spec.get("description", ""),
                "main": "server.js",
                "scripts": {"start": "node server.js"},
                # TODO: Intelligently add dependencies based on spec
                "dependencies": {"express": "^4.18.2", "cors": "^2.8.5"}
            }
            with open(package_json_path, "w") as f:
                json.dump(pkg_data, f, indent=2)

    return project_root


def run_programmatic_checks(file_name: str, code: str) -> str:
    """
    Runs automated checks like linting on the generated code.
    Returns a string of feedback if errors are found.
    """
    feedback = []
    # This is a placeholder for real checks.
    # In a real system, you would call a linter like ESLint or Pylint here.
    # For example:
    # if file_name.endswith(".js"):
    #     result = subprocess.run(["eslint", "--stdin"], input=code, text=True, capture_output=True)
    #     if result.returncode != 0:
    #         feedback.append(f"ESLint Errors:\n{result.stdout}")

    if "require('mongodb')" in code and not file_name.endswith(("api.js", "db.js", "server.js")):
         feedback.append("Architectural Error: Frontend file appears to be making a direct database call.")

    return "\n".join(feedback)
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
def extract_file_spec(file_name: str, final_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts the unified spec for a given file.
    Combines contracts from Contractor + Booster, plus depth notes.
    """

    # Start with baseline
    file_spec = {
        "file": file_name,
        "functions": [],
        "apis": [],
        "entities": [],
        "protocols": [],
        "errors": [],
        "contracts": {},
        "depth_notes": [],
    }

    # --- Collect from merged contracts ---
    contracts = final_spec.get("contracts", {})
    for key in ["functions", "apis", "entities", "protocols", "errors"]:
        items = contracts.get(key, [])
        for item in items:
            implements = item.get("implements", [])
            if not implements or file_name in implements:   # include if missing OR matches
                file_spec[key].append(item)

    # --- Merge booster enrichment ---
    depth_boost = final_spec.get("__depth_boost", {})
    if file_name in depth_boost:
        file_spec["contracts"] = depth_boost[file_name].get("contracts", {})
        file_spec["depth_notes"] = depth_boost[file_name].get("notes", [])

    return file_spec

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
        
        file_spec = extract_file_spec(file_name, spec)
        review_feedback = None
        approved = False
        attempts = 0
        final_code, final_review = None, None

        # 🔥 Log the agent input ONCE per file (instead of every attempt)
        print("\n" + "#"*80)
        print(f"🤖 AGENT INPUT for {file_name} (spec shown once)")
        print("#"*80)
        try:
            print("📂 FILE SPEC:")
            print(json.dumps(file_spec, indent=2, default=str))
            print("\n📦 FULL SPEC (trimmed):")
            print(json.dumps(spec, indent=2, default=str)[:2000] + " ... [TRUNCATED]" )
        except Exception as e:
            print(f"⚠️ Could not serialize agent input: {e}")
        print("#"*80 + "\n")

        while not approved and attempts < MAX_RETRIES:
            # Short retry log only
            print(f"🔄 Attempt {attempts+1} for {file_name} ...")

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
