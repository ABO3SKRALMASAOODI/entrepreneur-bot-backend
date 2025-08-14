from flask import Blueprint, request, jsonify
import os, json, re, hashlib
from datetime import datetime
import openai
from pathlib import Path
from typing import Dict, Any

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
SPEC_SYSTEM = (
    "You are the most advanced universal multi-agent project orchestrator in existence. "
    "Your output must be a FINAL, COMPLETE, ZERO-AMBIGUITY multi-file specification such that "
    "100+ independent coding agents can implement their parts in isolation, and when combined, "
    "the system will run flawlessly with zero manual fixes — regardless of project size or type.\n"
    "--- UNIVERSAL COMPATIBILITY RULES ---\n"
    "1. Fully incorporate ALL user-provided preferences/requirements into every relevant section.\n"
    "2. Define ALL data structures with exact field names, types, nullability, default values, constraints.\n"
    "3. For ANY communication (API, function calls, events, message passing), define exact request/response formats, "
    "including required fields, optional fields, ordering, and encoding.\n"
    "4. All constants, enums, config keys, environment variables, base URLs, endpoint routes, and feature flags "
    "must be centralized in config.py or constants.py — no hardcoded values anywhere.\n"
    "5. All API endpoint paths must be centralized in api_endpoints.py and imported — never hardcoded.\n"
    "6. Function contracts must include: purpose, exact input/output types, preconditions, postconditions, possible errors, side effects.\n"
    "7. Inter-agent protocols must have step-by-step flow sequences with success/failure branches, mandatory preconditions, and postconditions.\n"
    "8. Dependency graph must ensure no circular imports and all shared imports come from shared_schemas.\n"
    "9. Test cases must validate: data integrity, protocol compliance, cross-agent integration, and data ordering.\n"
    "10. Scale to 100–200 agents by decomposing into the smallest coherent responsibilities.\n"
    "11. Enforce naming conventions: Functions in snake_case <verb>_<noun>, Classes in PascalCase, Constants in UPPER_SNAKE_CASE.\n"
    "12. All data collections must define sort key and direction in spec.\n"
    "13. All external libraries must be listed in requirements.txt with pinned versions.\n"
    "14. All nullable fields must be marked Optional with default values explicitly stated.\n"
    "15. Populate EVERY spec section — never leave {} or [].\n"
    "16. Always output strictly valid JSON — no commentary, markdown, or extra text.\n"
    "17. Include a Global Reference Index listing ALL files, functions, agents, classes for cross-agent awareness.\n"
    "18. Include an Error Decision Table mapping each error code to conditions and HTTP status.\n"
)

# ===== Spec Template =====
SPEC_TEMPLATE = """
Project: {project}
Preferences/Requirements: {clarifications}

Produce STRICT JSON with every section fully populated, embedding all constraints into:
description, domain_specific, agent_blueprint, api_contracts, db_schema, function_contract_manifest, inter_agent_protocols, dependency_graph, execution_plan, test_cases.

{{
  "version": "12.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<comprehensive summary including: {clarifications}>",
  "project_type": "<auto-detected type>",
  "target_users": ["<primary user groups>"],
  "tech_stack": {{"language": "<main language>", "framework": "<main framework>", "database": "<db if any>"}},
  "global_naming_contract": {{"agent_prefix": "<prefix>", "entity_suffix": "_entity", "service_suffix": "_service", "protocol_suffix": "_protocol", "test_suffix": "_test"}},
  "data_dictionary": [{{"name": "<field>", "type": "<type>", "description": "<meaning>", "nullable": "<true/false>", "default": "<value or null>"}}],
  "shared_schemas": {shared_schemas},
  "protocol_schemas": "<Detailed schemas for all inter-agent messages with versioning and format>",
  "errors_module": "<Custom exception classes + Error Decision Table mapping codes → conditions → HTTP status>",
  "function_contract_manifest": {{"functions": [{{"file": "<filename>", "name": "<func_name>", "description": "<what it does>", "params": {{"param": "<type>"}}, "return_type": "<type>", "errors": ["<error_code>"]}}]}},
  "interface_stub_files": [
    {{"file": "config.py", "description": "Centralized configuration and constants"}},
    {{"file": "api_endpoints.py", "description": "Centralized API endpoint paths"}},
    {{"file": "requirements.txt", "description": "Pinned dependencies for consistent environment"}},
    {{"file": "<filename>", "description": "<interface purpose>"}}
  ],
  "agent_blueprint": [{{"name": "<AgentName>", "description": "<Role in system implementing: {clarifications}">}}],
  "api_contracts": [{{"endpoint": "<url>", "method": "<HTTP method>", "request_schema": "<schema>", "response_schema": "<schema>", "notes": "Implements: {clarifications}"}}],
  "db_schema": [{{"table": "<table>", "columns": [{{"name": "<col>", "type": "<type>", "constraints": "<constraints>", "nullable": "<true/false>", "default": "<value or null>", "notes": "Derived from: {clarifications}"}}]}}],
  "domain_specific": {{"user_constraints": "{clarifications}"}},
  "inter_agent_protocols": [{{"protocol": "<name>", "description": "<flow including: {clarifications}">}}],
  "dependency_graph": [{{"file": "<filename>", "dependencies": ["<dep1>", "<dep2>"], "notes": "Supports: {clarifications}"}}]],
  "execution_plan": [{{"step": 1, "description": "<step implementing: {clarifications}">}}],
  "global_reference_index": [{{"file": "<file>", "functions": ["<func1>", "<func2>"], "classes": ["<class1>"], "agents": ["<agent1>"]}}],
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
      "path": "test_protocol_roundtrip.py",
      "code": "# Verifies message formats can be serialized/deserialized without loss"
    }}
  ],
  "test_cases": [{{"description": "<test aligned with: {clarifications}>", "input": "<input>", "expected_output": "<output>"}}]
}}
""".replace("{shared_schemas}", json.dumps(CORE_SHARED_SCHEMAS)).replace("{core_hash}", CORE_SCHEMA_HASH)

