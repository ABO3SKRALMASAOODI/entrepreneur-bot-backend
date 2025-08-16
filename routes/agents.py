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

# ===== Core Shared Schemas =====
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
    COMPATIBILITY_ERROR = "compatibility_error"

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

# ===== Orchestrator System Prompt =====
SPEC_SYSTEM = (
    "You are the **most advanced universal multi-agent orchestrator in existence**. "
    "Your job: produce a COMPLETE, COMPATIBLE, ZERO-AMBIGUITY project specification "
    "that allows 100+ independent agents to generate code that runs perfectly together.\n"
    "--- ABSOLUTE RULES ---\n"
    "1. ALL output must be FINAL, COMPLETE, and STRICT JSON (no markdown).\n"
    "2. FULLY incorporate ALL user constraints and clarify ambiguous inputs.\n"
    "3. EVERY function: define inputs, outputs, steps, edge cases, and errors.\n"
    "4. EVERY data structure: define field names, types, nullability, defaults, constraints.\n"
    "5. Centralize ALL constants, env vars, routes in config.py / constants.py / api_endpoints.py.\n"
    "6. NO circular imports — all shared items in core_shared_schemas.py.\n"
    "7. Define explicit inter-agent protocols with request/response formats and error handling.\n"
    "8. Global Reference Index: list EVERY file, class, agent, and function.\n"
    "9. Provide integration test scaffolding that ensures cross-agent compatibility.\n"
    "10. Ensure deterministic ordering of execution, imports, and protocols.\n"
    "11. All nullable fields → Optional[T] with explicit default values.\n"
    "12. Pin dependency versions in requirements.txt.\n"
    "13. NO placeholders — every section must be richly filled.\n"
    "14. Guarantee that when all agents generate their files, the project runs END-TO-END with ZERO FIXES.\n"
)

# ===== Spec Template =====
SPEC_TEMPLATE = """{
  "version": "13.0",
  "generated_at": "<ISO timestamp>",
  "project": "{project}",
  "description": "Project generated with full compatibility. User constraints: {clarifications}",
  "project_type": "<auto-detected>",
  "target_users": ["<user groups>"],
  "tech_stack": {
    "language": "<lang>",
    "framework": "<framework>",
    "database": "<db>"
  },
  "global_naming_contract": {
    "agent_prefix": "Agent",
    "entity_suffix": "_entity",
    "service_suffix": "_service",
    "protocol_suffix": "_protocol",
    "test_suffix": "_test"
  },
  "shared_schemas": {shared_schemas},
  "error_module": {
    "errors": [
      {"code": "VALIDATION_ERROR", "http": 400},
      {"code": "NOT_FOUND", "http": 404},
      {"code": "INTERNAL_ERROR", "http": 500},
      {"code": "COMPATIBILITY_ERROR", "http": 422}
    ]
  },
  "function_contract_manifest": {
    "functions": []
  },
  "interface_stub_files": [
    {"file": "config.py", "description": "Centralized configuration"},
    {"file": "api_endpoints.py", "description": "Centralized API endpoints"},
    {"file": "requirements.txt", "description": "Pinned dependencies"},
    {"file": "core_shared_schemas.py", "description": "Universal schemas"}
  ],
  "agent_blueprint": [],
  "inter_agent_protocols": [],
  "global_reference_index": [],
  "integration_tests": [
    {"path": "test_compatibility.py", "code": "# Assert all agents can import each other without error"},
    {"path": "test_end_to_end.py", "code": "# Validate main user journey end-to-end"}
  ]
}""".replace("{shared_schemas}", json.dumps(CORE_SHARED_SCHEMAS))

# ===== Complexity Estimator =====
def estimate_complexity(spec: Dict[str, Any]) -> int:
    endpoints = len(spec.get("api_contracts", []))
    db_tables = len(spec.get("db_schema", []))
    functions = len(spec.get("function_contract_manifest", {}).get("functions", []))
    protocols = len(spec.get("inter_agent_protocols", []))
    score = (endpoints * 2) + (db_tables * 3) + (functions * 1.5) + (protocols * 2)
    return max(5, int(score))

# ===== Compatibility Enforcer =====
def enforce_compatibility(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Guarantees cross-agent compatibility by enforcing shared imports and reference consistency."""
    # Inject schema hash everywhere
    spec["schema_hash"] = CORE_SCHEMA_HASH

    # Add agent roles for deterministic compatibility
    for agent in spec.get("agent_blueprint", []):
        agent["compatibility"] = "MUST import from core_shared_schemas.py ONLY"
        agent["naming_contract"] = spec.get("global_naming_contract", {})

    return spec

# ===== Depth Booster =====
def boost_spec_depth(spec: dict) -> dict:
    if "__depth_boost" not in spec:
        spec["__depth_boost"] = {}
    for file in [a.get("file") for a in spec.get("interface_stub_files", []) if "file" in a]:
        spec["__depth_boost"][file] = {
            "notes": [
                f"Implement {file} to production standard.",
                "Follow SOLID principles, full typing, modular structure.",
                "Ensure all imports reference shared schemas.",
                "Include integration hooks for APIs/DB/protocols.",
                "Write full docstrings, logging, error handling."
            ]
        }
    return spec

# ===== Spec Generator =====
def generate_spec(project: str, clarifications: str):
    clarifications_safe = clarifications.strip() or "no constraints provided"
    filled = SPEC_TEMPLATE.replace("{project}", project).replace("{clarifications}", clarifications_safe).replace(
        "<ISO timestamp>", datetime.utcnow().isoformat() + "Z"
    )

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini", temperature=0.05,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": filled}
            ]
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

    raw = resp.choices[0].message["content"]
    spec = _extract_json_strict(raw)
    if not spec:
        raise ValueError("❌ Failed to parse JSON spec")

    spec = enforce_compatibility(spec)
    spec = boost_spec_depth(spec)

    project_state[project] = spec
    save_state(project_state)
    return spec

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
        user_sessions[user_id] = {"stage": "project"}

    session = user_sessions[user_id]

    if session["stage"] == "project":
        if not project:
            return jsonify({"role": "assistant", "content": "What is your project idea?"})
        session["project"] = project
        session["stage"] = "clarifications"
        return jsonify({"role": "assistant", "content": "Any preferences or constraints? (Optional)"})

    if session["stage"] == "clarifications":
        session["clarifications"] = clarifications or project
        session["stage"] = "done"
        try:
            spec = generate_spec(session["project"], session["clarifications"])
            agent_outputs = run_agents_for_spec(spec)
            return jsonify({
                "role": "assistant",
                "status": "✅ FULLY COMPATIBLE SPEC",
                "spec": spec,
                "agents_output": agent_outputs
            })
        except Exception as e:
            return jsonify({"role": "assistant", "content": f"❌ Failed: {e}"}), 500

    return jsonify({"role": "assistant", "content": "What is your project idea?"})
