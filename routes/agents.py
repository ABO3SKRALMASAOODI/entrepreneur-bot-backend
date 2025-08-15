# routes/orchestrator.py

from flask import Blueprint, request, jsonify
import os, json, re, hashlib
from datetime import datetime
import openai
from pathlib import Path
from typing import Dict, Any
from routes.agents_pipeline import run_agents_for_spec

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
    "Your output must be FINAL, COMPLETE, and ZERO-AMBIGUITY so that 100+ independent coding agents "
    "can implement their files in isolation and when combined, the system runs flawlessly without manual fixes.\n"
    "--- UNIVERSAL COMPATIBILITY RULES ---\n"
    "1. Fully incorporate ALL user requirements into every relevant section.\n"
    "2. For EVERY function in function_contract_manifest:\n"
    "   - Provide purpose, exact input/output types, preconditions, postconditions, possible errors, side effects.\n"
    "   - Provide 'steps' — explicit, numbered pseudocode containing exact imports, method calls, database queries, API calls, and config constant references.\n"
    "   - Never use vague instructions like 'check database' — always reference the exact class/method/file to call.\n"
    "   - Always include at least 5 steps unless the function is trivially one line.\n"
    "3. Define ALL data structures with exact field names, types, nullability, default values, constraints.\n"
    "4. All constants, enums, config keys, environment variables, base URLs, and endpoint routes must be centralized in config.py or constants.py — no hardcoding.\n"
    "5. All API endpoint paths must be centralized in api_endpoints.py.\n"
    "6. Inter-agent protocols must have step-by-step flow sequences, including success/failure handling, with concrete examples.\n"
    "7. Dependency graph must avoid circular imports — all shared imports come from shared_schemas.\n"
    "8. Test cases must validate: data integrity, protocol compliance, cross-agent integration, and ordering.\n"
    "9. Scale to 100–200 agents by splitting into smallest coherent responsibilities.\n"
    "10. Use strict naming conventions (snake_case for functions, PascalCase for classes, UPPER_SNAKE_CASE for constants).\n"
    "11. Every collection must define sort key and order.\n"
    "12. requirements.txt must have pinned versions.\n"
    "13. All nullable fields must be Optional with explicit defaults.\n"
    "14. Populate EVERY section — never leave {} or [].\n"
    "15. Output strictly valid JSON — no markdown, no comments.\n"
    "16. Include a Global Reference Index for all files, functions, agents, and classes.\n"
    "17. Include an Error Decision Table mapping codes → conditions → HTTP status.\n"
    "18. Include example inputs/outputs for ALL APIs and major functions.\n"
    "19. Make sure all functions in function_contract_manifest are cross-file aware — reference the exact DB schema tables, service classes, and protocols defined elsewhere in the spec.\n"
)

# ===== Spec Template =====
SPEC_TEMPLATE = """ Project: {project} Preferences/Requirements: {clarifications}
Produce STRICT JSON with every section fully populated.
{
  "version": "12.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<comprehensive summary including: {clarifications}>",
  "project_type": "<auto-detected type>",
  "target_users": ["<primary user groups>"],
  "tech_stack": {
    "language": "<main language>",
    "framework": "<main framework>",
    "database": "<db if any>"
  },
  "global_naming_contract": {
    "agent_prefix": "<prefix>",
    "entity_suffix": "_entity",
    "service_suffix": "_service",
    "protocol_suffix": "_protocol",
    "test_suffix": "_test"
  },
  "data_dictionary": [
    {"name": "<field>", "type": "<type>", "description": "<meaning>", "nullable": "<true/false>", "default": "<value or null>"}
  ],
  "shared_schemas": {shared_schemas},
  "protocol_schemas": "<Detailed schemas for all inter-agent messages with versioning, format, and example payloads>",
  "errors_module": "<Custom exceptions + Error Decision Table mapping error codes to conditions and HTTP statuses>",
  "function_contract_manifest": {
    "functions": [
        {
            "file": "<filename>",
            "name": "<func_name>",
            "description": "<what it does>",
            "params": {"<param>": "<type>"},
            "return_type": "<type>",
            "errors": ["<error_code>"],
            "steps": [
                "Step 1: Import all required classes and functions from the correct files, e.g., DatabaseService from db_service.py, ServiceResponse from core_shared_schemas.py.",
                "Step 2: Create or access required service or database instances using config.py constants where applicable.",
                "Step 3: Perform the primary validation or computation task, explicitly calling the relevant methods defined in other files.",
                "Step 4: Handle error conditions by returning ServiceResponse objects with correct Status and ErrorCode enums.",
                "Step 5: On success, perform all necessary updates, commits, or responses exactly as specified.",
                "Step 6: Return the final ServiceResponse object with the correct success message and any data required."
            ],
            "example_input": { "example_field": "value" },
            "example_output": { "example_field": "value" }
        }
    ]
},
  "interface_stub_files": [
    {"file": "config.py", "description": "Centralized configuration and constants"},
    {"file": "api_endpoints.py", "description": "Centralized API endpoint paths"},
    {"file": "requirements.txt", "description": "Pinned dependencies for consistent environment"}
  ],
  "agent_blueprint": [
    {"name": "<AgentName>", "description": "<Role in system implementing: {clarifications}>"}
  ],
  "api_contracts": [
    {
      "endpoint": "<url>",
      "method": "<HTTP method>",
      "request_schema": "<schema>",
      "response_schema": "<schema>",
      "example_request": { "example_field": "value" },
      "example_response": { "example_field": "value" }
    }
  ],
  "db_schema": [
    {
      "table": "<table>",
      "columns": [
        {"name": "<col>", "type": "<type>", "constraints": "<constraints>", "nullable": "<true/false>", "default": "<value or null>"}
      ]
    }
  ],
  "domain_specific": {"user_constraints": "{clarifications}"},
  "inter_agent_protocols": [
    {"protocol": "<name>", "description": "<flow with steps and failure handling>"}
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
    {"path": "test_schema_hash.py", "code": "import hashlib; assert hashlib.sha256(open('core_shared_schemas.py').read().encode()).hexdigest() == '{core_hash}'"},
    {"path": "test_protocol_roundtrip.py", "code": "# Verify protocol roundtrip serialization/deserialization"},
    {"path": "test_end_to_end.py", "code": "# Verify main user journey across agents passes"}
  ],
  "test_cases": [
    {"description": "<test aligned with: {clarifications}>", "input": "<input>", "expected_output": "<output>"}
  ]
}
""".replace("{shared_schemas}", json.dumps(CORE_SHARED_SCHEMAS)).replace("{core_hash}", CORE_SCHEMA_HASH)