# ===== Constraint Enforcer =====
def enforce_constraints(spec: Dict[str, Any], clarifications: str) -> Dict[str, Any]:
    # Inject constraints into domain_specific and description
    if clarifications.strip():
        spec["domain_specific"]["user_constraints"] = clarifications
        if clarifications not in spec.get("description", ""):
            spec["description"] += f" | User constraints: {clarifications}"

    # Ensure critical stub files exist
    required_files = [
        ("config.py", "Centralized configuration and constants"),
        ("api_endpoints.py", "Centralized API endpoint paths"),
        ("requirements.txt", "Pinned dependencies for consistent environment"),
    ]
    for fname, desc in required_files:
        if not any(f['file'] == fname for f in spec.get('interface_stub_files', [])):
            spec.setdefault("interface_stub_files", []).append({"file": fname, "description": desc})
    return spec

# ===== Spec Generator =====
def generate_spec(project: str, clarifications: str):
    clarifications_raw = clarifications.strip() if clarifications.strip() else "no specific constraints provided"
    clarifications_safe = json.dumps(clarifications_raw)[1:-1]
    project_safe = json.dumps(project)[1:-1]
    filled = SPEC_TEMPLATE.replace("{project}", project_safe).replace("{clarifications}", clarifications_safe).replace(
        "<ISO timestamp>", datetime.utcnow().isoformat() + "Z"
    )

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.05,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": filled}
            ],
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

    raw = resp.choices[0].message["content"]
    spec = _extract_json_strict(raw)

    if not spec:
        retry_prompt = "The previous output was not valid JSON. Output the exact same specification again as STRICT JSON only."
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.05,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": retry_prompt}
            ],
        )
        raw = resp.choices[0].message["content"]
        spec = _extract_json_strict(raw)
        if not spec:
            raise ValueError("❌ Failed to parse JSON spec after retry")

    spec = enforce_constraints(spec, clarifications_raw)
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
        if not session["clarifications"]:
            session["clarifications"] = "no specific constraints provided"
        session["stage"] = "done"
        try:
            spec = generate_spec(session["project"], session["clarifications"])
            return jsonify({"role": "assistant", "spec": spec, "content": json.dumps(spec, indent=2)})
        except Exception as e:
            return jsonify({"role": "assistant", "content": f"❌ Failed to generate spec: {e}"})

    if session["stage"] == "done":
        if project:
            session.update({"stage": "clarifications", "project": project, "clarifications": ""})
            return jsonify({"role": "assistant", "content": "Do you have any preferences, requirements, or constraints? (Optional)"})
        elif clarifications:
            session["clarifications"] = clarifications
            try:
                spec = generate_spec(session["project"], session["clarifications"])
                return jsonify({"role": "assistant", "spec": spec, "content": json.dumps(spec, indent=2)})
            except Exception as e:
                return jsonify({"role": "assistant", "content": f"❌ Failed to generate spec: {e}"})
        user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}
        return jsonify({"role": "assistant", "content": "What is your project idea?"})
