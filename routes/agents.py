from flask import Blueprint, request, jsonify
import os, json, re, hashlib
from datetime import datetime
import openai
from pathlib import Path

agents_bp = Blueprint("agents", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ===== Persistent Storage =====
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

# ===== In-memory session store =====
user_sessions = {}

# ===== JSON extractor =====
def _extract_json_safe(text: str):
    """Extract JSON safely from LLM output."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.MULTILINE).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    start = min([p for p in [s.find("{"), s.find("[")] if p != -1] or [-1])
    if start != -1:
        for end in range(len(s), start, -1):
            try:
                return json.loads(s[start:end])
            except Exception:
                continue
    return None

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

# ===== System Prompt =====
SPEC_SYSTEM = (
    "You are the most advanced AI project orchestrator in existence. "
    "Your goal is to produce a FINAL, COMPLETE, ZERO-AMBIGUITY universal multi-agent specification "
    "that ensures perfect compatibility across 100+ agents for ANY project type.\n"
    "--- ABSOLUTE RULES ---\n"
    "1. Always include the universal core schema in 'shared_schemas'.\n"
    f"2. Lock the core schema hash to '{CORE_SCHEMA_HASH}'.\n"
    "3. Define a full function_contract_manifest.json for ALL functions with names, params, return types, and errors.\n"
    "4. All interface_stub_files must import shared types — no local type definitions allowed.\n"
    "5. Generate integration tests that verify schema hashes, manifest compliance, and API contract adherence.\n"
    "6. No prose in output — STRICT JSON only.\n"
    "--- REQUIRED OUTPUT KEYS ---\n"
    "global_naming_contract, data_dictionary, shared_schemas, protocol_schemas, errors_module, "
    "function_contract_manifest, interface_stub_files, agent_blueprint, api_contracts, db_schema, domain_specific, "
    "inter_agent_protocols, dependency_graph, execution_plan, integration_tests, test_cases."
)

# ===== Spec Template =====
SPEC_TEMPLATE = """
Project: {project}
Preferences/Requirements: {clarifications}

Produce STRICT JSON:
{{
  "version": "9.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<universal project spec>",
  "project_type": "<auto-detected>",
  "target_users": [],
  "tech_stack": {{}},
  "global_naming_contract": {{}},
  "data_dictionary": [],
  "shared_schemas": {shared_schemas},
  "protocol_schemas": "Pydantic/BaseModel schemas for inter-agent communication",
  "errors_module": "Custom exception classes extending BaseError",
  "function_contract_manifest": {{}},
  "interface_stub_files": [],
  "agent_blueprint": [],
  "api_contracts": [],
  "db_schema": [],
  "domain_specific": {{}},
  "inter_agent_protocols": [],
  "dependency_graph": [],
  "execution_plan": [],
  "integration_tests": [
    {{
      "path": "test_schema_hash.py",
      "code": "import hashlib; assert hashlib.sha256(open('core_shared_schemas.py').read().encode()).hexdigest() == '{core_hash}'"
    }},
    {{
      "path": "test_manifest_compliance.py",
      "code": "# Validates all implemented functions match the manifest exactly"
    }},
    {{
      "path": "test_api_contracts.py",
      "code": "# Validates OpenAPI/AsyncAPI contracts match implementation"
    }}
  ],
  "test_cases": []
}}
""".replace("{shared_schemas}", json.dumps(CORE_SHARED_SCHEMAS)).replace("{core_hash}", CORE_SCHEMA_HASH)

# ===== Spec Generator =====
def generate_spec(project: str, clarifications: str):
    filled = SPEC_TEMPLATE.replace("{project}", project).replace("{clarifications}", clarifications).replace(
        "<ISO timestamp>", datetime.utcnow().isoformat() + "Z"
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            temperature=0.05,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": filled}
            ],
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

    raw = resp.choices[0].message["content"]
    spec = _extract_json_safe(raw)
    if not spec:
        raise ValueError("❌ Failed to parse JSON spec")
    
    # Save persistent state
    project_state[project] = spec
    save_state(project_state)
    
    return spec

# ===== Orchestrator Route =====
@agents_bp.route("/orchestrator", methods=["POST", "OPTIONS"])
def orchestrator():
    if request.method == "OPTIONS":
        return ("", 200)

    body = request.get_json(force=True) or {}
    user_id = body.get("user_id", "default")
    project = body.get("project", "").strip()
    clarifications = body.get("clarifications", "").strip()

    # Init session for user
    if user_id not in user_sessions:
        user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}

    session = user_sessions[user_id]

    # Stage 1: Get project
    if session["stage"] == "project":
        if not project:
            return jsonify({"role": "assistant", "content": "What is your project idea?"})
        session["project"] = project
        session["stage"] = "clarifications"
        return jsonify({
            "role": "assistant",
            "content": "Do you have any preferences, requirements, or constraints for the implementation? (Optional)"
        })

    # Stage 2: Get preferences and generate spec
    if session["stage"] == "clarifications":
        session["clarifications"] = clarifications if clarifications else "no preference"
        session["stage"] = "done"
        try:
            spec = generate_spec(session["project"], session["clarifications"])
            return jsonify({"role": "assistant", "content": json.dumps(spec, indent=2)})
        except Exception as e:
            return jsonify({"role": "assistant", "content": f"❌ Failed to generate spec: {e}"})

    # Stage 3: Done — reset for new project
    if session["stage"] == "done":
        user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}
        return jsonify({"role": "assistant", "content": "What is your project idea?"})
