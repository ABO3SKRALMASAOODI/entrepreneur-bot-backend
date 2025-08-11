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
    "You must produce a FINAL, COMPLETE, ZERO-AMBIGUITY multi-agent project specification "
    "for ANY type of project (not just websites). Agents will NOT make creative or technical choices — every "
    "single detail must be here.\n"
    "--- RULES ---\n"
    "1. Detect project type from user request. Supported types include:\n"
    "   web_app, mobile_app, cli_tool, api_service, desktop_app, ai_ml_model, blockchain_project, "
    "   iot_embedded, game, data_pipeline, hybrid.\n"
    "2. Adapt spec fields to the project type:\n"
    "   - Blockchain: consensus, chain config, smart contracts, deployment scripts.\n"
    "   - AI/ML: model architecture, dataset schema, preprocessing, hyperparameters.\n"
    "   - CLI: command list, args schema, stdout/stderr formats.\n"
    "   - Game: engine, assets, physics params, level schema.\n"
    "3. Define ALL technical choices: languages, frameworks, architecture, versions, dependencies, file tree.\n"
    "4. Output STRICT JSON ONLY — no prose, no markdown.\n"
    "5. Must include:\n"
    "   - global_naming_contract: variables, constants, functions, classes, APIs, commands\n"
    "   - data_dictionary: all fields/objects with type, format, constraints\n"
    "   - function_contracts: full signatures, param types, constraints, returns, pre/postconditions, errors, examples\n"
    "   - agent_blueprint: for EACH agent — responsibilities, coding rules, assigned files, functions to implement, "
    "                      inter-agent communication format, error handling rules, unit/integration tests\n"
    "   - api_contracts: endpoints, methods, request/response schema, error cases\n"
    "   - db_schema: all tables, columns, types, constraints, indexes\n"
    "   - domain_specific: fields for blockchain/AI/game/etc.\n"
    "   - inter_agent_protocols: who calls what, with exact JSON schema\n"
    "   - dependency_graph: task dependencies\n"
    "   - execution_plan: ordered steps for agents to build the project\n"
    "   - test_cases: for every public function/module\n"
    "6. All naming must match exactly across all modules.\n"
    "7. If referenced anywhere, it MUST be defined.\n"
    "8. Split into JSON chunks if large, but keep valid JSON."
)

# ===== Spec Template =====
SPEC_TEMPLATE = """
Project: {project}
Design Preferences: {design}

Produce STRICT JSON:
{{
  "version": "6.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<detailed summary>",
  "project_type": "<auto-detected>",
  "target_users": [],
  "design_preferences": {{
    "style": "{design}",
    "colors": [],
    "layout": "",
    "tone": "",
    "branding": "",
    "accessibility": ""
  }},
  "tech_stack": {{}},
  "global_naming_contract": {{}},
  "data_dictionary": [],
  "function_contracts": [],
  "api_contracts": [],
  "db_schema": [],
  "domain_specific": {{
    "ai_ml_model": {{"model_architecture": {{}}, "dataset": {{}}, "training_pipeline": {{}}, "evaluation_metrics": []}},
    "blockchain_project": {{"consensus": "", "chain_config": {{}}, "smart_contracts": [], "deployment_scripts": []}},
    "cli_tool": {{"commands": [], "args_schema": {{}}, "output_formats": {}}}, 
    "game": {{"engine": "", "assets": [], "levels": [], "physics": {}}}, 
    "iot_embedded": {{"hardware": {{}}, "firmware_modules": [], "communication_protocols": []}}
  }},
  "agent_blueprint": [],
  "inter_agent_protocols": [],
  "dependency_graph": [],
  "execution_plan": [],
  "file_tree": [],
  "test_cases": []
}}
"""

# ===== Spec Generator =====
def generate_spec(project: str, design: str):
    filled = SPEC_TEMPLATE.replace("{project}", project).replace("{design}", design).replace(
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
    design = body.get("design", "").strip()

    if user_id not in user_sessions:
        user_sessions[user_id] = {"stage": "project", "project": "", "design": ""}

    session = user_sessions[user_id]

    # Stage 1: Ask for project
    if session["stage"] == "project":
        if not project:
            return jsonify({"role": "assistant", "content": "What is your project idea?"})
        session["project"] = project
        session["stage"] = "design"
        return jsonify({"role": "assistant", "content": "Any preferences for style, colors, layout, branding, tone, or accessibility?"})

    # Stage 2: Ask for design and generate spec
    if session["stage"] == "design":
        session["design"] = design if design else "no preference"
        session["stage"] = "done"
        try:
            spec = generate_spec(session["project"], session["design"])
            return jsonify({"role": "assistant", "content": json.dumps(spec, indent=2)})
        except Exception as e:
            return jsonify({"role": "assistant", "content": f"❌ Failed to generate spec: {e}"})

    # Stage 3: Already done — reset or inform user
    if session["stage"] == "done":
        if project and project != session["project"]:
            # Reset for new project
            session["project"] = project
            session["design"] = ""
            session["stage"] = "design"
            return jsonify({"role": "assistant", "content": "Any preferences for style, colors, layout, branding, tone, or accessibility?"})
        else:
            return jsonify({"role": "assistant", "content": "You have already generated a plan. Please provide a new project idea to start over."})
