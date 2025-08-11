from flask import Blueprint, request, jsonify
import os, json, re
import openai
from datetime import datetime
import hashlib

agents_bp = Blueprint("agents", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

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

# ===== System Prompt =====
SPEC_SYSTEM = (
    "You are an elite senior software architect and AI project orchestrator. "
    "Your mission is to produce a FINAL, COMPLETE, ZERO-AMBIGUITY multi-agent specification "
    "that guarantees all generated code is 100% compatible, even across 100+ independent agents.\n"
    "--- CORE RULES ---\n"
    "1. Detect project_type from description (web_app, ai_ml_model, blockchain, mobile_app, cli_tool, game, data_pipeline, etc.).\n"
    "2. Use user preferences as hints, not hard locks — adapt them reasonably to the domain.\n"
    "3. Define ALL shared types in shared_schemas as strict dataclasses or equivalents.\n"
    "4. All interface_stub_files must import shared types — NO redefining types locally.\n"
    "5. Include import enforcement, round-trip tests, and contract hash lock tests in integration_tests.\n"
    "6. Output STRICT JSON ONLY — no prose, no markdown.\n"
    "--- REQUIRED FIELDS ---\n"
    "global_naming_contract, data_dictionary, shared_schemas, protocol_schemas, errors_module, "
    "interface_stub_files, agent_blueprint, api_contracts, db_schema, domain_specific, "
    "inter_agent_protocols, dependency_graph, execution_plan, integration_tests, test_cases."
)

# ===== Spec Template =====
SPEC_TEMPLATE = """
Project: {project}
Preferences/Requirements: {clarifications}

Produce STRICT JSON:
{{
  "version": "8.1",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<detailed summary>",
  "project_type": "<auto-detected>",
  "target_users": [],
  "tech_stack": {{}},
  "global_naming_contract": {{}},
  "data_dictionary": [],
  "shared_schemas": "code for shared_schemas.py",
  "protocol_schemas": "Pydantic/BaseModel schemas for inter-agent communication",
  "errors_module": "Custom exception classes",
  "interface_stub_files": [
    {{"path": "", "code": ""}}
  ],
  "agent_blueprint": [],
  "api_contracts": [],
  "db_schema": [],
  "domain_specific": {{}},
  "inter_agent_protocols": [],
  "dependency_graph": [],
  "execution_plan": [],
  "integration_tests": [
    {{
      "path": "test_import_enforcement.py",
      "code": "# Ensures all agents import shared types, no local redeclaration"
    }},
    {{
      "path": "test_round_trip_protocols.py",
      "code": "# Ensures output from one agent passes into another without transformation"
    }},
    {{
      "path": "test_contract_hash_lock.py",
      "code": "# Checks shared_schemas and stubs match original contract hash"
    }}
  ],
  "test_cases": []
}}
"""

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
