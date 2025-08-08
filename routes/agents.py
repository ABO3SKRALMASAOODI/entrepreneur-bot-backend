# routes/agents.py
from flask import Blueprint, request, jsonify
import os, json, re
import openai

agents_bp = Blueprint('agents', __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

def _extract_json(text: str):
    """Pull the first JSON object/array even if model wrapped it in fences."""
    if not text:
        return None
    # Remove code fences if present
    fenced = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    candidates = [text, fenced]
    for s in candidates:
        try:
            # Find first {...} or [...]
            start = s.find("{")
            alt_start = s.find("[") if start == -1 else -1
            if start == -1 and alt_start != -1:
                start = alt_start
            if start == -1:
                continue
            # naive end: try to load progressively
            for end in range(len(s), start, -1):
                chunk = s[start:end]
                try:
                    return json.loads(chunk)
                except Exception:
                    continue
        except Exception:
            pass
    return None

SPEC_SYSTEM = (
    "You are a senior software architect and build coordinator. "
    "You must output STRICT JSON only (no prose, no markdown). "
    "Your job: turn the user's request + constraints into a GLOBAL_SPEC all agents will follow."
)

SPEC_USER_TEMPLATE = """
Project request:
{project}

Constraints (hard requirements):
{constraints}

Produce JSON with this EXACT shape:
{{
  "version": "1.0",
  "project": "<short name>",
  "tech_stack": {{
    "frontend": {{ "framework": "<string>", "version": "<semver>" }},
    "backend":  {{ "framework": "<string>", "version": "<semver>" }},
    "language_standards": ["<e.g. ES2022>", "<PEP8>"]
  }},
  "file_tree": [
    {{ "path": "<string>", "purpose": "<string>" }}
  ],
  "api_contracts": [
    {{
      "name": "<string>",
      "method": "GET|POST|PUT|DELETE",
      "path": "<string>",
      "request": {{ "query": {{}}, "body": {{}} }},
      "response": {{ "200": {{}}, "4xx": {{}}, "5xx": {{}} }}
    }}
  ],
  "data_models": [
    {{
      "name": "<string>",
      "fields": [{{ "name":"<string>", "type":"<string>", "required": true }}]
    }}
  ],
  "coding_guidelines": {{
    "naming": ["<rules>"],
    "state_management": "<rule>",
    "error_handling": "<rule>",
    "imports": "<rule>"
  }},
  "tasks": [
    {{
      "id": "t1",
      "file": "<exact path from file_tree>",
      "role": "Frontend Developer|Backend Developer|Content Writer|Docs",
      "agent": "frontend|backend|docs",
      "instructions": "<precise steps>",
      "depends_on": []
    }}
  ]
}}
Rules:
- Respect constraints strictly (e.g., if backend_runtime=python-flask, do NOT create server.js).
- file paths in tasks MUST exist in file_tree.
- Use stable IDs (t1, t2, ...). Include depends_on when order matters.
- Keep API and model names consistent across tasks.
- NO markdown fences in output. JSON ONLY.
"""

@agents_bp.route('/start', methods=['POST', 'OPTIONS'])
def start_project():
    if request.method == 'OPTIONS':
        return ('', 200)
    body = request.get_json(force=True) or {}
    project = body.get("project", "").strip()
    constraints = body.get("constraints", {})

    if not project:
        return jsonify({"error": "No project description provided"}), 400

    # Default constraints to keep you on Flask/Python and avoid Node
    default_constraints = {
        "backend_runtime": "python-flask",
        "frontend_runtime": "vanilla",
        "package_manager": "pip",
        "hosting": "static+flask-api",
        "forbid": ["node", "express", "server.js"]
    }
    # Merge user constraints (override defaults)
    merged = {**default_constraints, **constraints}

    user_prompt = SPEC_USER_TEMPLATE.format(
        project=project,
        constraints=json.dumps(merged, indent=2)
    )

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": user_prompt}
            ],
        )
        raw = resp.choices[0].message["content"]
        spec = _extract_json(raw)

        if not spec or "tasks" not in spec or "file_tree" not in spec:
            return jsonify({"error": "Spec generation failed", "raw": raw}), 502

        # (Optional) minimal validation
        file_paths = {f["path"] for f in spec.get("file_tree", []) if "path" in f}
        bad = [t for t in spec["tasks"] if t.get("file") not in file_paths]
        if bad:
            return jsonify({"error": "Tasks reference unknown files", "bad_tasks": bad, "spec": spec}), 422

        # TODO: persist and return a project_id; for now return spec directly
        return jsonify({
            "project_id": None,
            "spec": spec
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Back-compat: keep your old endpoint but delegate to /start
@agents_bp.route('/orchestrator', methods=['POST', 'OPTIONS'])
def orchestrator():
    if request.method == 'OPTIONS':
        return ('', 200)
    # simply call start_project's logic to produce spec, but return chat-style payload
    with agents_bp.test_request_context():
        # reuse current request body
        result = start_project()
        if isinstance(result, tuple):
            payload, status = result
        else:
            payload, status = result, 200
        if status != 200:
            return result
        data = payload.get_json()
        spec = data.get("spec", {})
        # human-readable summary for chat bubble + structured spec for later
        summary_lines = [f"**Project:** {spec.get('project','')}", "\n**Tasks:**"]
        for i, t in enumerate(spec.get("tasks", []), 1):
            summary_lines.append(f"{i}. **{t.get('file')}** — _{t.get('role')}_")
        human = "\n".join(summary_lines)
        return jsonify({"role": "assistant", "content": human, "spec": spec})
