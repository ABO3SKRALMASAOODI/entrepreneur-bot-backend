from flask import Blueprint, request, jsonify
import os, json, re
import openai
from datetime import datetime

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
    "Your job is to output a FINAL, COMPLETE, ZERO-AMBIGUITY spec so multiple independent agents "
    "can code different files and produce 100% compatible, working software. "
    "--- RULES ---\n"
    "1. Detect project_type from description.\n"
    "2. Include: global_naming_contract, data_dictionary, shared_schemas (code), "
    "interface_stub_files (full code), agent_blueprint, api_contracts, db_schema, domain_specific, "
    "inter_agent_protocols, dependency_graph, execution_plan, integration_tests (code), test_cases.\n"
    "3. interface_stub_files must have exact imports, type hints, and docstrings.\n"
    "4. shared_schemas must define all shared types as Python dataclasses or language-appropriate equivalents.\n"
    "5. integration_tests must validate that agent outputs match inter-agent protocol schemas.\n"
    "6. All naming must match exactly across all modules.\n"
    "7. Output STRICT JSON ONLY."
)

# ===== Spec Template =====
SPEC_TEMPLATE = """
Project: {project}
Preferences/Requirements: {clarifications}

Produce STRICT JSON:
{{
  "version": "7.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<detailed summary>",
  "project_type": "<auto-detected>",
  "target_users": [],
  "tech_stack": {{}},
  "global_naming_contract": {{}},
  "data_dictionary": [],
  "shared_schemas": "code for shared_schemas.py",
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
    {{"path": "", "code": ""}}
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
            "content": "Do you have any preferences, requirements, or constraints for the implementation?"
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

    # Stage 3: Done — auto-reset for new project
    if session["stage"] == "done":
        user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}
        return jsonify({"role": "assistant", "content": "What is your project idea?"})
