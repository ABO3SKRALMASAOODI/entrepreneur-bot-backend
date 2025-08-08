# routes/agents.py
from flask import Blueprint, request, jsonify
import os, json, re
import openai

agents_bp = Blueprint('agents', __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

def _extract_json(text: str):
    if not text:
        return None
    s = text.strip()
    # strip code fences
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.MULTILINE).strip()
    # try parse full
    try:
        return json.loads(s)
    except Exception:
        pass
    # fallback: search first JSON object/array
    start = min([p for p in [s.find("{"), s.find("[")] if p != -1] or [-1])
    if start == -1:
        return None
    for end in range(len(s), start, -1):
        try:
            return json.loads(s[start:end])
        except Exception:
            continue
    return None

SPEC_SYSTEM = (
    "You are a senior software architect and build coordinator. "
    "Output STRICT JSON only. No prose, no markdown."
)

SPEC_USER_TEMPLATE = """
Project request:
{project}

Constraints:
{constraints}

Produce JSON with shape:
{{
  "version": "1.0",
  "project": "<short>",
  "tech_stack": {{
    "frontend": {{ "framework": "<str>", "version": "<semver>" }},
    "backend":  {{ "framework": "<str>", "version": "<semver>" }},
    "language_standards": ["<rule>", "<rule>"]
  }},
  "file_tree": [ {{ "path": "<string>", "purpose": "<string>" }} ],
  "api_contracts": [ {{
    "name": "<string>",
    "method": "GET|POST|PUT|DELETE",
    "path": "<string>",
    "request": {{ "query": {{}}, "body": {{}} }},
    "response": {{ "200": {{}}, "4xx": {{}}, "5xx": {{}} }}
  }} ],
  "data_models": [ {{
    "name": "<string>",
    "fields": [{{ "name":"<string>", "type":"<string>", "required": true }}]
  }} ],
  "coding_guidelines": {{
    "naming": ["<rules>"],
    "state_management": "<rule>",
    "error_handling": "<rule>",
    "imports": "<rule>"
  }},
  "tasks": [ {{
    "id": "t1",
    "file": "<exact path from file_tree>",
    "role": "Frontend Developer|Backend Developer|Content Writer|Docs",
    "agent": "frontend|backend|docs",
    "instructions": "<precise steps>",
    "depends_on": []
  }} ]
}}

Rules:
- Respect constraints strictly (e.g. if backend_runtime=python-flask, do NOT create server.js).
- Every task.file MUST exist in file_tree.
- Use stable IDs t1..tN and depends_on when order matters.
- JSON ONLY. No markdown fences.
"""

def generate_spec(project: str, constraints: dict):
    """Calls OpenAI to produce a project spec JSON dict (or raises)."""
    default_constraints = {
        "backend_runtime": "python-flask",
        "frontend_runtime": "vanilla",
        "package_manager": "pip",
        "hosting": "static+flask-api",
        "forbid": ["node", "express", "server.js"]
    }
    merged = {**default_constraints, **(constraints or {})}

    user_prompt = SPEC_USER_TEMPLATE.format(
        project=project,
        constraints=json.dumps(merged, indent=2)
    )

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
        raise ValueError("Spec generation failed")

    # minimal validation
    file_paths = {f.get("path") for f in spec.get("file_tree", []) if f.get("path")}
    bad = [t for t in spec.get("tasks", []) if t.get("file") not in file_paths]
    if bad:
        raise ValueError(f"Tasks reference unknown files: {bad[:3]}")

    return spec

@agents_bp.route('/start', methods=['POST', 'OPTIONS'])
def start_project():
    if request.method == 'OPTIONS':
        return ('', 200)
    body = request.get_json(force=True) or {}
    project = (body.get("project") or "").strip()
    constraints = body.get("constraints", {})
    if not project:
        return jsonify({"error": "No project description provided"}), 400
    try:
        spec = generate_spec(project, constraints)
        return jsonify({"project_id": None, "spec": spec})
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@agents_bp.route('/orchestrator', methods=['POST', 'OPTIONS'])
def orchestrator():
    if request.method == 'OPTIONS':
        return ('', 200)
    body = request.get_json(force=True) or {}
    project = (body.get("project") or "").strip()
    constraints = body.get("constraints", {})
    if not project:
        return jsonify({"error": "No project description provided"}), 400
    try:
        spec = generate_spec(project, constraints)
        # human-readable summary for chat + structured spec
        lines = [f"**Project:** {spec.get('project','')}", "\n**Tasks:**"]
        for i, t in enumerate(spec.get("tasks", []), 1):
            lines.append(f"{i}. **{t.get('file')}** — _{t.get('role')}_")
        human = "\n".join(lines)
        return jsonify({"role": "assistant", "content": human, "spec": spec})
    except Exception as e:
        return jsonify({"error": str(e)}), 502
