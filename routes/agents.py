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
    """
    Extract the first valid JSON object from a string response.
    Always returns a dict if successful, otherwise raises ValueError.
    """
    if not text:
        return None

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        return None

    try:
        parsed = json.loads(text[start:end+1])
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected dict but got {type(parsed)}: {parsed}")
        return parsed
    except Exception as e:
        raise ValueError(
            f"❌ Failed to parse JSON from model output: {e}\n"
            f"--- RAW TEXT START ---\n{text[:500]}\n--- RAW TEXT END ---"
        )


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
    "2. For EVERY function, provide: purpose, exact input/output types, preconditions, postconditions, possible errors, side effects.\n"
    "3. For EVERY function, also provide 'steps' — explicit, numbered pseudocode that leaves no ambiguity.\n"
    "4. Define ALL data structures with exact field names, types, nullability, default values, constraints.\n"
    "5. All constants, enums, config keys, environment variables, base URLs, and endpoint routes must be centralized in config.py or constants.py — no hardcoding.\n"
    "6. All API endpoint paths must be centralized in api_endpoints.py.\n"
    "7. Inter-agent protocols must have step-by-step flow sequences, including success/failure handling.\n"
    "8. Dependency graph must avoid circular imports — all shared imports come from shared_schemas.\n"
    "9. Test cases must validate: data integrity, protocol compliance, cross-agent integration, and ordering.\n"
    "10. Scale to 100–200 agents by splitting into smallest coherent responsibilities.\n"
    "11. Use strict naming conventions (snake_case for functions, PascalCase for classes, UPPER_SNAKE_CASE for constants).\n"
    "12. Every collection must define sort key and order.\n"
    "13. requirements.txt must have pinned versions.\n"
    "14. All nullable fields must be Optional with explicit defaults.\n"
    "15. Populate EVERY section — never leave {} or [].\n"
    "16. Output strictly valid JSON — no markdown, no comments.\n"
    "17. Include a Global Reference Index for all files, functions, agents, and classes.\n"
    "18. Include an Error Decision Table mapping codes → conditions → HTTP status.\n"
    "19. Include example inputs/outputs for ALL APIs and major functions.\n"
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
          "Step 1: ...",
          "Step 2: ...",
          "Step 3: ..."
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

# ===== Constraint Enforcement =====
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
    for f in spec.get("interface_stub_files", []):
        all_files.add(f["file"])
    for dep in spec.get("dependency_graph", []):
        if "file" in dep:
            all_files.add(dep["file"])
        for d in dep.get("dependencies", []):
            all_files.add(d)
    for ref in spec.get("global_reference_index", []):
        if "file" in ref:
            all_files.add(ref["file"])
    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if "file" in func:
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

def boost_spec_depth(spec: dict) -> dict:
    """
    Expands the orchestrator spec with deep, rich, and highly detailed implementation
    instructions for every file in the project. This guarantees agents receive
    enough content to generate world-class, long, and compatible code.
    """
    if "__depth_boost" not in spec:
        spec["__depth_boost"] = {}

    all_files = set()

    # Gather all file names from various spec sections
    for section in ["interface_stub_files", "agent_blueprint", "function_contract_manifest",
                    "dependency_graph", "global_reference_index"]:
        entries = spec.get(section, [])
        if isinstance(entries, dict):
            entries = entries.get("functions", []) if section == "function_contract_manifest" else []
        for item in entries:
            if isinstance(item, dict) and "file" in item:
                all_files.add(item["file"])
            elif isinstance(item, str):
                all_files.add(item)

    # Populate detailed depth boost for each file
    for file_name in all_files:
        spec["__depth_boost"].setdefault(file_name, {})

        # Example deep pseudocode and considerations
        spec["__depth_boost"][file_name]["notes"] = [
            f"Implement {file_name} with production-grade standards.",
            "Follow SOLID principles, modular structure, and type hints everywhere.",
            "Include full error handling, retries, and failover logic where applicable.",
            "Add comprehensive logging at INFO and ERROR levels.",
            "Ensure security best practices: sanitize inputs, prevent injection attacks, handle secrets properly.",
            "Design for high performance: avoid unnecessary loops, use efficient algorithms and data structures.",
            "Write functions to be unit-testable and deterministic.",
            "Include integration points for APIs, DB, and inter-agent protocols exactly as per spec.",
            "Document every public method and class with docstrings explaining usage and edge cases.",
            "Follow consistent naming and structure to guarantee compatibility with other generated files."
        ]

        # Optional expanded DB/API/protocols (could pull from spec if relevant)
        spec["__depth_boost"][file_name]["db"] = spec.get("db_schema", [])
        spec["__depth_boost"][file_name]["api"] = spec.get("api_contracts", [])
        spec["__depth_boost"][file_name]["protocols"] = spec.get("inter_agent_protocols", [])

    return spec



