# routes/agents.py
from flask import Blueprint, request, jsonify
import os, json, re
import openai

agents_bp = Blueprint('agents', __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# In-memory session store — swap for Redis or DB in prod
user_sessions = {}

# ===== Helper: safer JSON extraction =====
def _extract_json_safe(text: str):
    """Safely extract JSON object/array from LLM output."""
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

# ===== System prompt for any project =====
SPEC_SYSTEM = (
    "You are a senior software architect and lead AI orchestrator. "
    "Your job is to turn vague user ideas into a complete multi-agent spec for *any type of software project*, "
    "not just websites. You must ensure all generated tasks are 100% compatible."
    "\nRules:"
    "\n- Output STRICT JSON only. No prose, no markdown."
    "\n- All file paths in tasks MUST exist in file_tree."
    "\n- Each task must have: id, file, role, agent, instructions, depends_on."
    "\n- If project is huge, split into logically independent modules."
    "\n- Ensure consistent naming across all places (e.g., API names, files, imports)."
    "\n- Prefer modular, maintainable structure."
)

# ===== Universal JSON template =====
SPEC_USER_TEMPLATE = """
Project request:
{project}

Constraints & requirements:
{constraints}

Produce STRICT JSON with EXACT shape:
{{
  "version": "1.0",
  "project": "<short descriptive name>",
  "project_type": "<web_app|cli_tool|backend_api|ml_system|automation|game|desktop_app|other>",
  "tech_stack": {{
    "frontend": {{"framework": "<string>", "version": "<semver or latest>"}},
    "backend": {{"framework": "<string>", "version": "<semver or latest>"}},
    "languages": ["<e.g., Python 3.11>", "<JavaScript ES2022>"],
    "databases": ["<if any>"],
    "tools": ["<build tools, libs, deps>"]
  }},
  "file_tree": [
    {{"path": "src/main.py", "purpose": "Main entrypoint"}},
    {{"path": "tests/test_main.py", "purpose": "Basic tests"}},
    ...
  ],
  "api_contracts": [
    {{
      "name": "createUser",
      "method": "POST",
      "path": "/api/users",
      "request": {{"body": {{"username":"string", "password":"string"}}}},
      "response": {{"200": {{"ok": true}}, "400": {{"error": "string"}}}}
    }}
  ],
  "data_models": [
    {{"name": "User", "fields": [
      {{"name": "id", "type": "uuid", "required": true}},
      {{"name": "username", "type": "string", "required": true}}
    ]}}
  ],
  "modules": [
    {{"name": "auth", "description": "Handles authentication and authorization"}},
    {{"name": "payments", "description": "Manages payment processing"}}
  ],
  "coding_guidelines": {{
    "style": "Follow language-specific style guides (e.g., PEP8, ESLint)",
    "testing": "Write tests for all public functions",
    "error_handling": "Gracefully handle and log errors"
  }},
  "acceptance_criteria": [
    "All modules work together without integration errors",
    "Passes all tests",
    "Meets all listed constraints"
  ],
  "tasks": [
    {{
      "id": "t1",
      "file": "src/main.py",
      "role": "Backend Developer",
      "agent": "backend",
      "instructions": "Implement entrypoint and module loader",
      "depends_on": []
    }}
  ]
}}
"""
def generate_spec(project: str, constraints: dict):
    """
    Generates a complete multi-agent project specification for ANY type of software.
    Automatically merges defaults and handles huge outputs.
    """
    default_constraints = {
        "backend_runtime": "python-flask",
        "frontend_runtime": "vanilla",
        "package_manager": "pip",
        "hosting": "static+flask-api",
        "min_quality": "production-grade",
        "forbid": [],
        "required_modules": [],
        "required_integrations": []
    }
    merged = {**default_constraints, **(constraints or {})}

    # Replace placeholders instead of .format() to avoid KeyError from JSON braces
    user_prompt = SPEC_USER_TEMPLATE \
        .replace("{project}", project) \
        .replace("{constraints}", json.dumps(merged, indent=2))

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": user_prompt}
            ],
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

    raw = resp.choices[0].message["content"]
    spec = _extract_json_safe(raw)

    if not spec:
        raise ValueError("❌ Failed to parse JSON spec from AI output")

    # Ensure required keys
    for key in ["project", "tech_stack", "file_tree", "tasks"]:
        if key not in spec:
            raise ValueError(f"❌ Missing key in spec: {key}")

    # Ensure file references are valid
    file_paths = {f.get("path") for f in spec.get("file_tree", []) if f.get("path")}
    bad_tasks = [t for t in spec.get("tasks", []) if t.get("file") not in file_paths]
    if bad_tasks:
        print(f"⚠️ Removing tasks with invalid file references: {bad_tasks[:3]}")
        spec["tasks"] = [t for t in spec.get("tasks", []) if t.get("file") in file_paths]

    # Chunk handling for very large specs
    max_chunk_size = 15000  # characters
    spec_str = json.dumps(spec, indent=2)
    if len(spec_str) > max_chunk_size:
        print(f"⚠️ Large spec detected ({len(spec_str)} chars) — splitting into chunks")
        spec["__chunks__"] = []
        current_chunk = ""
        for line in spec_str.splitlines():
            if len(current_chunk) + len(line) + 1 > max_chunk_size:
                spec["__chunks__"].append(current_chunk)
                current_chunk = ""
            current_chunk += line + "\n"
        if current_chunk:
            spec["__chunks__"].append(current_chunk)

    return spec
