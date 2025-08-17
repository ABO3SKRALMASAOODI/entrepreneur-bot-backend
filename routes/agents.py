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
        incoming_constraints = clarifications or project
        session["clarifications"] = incoming_constraints.strip()
        session["stage"] = "done"
        try:
            description_spec = generate_description_spec(session["project"], session["clarifications"])
            contracts_spec = generate_contracts_spec(session["project"], session["clarifications"])
            files_spec = generate_files_spec(contracts_spec)
            utilities_spec = generate_utilities_spec(files_spec)
            tests_spec = generate_tests_spec(session["project"], contracts_spec)

            merged = merge_specs({
                "description": description_spec,
                "contracts": contracts_spec,
                "files": files_spec,
                "utilities": utilities_spec,
                "tests": tests_spec
            })

            errors = validate_spec(merged)
            if errors:
                raise ValueError(f"Spec validation failed: {errors}")

            final = boost_spec_depth(merged)
            project_state[session["project"]] = final
            save_state(project_state)

            agent_outputs = run_agents_for_spec(final)

            return jsonify([
                {"role": "orchestrator", "name": "Description", "content": description_spec},
                {"role": "orchestrator", "name": "Contracts", "content": contracts_spec},
                {"role": "orchestrator", "name": "Files", "content": files_spec},
                {"role": "orchestrator", "name": "Utilities", "content": utilities_spec},
                {"role": "orchestrator", "name": "Tests", "content": tests_spec},
                {"role": "assistant", "status": "MERGED_SPEC", "content": final, "agents_output": agent_outputs}
            ])
        except Exception as e:
            return jsonify({"role": "assistant", "content": f"❌ Failed to generate project: {e}"}), 500

    return jsonify({"role": "assistant", "content": "What is your project idea?"})
