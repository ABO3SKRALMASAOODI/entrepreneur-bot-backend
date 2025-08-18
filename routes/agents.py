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
# ===== Robust JSON Extractor =====
def _extract_json_strict(text: str):
    """
    Extract valid JSON (object or array) from LLM output.
    Includes auto-repair for common mistakes instead of failing silently.
    """
    if not text:
        return None

    s = text.strip()

    # Strip Markdown fences
    if s.startswith("```"):
        parts = s.split("\n", 1)
        s = parts[1] if len(parts) > 1 else ""
    if s.endswith("```"):
        s = s[:-3].rstrip()

    # Direct attempt
    try:
        return json.loads(s)
    except Exception:
        pass

    # Slice between first { or [ and last } or ]
    start_braces = min([i for i in [s.find("{"), s.find("[")] if i != -1], default=-1)
    end_braces = max([s.rfind("}"), s.rfind("]")])
    if start_braces != -1 and end_braces != -1:
        candidate = s[start_braces:end_braces + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # Repair common issues: trailing commas, single quotes
    repaired = re.sub(r",\s*([\]}])", r"\1", s)
    repaired = repaired.replace("'", "\"")
    try:
        return json.loads(repaired)
    except Exception as e:
        print(f"❌ JSON extraction failed.\nRaw:\n{text}\nError: {e}")
        return None


# ===== Orchestrator Stage Runner =====
def run_orchestrator(stage: str, input_data: dict) -> dict:
    """
    Run a single orchestrator stage with strict JSON enforcement and safe fallbacks.
    Returns a dict with either valid spec OR an error structure.
    """
    system_msg = ORCHESTRATOR_STAGES[stage]
    raw = None

    try:
        # First attempt
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": json.dumps(input_data, indent=2)}
            ]
        )
        raw = resp["choices"][0]["message"]["content"]
        spec = _extract_json_strict(raw)

        # Retry if invalid JSON
        attempt = 0
        while not spec and attempt < 2:
            attempt += 1
            retry_msg = "⚠️ Your last output was invalid JSON. Return the SAME specification again as STRICT JSON only."
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": retry_msg}
                ]
            )
            raw = resp["choices"][0]["message"]["content"]
            spec = _extract_json_strict(raw)

        if not spec:
            return {
                "error": True,
                "stage": stage,
                "detail": f"Stage {stage} failed to produce valid JSON",
                "raw_output": raw
            }

        return {"error": False, "spec": spec}

    except Exception as e:
        return {
            "error": True,
            "stage": stage,
            "detail": str(e),
            "raw_output": raw
        }


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
STRICT_JSON_RULES = """
⚠️ RULES – You are a structured specification engine.
- You MUST output VALID JSON ONLY.
- DO NOT add explanations, notes, comments, Markdown, or prose.
- DO NOT include code fences (```).
- Output MUST parse with Python's json.loads() without modification.
- The top-level output MUST exactly match the required schema.
- If unsure, make reasonable assumptions but always return syntactically valid JSON.
"""

ORCHESTRATOR_STAGES = {
    "describer": f"""
You are Orchestrator 0 (Project Describer).
Your job: restate the project clearly, define the user story, target users, and suggest a tech stack.
Expected JSON keys: project_summary, user_story, suggested_stack.
{STRICT_JSON_RULES}
""",

    "scoper": f"""
You are Orchestrator 1 (Scoper).
Input: project description.
Output: STRICT JSON array of files.
Each file object MUST contain: file, category, description.
No prose or explanations outside the JSON array.
{STRICT_JSON_RULES}
""",

    "contractor": f"""
You are Orchestrator 2 (Contractor).
Input: project + files.
Output: JSON object with key "contracts".
Inside "contracts": entities, apis, functions, protocols, errors.
Each item MUST include types, examples, and conditions.
{STRICT_JSON_RULES}
""",

    "architect": f"""
You are Orchestrator 3 (Architect).
Input: project + files + contracts.
Output: JSON object with keys:
- file_contract_map (assign contracts to files)
- agent_blueprint
- dependency_graph
- execution_plan
- global_reference_index
{STRICT_JSON_RULES}
""",

    "booster": f"""
You are Orchestrator 4 (Detail Booster).
Input: enriched spec.
Output: the SAME spec with an added "__depth_boost" key.
For each file, add production-grade notes (SOLID, logging, testing, etc.).
{STRICT_JSON_RULES}
""",

    "verifier": f"""
You are Orchestrator 5 (Verifier).
Input: boosted spec.
Output: FINAL VERIFIED JSON object.
You MUST check and enforce:
- Every API has a backend file.
- Every file has an agent in agent_blueprint.
- Every function has a test case.
- Every error maps to an http_status.
Return ONLY the final JSON spec, nothing else.
{STRICT_JSON_RULES}
"""
}