@agents_bp.route('/orchestrator', methods=['POST', 'OPTIONS'])
def orchestrator():
    """
    Multi-turn orchestrator that gathers ALL required details before generating the spec.
    Handles any type of software project.
    """
    if request.method == 'OPTIONS':
        return ('', 200)

    body = request.get_json(force=True) or {}
    user_id = body.get("user_id", "default")
    user_input = (body.get("project") or "").strip()
    constraints = body.get("constraints", {})

    session = user_sessions.get(user_id, {"project": "", "constraints": {}})

    # Step 1: Project name/description
    if not session["project"]:
        if len(user_input.split()) < 3:
            return jsonify({
                "role": "assistant",
                "content": "Tell me more — what kind of software do you want to build? (e.g. website, mobile app, AI tool, game, automation)"
            })
        session["project"] = user_input
        user_sessions[user_id] = session
        return jsonify({"role": "assistant", "content": "What is the main purpose or goal of this project?"})

    # Step 2: Main purpose
    if "purpose" not in session["constraints"] and "purpose" not in constraints:
        if user_input:
            session["constraints"]["purpose"] = user_input
            user_sessions[user_id] = session
            return jsonify({"role": "assistant", "content": "What platforms should it run on? (e.g. web, mobile, desktop, CLI, IoT)"})
        else:
            return jsonify({"role": "assistant", "content": "Please describe the main purpose of the project."})

    # Step 3: Platforms
    if "platforms" not in session["constraints"] and "platforms" not in constraints:
        if user_input:
            session["constraints"]["platforms"] = [p.strip() for p in user_input.split(",")]
            user_sessions[user_id] = session
            return jsonify({"role": "assistant", "content": "What main features or modules should it have?"})
        else:
            return jsonify({"role": "assistant", "content": "List the platforms it should run on."})

    # Step 4: Features
    if "features" not in session["constraints"] and "features" not in constraints:
        if user_input:
            session["constraints"]["features"] = [f.strip() for f in user_input.split(",")]
            user_sessions[user_id] = session
            return jsonify({"role": "assistant", "content": "Any preferred tech stack? (e.g. Python+Flask, Node.js+React, Unity, TensorFlow)"})
        else:
            return jsonify({"role": "assistant", "content": "List the main features or modules."})

    # Step 5: Tech stack
    if "tech_stack" not in session["constraints"] and "tech_stack" not in constraints:
        if user_input:
            session["constraints"]["tech_stack"] = user_input
            user_sessions[user_id] = session
            return jsonify({"role": "assistant", "content": "Any special integrations or APIs required? (e.g. payment gateways, OpenAI, AWS)"})
        else:
            return jsonify({"role": "assistant", "content": "Specify the preferred tech stack or say 'no preference'."})

    # Step 6: Integrations
    if "integrations" not in session["constraints"] and "integrations" not in constraints:
        if user_input:
            session["constraints"]["integrations"] = [i.strip() for i in user_input.split(",")]
            user_sessions[user_id] = session
            return jsonify({"role": "assistant", "content": "Any performance or scalability requirements? (e.g. handle 10k concurrent users)"})
        else:
            return jsonify({"role": "assistant", "content": "List any special integrations or say 'none'."})

    # Step 7: Performance
    if "performance" not in session["constraints"] and "performance" not in constraints:
        if user_input:
            session["constraints"]["performance"] = user_input
            user_sessions[user_id] = session
            return jsonify({"role": "assistant", "content": "What’s your target timeline for the MVP?"})
        else:
            return jsonify({"role": "assistant", "content": "Specify performance/scalability needs or say 'standard'."})

    # Step 8: Timeline
    if "timeline" not in session["constraints"] and "timeline" not in constraints:
        if user_input:
            session["constraints"]["timeline"] = user_input
            user_sessions[user_id] = session
        else:
            return jsonify({"role": "assistant", "content": "What’s your target timeline for MVP?"})

    # Merge constraints
    session["constraints"].update(constraints)
    user_sessions[user_id] = session

    REQUIRED_KEYS = ["purpose", "platforms", "features", "tech_stack", "integrations", "performance", "timeline"]

    # If all required info is collected, generate spec
    if all(k in session["constraints"] for k in REQUIRED_KEYS):
        try:
            spec = generate_spec(session["project"], session["constraints"])
            lines = [f"**Project:** {spec.get('project','')}", "\n**Tasks:**"]
            for i, t in enumerate(spec.get("tasks", []), 1):
                lines.append(f"{i}. **{t.get('file')}** — _{t.get('role')}_")
            return jsonify({"role": "assistant", "content": "\n".join(lines), "spec": spec})
        except Exception as e:
            return jsonify({"role": "assistant", "content": f"❌ Spec generation failed: {e}"})

    return jsonify({"role": "assistant", "content": "I still need more details before generating your project spec."})