# ===== Complexity Estimator =====
def estimate_complexity(spec: Dict[str, Any]) -> int:
    endpoints = len(spec.get("api_contracts", []))
    db_tables = len(spec.get("db_schema", []))
    functions = len(spec.get("function_contract_manifest", {}).get("functions", []))
    protocols = len(spec.get("inter_agent_protocols", []))
    score = (endpoints * 2) + (db_tables * 3) + (functions * 1.5) + (protocols * 2)
    return max(5, int(score))

# ===== File Splitting =====
def split_large_modules(base_file: str, est_loc: int, max_loc: int = 1200) -> list:
    skip_split_keywords = ["config", "constants", "shared", "schemas", "api_endpoints", "requirements", "test"]
    if any(k in base_file.lower() for k in skip_split_keywords) and est_loc <= 2500:
        return [base_file]
    if est_loc <= max_loc:
        return [base_file]
    num_parts = (est_loc // max_loc) + 1
    return [f"{base_file.rsplit('.', 1)[0]}_part{i+1}.py" for i in range(num_parts)]

 def enforce_constraints(spec: Dict[str, Any], clarifications: str) -> Dict[str, Any]:
    if clarifications.strip():
        spec.setdefault("domain_specific", {})
        spec["domain_specific"]["user_constraints"] = clarifications
    if clarifications not in spec.get("description", ""):
        spec["description"] = f"{spec.get('description', '')} | User constraints: {clarifications}"

    required_files = [
        ("config.py", "Centralized configuration and constants"),
        ("api_endpoints.py", "Centralized API endpoint paths"),
        ("requirements.txt", "Pinned dependencies for consistent environment"),
        ("core_shared_schemas.py", "Universal shared schemas for all agents"),
    ]
    for fname, desc in required_files:
        if not any(f.get("file") == fname for f in spec.get("interface_stub_files", [])):
            spec.setdefault("interface_stub_files", []).append({"file": fname, "description": desc})

    all_files = set()

    # From interface stub files
    for f in spec.get("interface_stub_files", []):
        if isinstance(f, dict) and "file" in f and f["file"]:
            all_files.add(f["file"])

    # From dependency graph
    for dep in spec.get("dependency_graph", []):
        if isinstance(dep, dict):
            if "file" in dep and dep["file"]:
                all_files.add(dep["file"])
            for d in dep.get("dependencies", []):
                if isinstance(d, str) and d.strip():
                    all_files.add(d.strip())

    # From global reference index
    for ref in spec.get("global_reference_index", []):
        if isinstance(ref, dict) and "file" in ref and ref["file"]:
            all_files.add(ref["file"])

    # From function contract manifest
    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if isinstance(func, dict) and "file" in func and func["file"]:
            all_files.add(func["file"])

    complexity_score = min(estimate_complexity(spec), 12)
    expanded_files = set()
    for file_name in all_files:
        if "service" in file_name:
            est_loc = 400
        elif "test" in file_name:
            est_loc = 150
        elif "app" in file_name or "main" in file_name:
            est_loc = 600
        else:
            est_loc = 120
        est_loc *= min(complexity_score / 5, 2.0)
        expanded_files.update(split_large_modules(file_name, int(est_loc)))

    spec["agent_blueprint"] = []
    for file_name in sorted(expanded_files):
        base_name = file_name.rsplit(".", 1)[0]
        agent_name = "".join(word.capitalize() for word in base_name.split("_")) + "Agent"
        spec["agent_blueprint"].append({
            "name": agent_name,
            "description": f"Responsible for implementing {file_name} exactly as specified in the spec."
        })

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
            model="gpt-4o-mini", temperature=0.05,
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
            model="gpt-4o-mini", temperature=0.05,
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
            agent_outputs = run_agents_for_spec(spec)
            return jsonify({
                "role": "assistant",
                "spec": spec,
                "content": json.dumps(spec, indent=2),
                "agents_output": agent_outputs
            })
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
                agent_outputs = run_agents_for_spec(spec)
                return jsonify({
                    "role": "assistant",
                    "spec": spec,
                    "content": json.dumps(spec, indent=2),
                    "agents_output": agent_outputs
                })
            except Exception as e:
                return jsonify({"role": "assistant", "content": f"❌ Failed to generate spec: {e}"})

    user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}
    return jsonify({"role": "assistant", "content": "What is your project idea?"})
