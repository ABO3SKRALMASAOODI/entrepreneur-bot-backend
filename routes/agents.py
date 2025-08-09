# routes/agents.py
from flask import Blueprint, request, jsonify
import os, json, re
import openai

agents_bp = Blueprint('agents', __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

def _extract_json_safe(text: str):
    """Safely extract JSON from AI output."""
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

SPEC_SYSTEM = (
    "You are a world-class Chief Software Architect & Multi-Agent Coordinator. "
    "Given ANY high-level user description, you will generate a COMPLETE, "
    "CONSISTENT, and EXECUTABLE build specification for multiple AI coding agents. "
    "You must decide ALL missing details yourself without asking the user. "
    "Your output will allow agents to build the system with ZERO conflicts. "
    "Be explicit about function signatures, input/output types, file paths, "
    "API routes, and dependencies."
)

def generate_full_spec(user_input: str):
    """Generate a complete A-to-Z multi-agent spec from a single user description."""
    prompt = f"""
User's request:
\"\"\"{user_input}\"\"\"

Now produce STRICT JSON ONLY with the following shape:
{{
  "version": "1.0",
  "project": "<short descriptive name>",
  "type": "<website|mobile app|ai model|blockchain|api service|other>",
  "description": "<1-2 sentence project description>",
  "tech_stack": {{
    "frontend": {{ "framework": "<string>", "version": "<semver>" }},
    "backend":  {{ "framework": "<string>", "version": "<semver>" }},
    "languages": ["<list of languages>"],
    "package_manager": "<npm|pip|yarn|other>"
  }},
  "file_tree": [
    {{ "path": "<file_or_dir>", "purpose": "<short description>" }}
  ],
  "api_contracts": [
    {{
      "name": "<api_name>",
      "method": "<GET|POST|PUT|DELETE>",
      "path": "<string>",
      "request": {{ "type": "<schema or fields>" }},
      "response": {{ "type": "<schema or fields>" }}
    }}
  ],
  "data_models": [
    {{ "name": "<model_name>", "fields": [{{"name": "<field>", "type": "<type>", "required": true}}] }}
  ],
  "function_specs": [
    {{
      "name": "<function_name>",
      "agent": "<frontend|backend|ml|blockchain|docs|qa>",
      "args": [{{"name": "<arg>", "type": "<type>"}}],
      "returns": "<type>",
      "description": "<short description>"
    }}
  ],
  "agent_tasks": [
    {{
      "id": "t1",
      "file": "<filename>",
      "role": "<agent role>",
      "agent": "<frontend|backend|ml|blockchain|docs|qa>",
      "instructions": "detailed task instructions",
      "depends_on": ["<task_ids>"]
    }}
  ],
  "agent_dependencies": [
    {{
      "from": "<task_id>",
      "to": "<task_id>",
      "reason": "<why this dependency exists>"
    }}
  ],
  "coding_guidelines": {{
    "style": "coding style & formatting rules",
    "error_handling": "error handling rules",
    "security": "security considerations"
  }},
  "testing_requirements": [
    "clear test requirements and cases"
  ],
  "acceptance_criteria": [
    "clear acceptance criteria"
  ]
}}

Rules:
- Fill EVERYTHING with concrete details.
- Use consistent naming for files, functions, models, and API paths.
- No placeholders like 'TBD' or empty arrays.
- Think like you're building it yourself for real.
"""

    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0.1,
        messages=[
            {"role": "system", "content": SPEC_SYSTEM},
            {"role": "user", "content": prompt}
        ],
    )

    raw = resp.choices[0].message["content"]
    spec = _extract_json_safe(raw)

    if not spec:
        raise ValueError("Spec generation failed — no valid JSON returned")
    return spec
@agents_bp.route('/orchestrator', methods=['POST', 'OPTIONS'])
def orchestrator():
    if request.method == 'OPTIONS':
        return ('', 200)

    try:
        body = request.get_json(force=True, silent=True) or {}

        # Accept multiple possible keys or a raw string
        if isinstance(body, str):
            user_input = body.strip()
        else:
            user_input = (
                body.get("answer")
                or body.get("content")
                or body.get("message")
                or body.get("input")
                or ""
            ).strip()

        if not user_input:
            return jsonify({
                "error": "No valid project description provided.",
                "hint": "Send JSON like { 'answer': 'Website for women’s clothing business' }"
            }), 400

        spec = generate_full_spec(user_input)

        return jsonify({
            "role": "assistant",
            "content": f"✅ Complete Project Spec for {spec.get('project')}",
            "spec": spec
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
