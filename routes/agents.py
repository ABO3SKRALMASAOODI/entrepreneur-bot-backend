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
    Returns None if no valid JSON found.
    """
    if not text:
        return None

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None

    candidate = text[start:end+1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Try to clean trailing commas or bad escapes
        cleaned = re.sub(r",\s*}", "}", candidate)
        cleaned = re.sub(r",\s*]", "]", cleaned)
        try:
            return json.loads(cleaned)
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
    "can implement their files in isolation and when combined, the system runs flawlessly.\n"
    "--- UNIVERSAL COMPATIBILITY RULES ---\n"
    "1. First define the CONTRACTS: entities, APIs, functions, protocols, and error codes.\n"
    "2. Every contract must have: exact input/output types, example I/O, pre/postconditions.\n"
    "3. Then define FILES: each file specifies which contracts it implements (not free choice).\n"
    "4. Agents must implement ONLY their assigned contracts, exactly as defined.\n"
    "5. Every function has explicit pseudocode steps.\n"
    "6. Every data structure has exact field names, types, nullability, defaults.\n"
    "7. Errors must map to Error Decision Table with codes → conditions → status.\n"
    "8. Inter-agent protocols must have full step-by-step flows with success/failure handling.\n"
    "9. Dependency graph must list all imports, avoid circulars.\n"
    "10. Integration tests must verify contracts, protocols, and end-to-end execution.\n"
    "11. Output must be STRICT JSON, no comments or markdown.\n"
    "12. Scale: always break into smallest coherent files so 100–200 agents can work in parallel.\n"
    "13. Use strict naming conventions: snake_case (functions), PascalCase (classes), UPPER_SNAKE_CASE (constants).\n"
    "14. Never leave sections empty: populate everything fully.\n"
    "15. Include Global Reference Index for all files, functions, classes, agents.\n"
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
    """
    Enforces universal orchestrator constraints:
    - Merge clarifications into description.
    - Ensure universal files exist.
    - Populate agent_blueprint and global_reference_index.
    - Validate contract structure.
    """
    # --- Merge clarifications ---
    if clarifications.strip():
        spec.setdefault("domain_specific", {})
        spec["domain_specific"]["user_constraints"] = clarifications
    if clarifications not in spec.get("description", ""):
        spec["description"] = f"{spec.get('description', '')} | User constraints: {clarifications}"

    # --- Required universal files ---
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

    # --- Validate contracts ---
    if "contracts" not in spec:
        raise ValueError("Spec missing 'contracts' section")

    for section in ["entities", "apis", "functions", "protocols", "errors"]:
        spec["contracts"].setdefault(section, [])

    # --- Update agent blueprint ---
    spec["agent_blueprint"] = []
    for f in spec.get("files", []):
        base = f["file"].rsplit(".", 1)[0]
        agent_name = "".join(word.capitalize() for word in base.split("_")) + "Agent"
        spec["agent_blueprint"].append({
            "name": agent_name,
            "description": f"Responsible for implementing {f['file']} exactly as specified in the contracts."
        })

    # --- Update global reference index ---
    spec.setdefault("global_reference_index", [])
    seen = {e["file"] for e in spec["global_reference_index"] if "file" in e}
    for f in spec.get("files", []):
        if f["file"] not in seen:
            spec["global_reference_index"].append({
                "file": f["file"],
                "functions": [],
                "classes": [],
                "agents": []
            })

    return spec


# ===== Depth Booster =====
def boost_spec_depth(spec: dict) -> dict:
    """
    Adds deep implementation guidance for every file in spec.
    Prevents ambiguity, ensures agents produce production-ready,
    compatible, world-class code.
    """
    if "__depth_boost" not in spec:
        spec["__depth_boost"] = {}

    # Collect file names
    all_files = {f["file"] for f in spec.get("files", []) if "file" in f}

    for file_name in all_files:
        spec["__depth_boost"].setdefault(file_name, {})

        # Attach universal engineering notes
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

        # Link back to contracts for clarity
        contracts = spec.get("contracts", {})
        spec["__depth_boost"][file_name]["contracts"] = {
            "entities": contracts.get("entities", []),
            "apis": contracts.get("apis", []),
            "functions": contracts.get("functions", []),
            "protocols": contracts.get("protocols", []),
            "errors": contracts.get("errors", []),
        }

    return spec


# ===== Spec Generator =====
def run_agents_for_spec(spec: dict) -> dict:
    """
    Orchestrator → Agents → Tester → Fixer pipeline with restructuring fallback.
    Generates all required files for a project specification.
    Ensures final code passes tester approval, imports, and integration tests.
    """

    final_outputs = {}
    failures = {}

    candidate_files = get_agent_files(spec)

    for file_name in candidate_files:
        file_spec = extract_file_spec(spec, file_name)
        print(f"[Pipeline] Starting generation for: {file_name}")

        generated_code = None
        success = False
        attempts = 0
        review_feedback = ""

        while attempts < MAX_RETRIES and not success:
            attempts += 1
            print(f"[Pipeline] Attempt {attempts} for {file_name}")

            # --- Generation Phase ---
            if attempts == 1:
                generated_code = run_generator_agent(file_name, file_spec, spec)
            else:
                if attempts >= 3 and review_feedback:
                    print(f"[Pipeline] Escalating {file_name} to restructuring agent")
                    generated_code = run_restructuring_agent(
                        file_name, file_spec, spec, generated_code, review_feedback
                    )
                else:
                    generated_code = run_fixer_agent(
                        file_name, file_spec, spec, generated_code, review_feedback
                    )

            if not generated_code:
                review_feedback = "❌ No code generated"
                break

            # --- Tester Phase ---
            review_feedback = run_tester_agent(file_name, file_spec, spec, generated_code)
            print(f"[Tester Feedback] {file_name}: {review_feedback}")

            if (
                not review_feedback
                or "approved" in review_feedback.lower()
                or "✅" in review_feedback
            ):
                success = True
                final_outputs[file_name] = {"file": file_name, "code": generated_code}
                print(f"[Pipeline] {file_name} approved on attempt {attempts}")
                break

            if is_hard_failure(review_feedback):
                print(f"[Pipeline] Hard failure detected for {file_name}")
                break

        if not success:
            failures[file_name] = {
                "attempts": attempts,
                "last_feedback": review_feedback,
                "last_code": generated_code,
            }
            print(f"[Pipeline] Failed to approve {file_name} after {attempts} attempts")

    # === Final verification step ===
    if final_outputs:
        try:
            outputs_as_dicts = list(final_outputs.values())
            verify_imports(outputs_as_dicts)
            verify_tests(outputs_as_dicts, spec)
        except Exception as e:
            return {
                "status": "tests_failed",
                "approved_files": final_outputs,
                "failed_files": failures,
                "message": f"Verification failed: {e}",
            }

    # === Response ===
    if failures:
        return {
            "status": "partial_failure",
            "approved_files": final_outputs,
            "failed_files": failures,
            "message": "Some files could not be approved even after retries",
        }
    else:
        return {
            "status": "success",
            "approved_files": final_outputs,
            "message": "All files successfully generated, tested, and approved",
        }


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