# ===== Spec Template =====
SPEC_TEMPLATE = """ Project: {project}
Preferences/Requirements: {clarifications}
Produce STRICT JSON with every section fully populated.

{ "version": "12.0",
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
    Ensures universal constraints:
    - Clarifications merged into description.
    - Required universal files always exist.
    - Agent blueprint populated for all files.
    - Global reference index always populated.
    """
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

# ===== Spec Generator =====

# ===== Orchestrator Pipeline =====
def orchestrator_pipeline(project: str, clarifications: str) -> dict:
    results = {}

    # Stage 0 - Describer
    desc = run_orchestrator("describer", {"project": project, "clarifications": clarifications})
    results["describer"] = desc
    if desc.get("error"):
        return {"status": "failed", "stage": "describer", "detail": desc["detail"], "raw": desc.get("raw_output")}

    # Stage 1 - Scoper
    files = run_orchestrator("scoper", desc["spec"])
    results["scoper"] = files
    if files.get("error"):
        return {"status": "failed", "stage": "scoper", "detail": files["detail"], "raw": files.get("raw_output")}

    # Normalize files into dict for contractor
    files_dict = {"files": files["spec"]} if isinstance(files["spec"], list) else files["spec"]

    # Stage 2 - Contractor
    contractor_input = {**desc["spec"], **files_dict}
    contracts = run_orchestrator("contractor", contractor_input)
    results["contractor"] = contracts
    if contracts.get("error"):
        return {"status": "failed", "stage": "contractor", "detail": contracts["detail"], "raw": contracts.get("raw_output")}

    # Stage 3 - Architect
    arch_input = {**desc["spec"], **files_dict, **contracts["spec"]}
    arch = run_orchestrator("architect", arch_input)
    results["architect"] = arch
    if arch.get("error"):
        return {"status": "failed", "stage": "architect", "detail": arch["detail"], "raw": arch.get("raw_output")}

    # Stage 4 - Booster
    boosted = run_orchestrator("booster", arch["spec"])
    results["booster"] = boosted
    if boosted.get("error"):
        return {"status": "failed", "stage": "booster", "detail": boosted["detail"], "raw": boosted.get("raw_output")}

    # Stage 5 - Verifier
    final_spec = run_orchestrator("verifier", boosted["spec"])
    results["verifier"] = final_spec
    if final_spec.get("error"):
        return {"status": "failed", "stage": "verifier", "detail": final_spec["detail"], "raw": final_spec.get("raw_output")}

    # Save verified spec
    project_state[project] = final_spec["spec"]
    save_state(project_state)

    return {
        "status": "success",
        "stages": results,
        "final_spec": final_spec["spec"]
    }


# ===== Orchestrator Route =====
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

    # Initialize session if needed
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "stage": "project",
            "project": "",
            "clarifications": ""
        }

    session = user_sessions[user_id]

    # Stage 1: Ask for project if missing
    if session["stage"] == "project":
        if not project:
            return jsonify({
                "role": "assistant",
                "content": "What is your project idea?"
            })
        session["project"] = project
        session["stage"] = "clarifications"
        return jsonify({
            "role": "assistant",
            "content": "Do you have any preferences, requirements, or constraints? (Optional)"
        })

    # Stage 2: Clarifications provided → run orchestrator pipeline
    if session["stage"] == "clarifications":
        incoming_constraints = clarifications or project
        if incoming_constraints.strip():
            session["clarifications"] = incoming_constraints.strip()
            session["stage"] = "done"

        # Run full orchestrator pipeline
        stage_outputs = orchestrator_pipeline(
            session["project"],
            session["clarifications"]
        )

        # If pipeline failed, return structured error (no 500s)
        if stage_outputs.get("status") == "failed":
            return jsonify({
                "role": "assistant",
                "status": "FAILED",
                "stage": stage_outputs["stage"],
                "detail": stage_outputs["detail"],
                "raw_output": stage_outputs.get("raw")
            }), 400

        # Otherwise, use the final spec
        final_spec = stage_outputs.get("final_spec", {})

        # Run generator + tester agents on the final spec
        agent_outputs = run_agents_for_spec(final_spec)

        return jsonify({
            "role": "assistant",
            "status": "FULLY VERIFIED",
            "stages": stage_outputs["stages"],   # all intermediate orchestrator outputs
            "final_spec": final_spec,            # explicitly the verified spec
            "agents_output": agent_outputs
        })

    # Reset session if flow breaks
    user_sessions[user_id] = {
        "stage": "project",
        "project": "",
        "clarifications": ""
    }
    return jsonify({
        "role": "assistant",
        "content": "What is your project idea?"
    })
