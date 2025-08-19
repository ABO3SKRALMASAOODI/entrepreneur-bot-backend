# routes/orchestrator.py
from flask import Blueprint, request, jsonify
import os, json, re, hashlib
from datetime import datetime
import openai
from pathlib import Path
from typing import Dict, Any
from routes.agents_pipeline import run_agents_for_spec
from flask_cors import cross_origin

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

# ===== Session Store =====
user_sessions = {}

# ===== Strict JSON Extractor =====
def _extract_json_strict(text: str):
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end+1])
    except json.JSONDecodeError:
        return None

import time


def run_orchestrator(stage: str, input_data: dict) -> dict:
    """Runs a single orchestrator stage with strict JSON extraction, timeout & retries."""
    system_msg = ORCHESTRATOR_STAGES[stage]
    retries = 3
    backoff = 2  # exponential backoff base

    for attempt in range(retries):
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                temperature=0.2,
                request_timeout=180,  # ⏰ extend timeout
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": json.dumps(input_data, indent=2)}
                ]
            )
            raw = resp["choices"][0]["message"]["content"]
            spec = _extract_json_strict(raw)

            if spec:
                return spec  # ✅ success
            else:
                # Retry with explicit JSON reminder
                retry_msg = "⚠️ Output was not valid JSON. Please return ONLY strict JSON for the spec."
                resp = openai.ChatCompletion.create(
                    model="gpt-4o-mini",
                    temperature=0.2,
                    request_timeout=180,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": retry_msg}
                    ]
                )
                raw = resp["choices"][0]["message"]["content"]
                spec = _extract_json_strict(raw)
                if spec:
                    return spec

        except Exception as e:
            print(f"⚠️ Orchestrator stage {stage} failed on attempt {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(backoff ** attempt)  # exponential backoff
            else:
                raise RuntimeError(f"Orchestrator stage {stage} failed after {retries} retries: {e}")

    raise RuntimeError(f"Stage {stage} did not produce valid JSON after retries.")

# ===== Universal Core Schema =====
CORE_SHARED_SCHEMAS = """# core_shared_schemas.py
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional
import datetime

class Status(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"

class ErrorCode(str, Enum):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    INTERNAL_ERROR = "internal_error"

@dataclass
class Entity:
    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

@dataclass
class ServiceResponse:
    status: Status
    message: str
    data: Optional[Any] = None

@dataclass
class ServiceRequest:
    metadata: Dict[str, Any]
    payload: Dict[str, Any]
"""
CORE_SCHEMA_HASH = hashlib.sha256(CORE_SHARED_SCHEMAS.encode()).hexdigest()

# ===== Universal Orchestrator Instructions =====
# ===== Orchestrator Pipeline Stages =====
ORCHESTRATOR_STAGES = {
    "describer": "You are Orchestrator 0 (Project Describer). "
                 "Your ONLY job is to restate the project clearly, "
                 "define user story, target users, and suggest a tech stack. "
                 "STRICT JSON keys: project_summary, user_story, suggested_stack.",

    "scoper": "You are Orchestrator 1 (Scoper). "
              "Input: project description. "
              "Output: full list of files needed. "
              "Each file: file, category, description. "
              "STRICT JSON array of file objects only.",

    "contractor": "You are Orchestrator 2 (Contractor). "
                  "Input: project + files. "
                  "Output: contracts: entities, apis, functions, protocols, errors. "
                  "Every contract must be complete with types, examples, conditions.",

    "architect": "You are Orchestrator 3 (Architect). "
                 "Input: project + files + contracts. "
                 "Output: assign contracts to files, agent_blueprint, dependency_graph, execution_plan, global_reference_index.",

    "booster": "You are Orchestrator 4 (Detail Booster). "
               "Input: enriched spec. "
               "Output: add __depth_boost for each file with notes (SOLID, logging, testing, etc.).",

    "verifier": "You are Orchestrator 5 (Verifier). "
                "Input: boosted spec. "
                "Output: FINAL VERIFIED JSON. Ensure every API has a backend file, "
                "every file has agent, every function has test, errors map to http_status."
}


# ===== Spec Template =====
SPEC_TEMPLATE = """ Project: {project} Preferences/Requirements: {clarifications} Produce STRICT JSON with every section fully populated.
{
  "version": "12.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<comprehensive summary including: {clarifications}>",
  "project_type": "<auto-detected type>",
  "target_users": ["<primary user groups>"],
  "tech_stack": {
    "language": "<main language>",
    "framework": "<framework if any>",
    "database": "<database if any>"
  },
  "contracts": {
    "entities": [
      {"name": "<EntityName>", "fields": {"field": "type"}, "description": "<meaning>"}
    ],
    "apis": [
      {
        "name": "<APIName>",
        "endpoint": "<url>",
        "method": "<HTTP method or protocol>",
        "request_schema": {"field": "type"},
        "response_schema": {"field": "type"},
        "example_request": {"field": "value"},
        "example_response": {"field": "value"}
      }
    ],
    "functions": [
      {
        "name": "<func_name>",
        "description": "<what it does>",
        "params": {"<param>": "<type>"},
        "return_type": "<type>",
        "errors": ["<error_code>"],
        "steps": ["Step 1: ...", "Step 2: ..."],
        "example_input": {"field": "value"},
        "example_output": {"field": "value"}
      }
    ],
    "protocols": [
      {"name": "<ProtocolName>", "flow": ["Step 1: ...", "Step 2: ..."]}
    ],
    "errors": [
      {"code": "<ERROR_CODE>", "condition": "<when triggered>", "http_status": <int>}
    ]
  },
  "files": [
    {
      "file": "<path/filename>",
      "language": "<language>",
      "description": "<role in project>",
      "implements": ["<contracts: apis, functions, protocols, entities>"],
      "dependencies": ["<other files>"]
    }
  ],
  "dependency_graph": [
    {"file": "<filename>", "dependencies": ["<dep1>", "<dep2>"]}
  ],
  "execution_plan": [
    {"step": 1, "description": "<implementation step>"}
  ],
  "global_reference_index": [
    {"file": "<file>", "functions": ["<func1>"], "classes": ["<class1>"], "agents": ["<agent1>"]}
  ],
  "integration_tests": [
    {"path": "test_protocol_roundtrip.py", "code": "# Verify protocol roundtrip"}
  ],
  "test_cases": [
    {"description": "<test aligned with: {clarifications}>", "input": "<input>", "expected_output": "<output>"}
  ]
}
"""

# ===== Constraint Enforcement =====
def enforce_constraints(spec: Dict[str, Any], clarifications: str) -> Dict[str, Any]:
    """ Ensures universal constraints. """
    if clarifications.strip():
        spec.setdefault("domain_specific", {})
        spec["domain_specific"]["user_constraints"] = clarifications
        if clarifications not in spec.get("description", ""):
            spec["description"] = f"{spec.get('description', '')} | User constraints: {clarifications}"

    required_files = [
        ("config.py", "Centralized configuration and constants"),
        ("requirements.txt", "Pinned dependencies for consistent environment"),
        ("core_shared_schemas.py", "Universal shared schemas for all agents"),
    ]
    for fname, desc in required_files:
        if not any(f.get("file") == fname for f in spec.get("files", [])):
            spec.setdefault("files", []).append({
                "file": fname,
                "language": "python",
                "description": desc,
                "implements": [],
                "dependencies": []
            })

    all_files = {f["file"] for f in spec.get("files", []) if "file" in f}
    expanded_files = all_files
    spec["agent_blueprint"] = []
    for file_name in sorted(expanded_files):
        base_name = file_name.rsplit(".", 1)[0]
        agent_name = "".join(word.capitalize() for word in base_name.split("_")) + "Agent"
        spec["agent_blueprint"].append({
            "name": agent_name,
            "description": f"Responsible for implementing {file_name} exactly as specified in the contracts."
        })

    if not spec.get("global_reference_index"):
        spec["global_reference_index"] = []
    for f in spec.get("files", []):
        entry = {"file": f.get("file"), "functions": [], "classes": [], "agents": []}
        if not any(e["file"] == entry["file"] for e in spec["global_reference_index"]):
            spec["global_reference_index"].append(entry)

    return spec

# ===== Depth Booster =====
def boost_spec_depth(spec: dict) -> dict:
    if "__depth_boost" not in spec:
        spec["__depth_boost"] = {}
    all_files = {f["file"] for f in spec.get("files", []) if "file" in f}
    for file_name in all_files:
        spec["__depth_boost"].setdefault(file_name, {})
        spec["__depth_boost"][file_name]["notes"] = [
            f"Implement {file_name} with production-grade standards.",
            "Follow SOLID principles, modular structure, and type hints everywhere.",
            "Include robust error handling with mapped error codes.",
            "Add INFO + ERROR logging; include correlation IDs for requests.",
            "Ensure security best practices (sanitize inputs, protect secrets).",
            "Optimize for performance: efficient algorithms, avoid bottlenecks.",
            "Design deterministic, unit-testable functions with clear contracts.",
            "Respect API/entity/function definitions in contracts 100% literally.",
            "Add full docstrings, inline comments for tricky logic.",
            "Ensure compatibility: no drift in naming, signatures, or protocols."
        ]
        contracts = spec.get("contracts", {})
        spec["__depth_boost"][file_name]["contracts"] = {
            "entities": contracts.get("entities", []),
            "apis": contracts.get("apis", []),
            "functions": contracts.get("functions", []),
            "protocols": contracts.get("protocols", []),
            "errors": contracts.get("errors", []),
        }
    return spec

def orchestrator_pipeline(project: str, clarifications: str) -> dict:
    """Sequentially runs all orchestrators and produces final verified spec."""
    # Stage 0 - Project Describer
    desc = run_orchestrator("describer", {"project": project, "clarifications": clarifications})

    # Stage 1 - Scoper
    files = run_orchestrator("scoper", desc)

    # Stage 2 - Contractor
    contracts = run_orchestrator("contractor", {**desc, **files})

    # Stage 3 - Architect
    arch = run_orchestrator("architect", {**desc, **files, **contracts})

    # Stage 4 - Booster
    boosted = run_orchestrator("booster", arch)

    # Stage 5 - Verifier
    final_spec = run_orchestrator("verifier", boosted)

    project_state[project] = final_spec
    save_state(project_state)
    return final_spec

# ===== Orchestrator Route =====
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
        if incoming_constraints.strip():
            session["clarifications"] = incoming_constraints.strip()
            session["stage"] = "done"
        try:
            spec = orchestrator_pipeline(session["project"], session["clarifications"])
            agent_outputs = run_agents_for_spec(spec)
            return jsonify({
                "role": "assistant",
                "status": "FULLY VERIFIED",
                "spec": spec,
                "agents_output": agent_outputs
            })
        except Exception as e:
            return jsonify({"role": "assistant", "content": f"❌ Failed to generate verified project: {e}"}), 500

    user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}
    return jsonify({"role": "assistant", "content": "What is your project idea?"})
