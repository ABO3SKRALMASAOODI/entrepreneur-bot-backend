# routes/orchestrator.py

from flask import Blueprint, request, jsonify
import os, json
from datetime import datetime
import openai
from pathlib import Path
from typing import Dict, Any
from flask_cors import cross_origin
from routes.agents_pipeline import run_agents_for_spec
from routes.spec_merger import merge_specs, validate_spec, boost_spec_depth

# ===== Flask Blueprint =====
agents_bp = Blueprint("agents", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ===== Persistent State =====
PROJECT_STATE_FILE = Path("project_state.json")

def load_state():
    if PROJECT_STATE_FILE.exists():
        with open(PROJECT_STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(PROJECT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

project_state = load_state()
user_sessions = {}

# ====== Core LLM Helper ======
def call_orchestrator(prompt: str, system_msg: str) -> Dict[str, Any]:
    """Single call to GPT orchestrator with strict JSON return"""
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0.25,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ]
    )
    text = resp["choices"][0]["message"]["content"]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except:
            return {}
    return {}

# ====== Multi-Orchestrator ======
def generate_description_spec(project: str, clarifications: str):
    return call_orchestrator(
        f"Project: {project}\nConstraints: {clarifications}",
        "You are a project description orchestrator. Output strict JSON with project, description, type, target_users, tech_stack."
    )

def generate_contracts_spec(project: str, clarifications: str):
    return call_orchestrator(
        f"Project: {project}\nConstraints: {clarifications}",
        "You are a contracts orchestrator. Define entities, APIs, functions, protocols, errors. Output strict JSON."
    )

def generate_files_spec(contracts: Dict[str, Any]):
    return call_orchestrator(
        f"Contracts: {json.dumps(contracts)}",
        "You are a file layout orchestrator. Define files, their role, and which contracts they implement."
    ).get("files", [])

def generate_utilities_spec(files: Dict[str, Any]):
    return call_orchestrator(
        f"Files: {json.dumps(files)}",
        "You are a utility orchestrator. Add meaningful descriptions for each file."
    ).get("files", [])

def generate_tests_spec(project: str, contracts: Dict[str, Any]):
    return call_orchestrator(
        f"Project: {project}\nContracts: {json.dumps(contracts)}",
        "You are a testing orchestrator. Produce integration_tests and test_cases."
    )
def call_validator(role: str, spec: Dict[str, Any], project: str, clarifications: str) -> Dict[str, Any]:
    """
    Generic validator orchestrator.
    role = 'contracts' | 'files' | 'utilities' | 'tests' | 'description'
    Ensures the validator always returns either:
      ✅ pass=True
      ❌ pass=False with issues + suggestion
    """
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a {role} validator.\n"
                        f"Check if the {role} spec is complete, consistent, and useful.\n"
                        f"If valid → return JSON: {{'pass': true}}.\n"
                        f"If invalid → return JSON: {{'pass': false, 'issues': [...], 'suggestion': '...'}}.\n"
                        f"Never return empty or invalid JSON. Always explain why if failing."
                    )
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "project": project,
                        "clarifications": clarifications,
                        "spec": spec
                    })
                }
            ]
        )

        text = resp["choices"][0]["message"]["content"]
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                parsed = json.loads(text[start:end+1])
                # Guarantee structure
                if parsed.get("pass") is True:
                    return {"pass": True, "issues": [], "suggestion": ""}
                else:
                    return {
                        "pass": False,
                        "issues": parsed.get("issues", ["Unspecified issues"]),
                        "suggestion": parsed.get("suggestion", "No suggestion provided")
                    }
            except:
                return {"pass": False, "issues": ["Validator returned invalid JSON"], "suggestion": "Retry with stricter format"}
        return {"pass": False, "issues": ["Validator returned no JSON"], "suggestion": "Retry with stricter format"}

    except Exception as e:
        return {"pass": False, "issues": [f"Validator crashed: {e}"], "suggestion": "Retry"}

# ====== Flask Route ======
# ====== Flask Route ======
@agents_bp.route("/orchestrator", methods=["POST", "OPTIONS"])
@cross_origin(origins=["https://thehustlerbot.com"])
def orchestrator():
    if request.method == "OPTIONS":
        return ("", 200)

    body = request.get_json(force=True) or {}
    user_id = body.get("user_id", "default")
    project = body.get("project", "").strip()
    clarifications = body.get("clarifications", "").strip()

    if user_id not in user_sessions:
        user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}

    session = user_sessions[user_id]

    if session["stage"] == "project":
        if not project:
            return jsonify({"role": "assistant", "content": "What is your project idea?"})
        session["project"] = project
        session["stage"] = "clarifications"
        return jsonify({"role": "assistant", "content": "Do you have any preferences, requirements, or constraints? (Optional)"})

    if session["stage"] == "clarifications":
        session["clarifications"] = clarifications or project
        session["stage"] = "done"

        try:
            # --- Run orchestrators with validator + retries ---
            def run_with_validation(name, generator, validator_role, *args, max_retries=3):
             for attempt in range(max_retries):
              spec = generator(*args)
             result = call_validator(validator_role, spec, session["project"], session["clarifications"])
             if result["pass"]:
             return spec, []
             else:
             if attempt < max_retries - 1:
                # Only inject suggestion if the last arg is a string
                if isinstance(args[-1], str):
                    args = (*args[:-1], args[-1] + " " + result["suggestion"])
                # Otherwise just retry with the same args
              if attempt == max_retries - 1:
             return spec, result["issues"]
             return {}, ["Validator gave up after retries"]


            # ---- Orchestrators ----
            description_spec, desc_issues = run_with_validation(
                "Description", generate_description_spec, "description", session["project"], session["clarifications"]
            )
            contracts_spec, contract_issues = run_with_validation(
                "Contracts", generate_contracts_spec, "contracts", session["project"], session["clarifications"]
            )
            files_spec, file_issues = run_with_validation(
                "Files", generate_files_spec, "files", contracts_spec
            )
            utilities_spec, util_issues = run_with_validation(
                "Utilities", generate_utilities_spec, "utilities", files_spec
            )
            tests_spec, test_issues = run_with_validation(
                "Tests", generate_tests_spec, "tests", session["project"], contracts_spec
            )

            merged = merge_specs({
                "description": description_spec,
                "contracts": contracts_spec,
                "files": files_spec,
                "utilities": utilities_spec,
                "tests": tests_spec
            })

            final = boost_spec_depth(merged)
            project_state[session["project"]] = final
            save_state(project_state)

            agent_outputs = run_agents_for_spec(final)

            return jsonify([
                {"role": "orchestrator", "name": "Description", "content": description_spec, "issues": desc_issues},
                {"role": "orchestrator", "name": "Contracts", "content": contracts_spec, "issues": contract_issues},
                {"role": "orchestrator", "name": "Files", "content": files_spec, "issues": file_issues},
                {"role": "orchestrator", "name": "Utilities", "content": utilities_spec, "issues": util_issues},
                {"role": "orchestrator", "name": "Tests", "content": tests_spec, "issues": test_issues},
                {"role": "assistant", "status": "MERGED_SPEC", "content": final, "agents_output": agent_outputs}
            ])

        except Exception as e:
            return jsonify({"role": "assistant", "content": f"❌ Failed to generate project: {e}"}), 500

    return jsonify({"role": "assistant", "content": "What is your project idea?"})