# ===== Spec Generator =====
def generate_spec(project: str, clarifications: str):
    """
    Generates a fully detailed orchestrator spec for the given project and constraints.
    Agents must output world-class, production-ready code.
    Testers review one file at a time and provide ALL corrections if issues exist.
    """
    clarifications_raw = clarifications.strip() if clarifications.strip() else "no specific constraints provided"
    clarifications_safe = json.dumps(clarifications_raw)[1:-1]
    project_safe = json.dumps(project)[1:-1]
    filled = SPEC_TEMPLATE.replace("{project}", project_safe).replace("{clarifications}", clarifications_safe).replace(
        "<ISO timestamp>", datetime.utcnow().isoformat() + "Z"
    )

    try:
        # === Generate initial spec with orchestrator ===
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # ⚡ legacy client call
            temperature=0.25,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": filled}
            ]
        )
        raw = resp["choices"][0]["message"]["content"]
        spec = _extract_json_strict(raw)

        # === Retry once if JSON invalid ===
        if not isinstance(spec, dict):
            retry_prompt = (
                "The previous output was not valid JSON. "
                "Output the exact same specification again as STRICT JSON only."
            )
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                temperature=0.25,
                messages=[
                    {"role": "system", "content": SPEC_SYSTEM},
                    {"role": "user", "content": retry_prompt}
                ]
            )
            raw = resp["choices"][0]["message"]["content"]
            spec = _extract_json_strict(raw)

        # ✅ Final validation
        if not isinstance(spec, dict):
            raise ValueError(f"Spec is not a dict. Got {type(spec)} → {spec}")

        # === Enforce depth and constraints ===
        spec = boost_spec_depth(spec)
        spec = enforce_constraints(spec, clarifications_raw)

        # === Define agent & tester roles ===
        spec["_agent_role_prefix"] = {
            "generator": (
                "You are the **world’s most elite coding agent**. "
                "Deliver FINAL, PRODUCTION-READY code in one pass. "
                "Follow the spec exactly, resolve every requirement, "
                "and guarantee compatibility with all other files."
            ),
            "tester": (
                "You are a **file-specific practical reviewer**. "
                "You ONLY review the file given to you — not others.\n\n"
                "Rules:\n"
                "1. Approve ONLY if the file is flawless and production-ready.\n"
                "2. If issues exist, list **ALL problems in this file at once**, with exact corrections.\n"
                "   Example:\n"
                "   ❌ Issues in `user_service.py`:\n"
                "   - Missing import: add `from typing import List`.\n"
                "   - Function `get_user` missing return type annotation.\n"
                "   - Variable `db` is used but never defined.\n"
                "3. Never stop at the first error — always surface *every* issue.\n"
                "4. If no issues: output ONLY ✅ APPROVED."
            )
        }

        # === Save state ===
        project_state[project] = spec
        save_state(project_state)
        return spec

    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

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
            spec = generate_spec(session["project"], session["clarifications"])
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
