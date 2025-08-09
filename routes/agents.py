# routes/agents.py
from flask import Blueprint, request, jsonify
import os, json, re
import openai

agents_bp = Blueprint('agents', __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# User session memory (in production, use DB or Redis)
user_sessions = {}

# Forgiving JSON extractor
def _extract_json_safe(text: str):
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

# System prompt for spec generation
SPEC_SYSTEM = (
    "You are a Chief Software Architect. "
    "Your job is to create a COMPLETE and CONSISTENT multi-agent build specification "
    "based on the user's high-level requirements. "
    "The user will NEVER provide low-level implementation details — you must decide all names, file paths, API routes, and structures yourself. "
    "Output STRICT JSON ONLY — no markdown, no prose."
)

# High-level question sequence
QUESTION_FLOW = [
    {"key": "purpose", "text": "What is the main purpose or goal of this project?"},
    {"key": "type", "text": "What type of project is it? (e.g., website, mobile app, AI model, blockchain, API service)"},
    {"key": "audience", "text": "Who is the target audience or main user group?"},
    {"key": "features", "text": "What main features or modules should it have?"},
    {"key": "platforms", "text": "What platforms should it run on? (web, iOS, Android, CLI, API, IoT)"},
    {"key": "integrations", "text": "Any integrations or APIs required? (e.g., payment gateways, OpenAI, AWS, Google Maps)"},
    {"key": "scale", "text": "Any performance or scalability requirements? (e.g., handle 10k concurrent users, high security)"},
    {"key": "design", "text": "Any design or UI style preferences?"},
    {"key": "timeline", "text": "What’s your target timeline for the MVP or first version?"}
]
def generate_spec(high_level: dict):
    # Convert answers into JSON string for prompt
    user_context = json.dumps(high_level, indent=2)

    prompt = f"""
User's high-level requirements:
{user_context}

Now produce a STRICT JSON specification with this shape:
{{
  "version": "1.0",
  "project": "<short name>",
  "type": "<website|mobile app|ai model|blockchain|api service|other>",
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
      "request": {{ }},
      "response": {{ }}
    }}
  ],
  "data_models": [
    {{ "name": "<model_name>", "fields": [{{"name": "<field>", "type": "<type>", "required": true}}] }}
  ],
  "coding_guidelines": {{
    "style": "coding style & formatting rules",
    "error_handling": "error handling rules",
    "security": "security considerations"
  }},
  "acceptance_criteria": [
    "list of clear acceptance criteria"
  ],
  "tasks": [
    {{
      "id": "t1",
      "file": "<filename>",
      "role": "<agent role>",
      "agent": "<frontend|backend|ml|blockchain|docs|qa>",
      "instructions": "detailed task instructions",
      "depends_on": []
    }}
  ]
}}

Rules:
- Decide ALL low-level implementation details yourself.
- Keep names, API paths, and file structure consistent.
- Do not leave any placeholder fields empty.
- This spec must allow multiple AI agents to generate fully compatible code with zero conflicts.
"""

    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": SPEC_SYSTEM},
            {"role": "user", "content": prompt}
        ],
    )

    raw = resp.choices[0].message["content"]
    spec = _extract_json_safe(raw)

    if not spec:
        raise ValueError("Spec generation failed — no valid JSON")
    return spec
@agents_bp.route('/orchestrator', methods=['POST', 'OPTIONS'])
def orchestrator():
    if request.method == 'OPTIONS':
        return ('', 200)

    body = request.get_json(force=True) or {}
    user_id = body.get("user_id", "default")
    user_input = (body.get("answer") or "").strip()

    session = user_sessions.get(user_id, {"answers": {}, "step": 0})

    # Save answer from previous step
    if session["step"] > 0:
        last_key = QUESTION_FLOW[session["step"] - 1]["key"]
        session["answers"][last_key] = user_input

    # If we still have more questions to ask
    if session["step"] < len(QUESTION_FLOW):
        question = QUESTION_FLOW[session["step"]]["text"]
        session["step"] += 1
        user_sessions[user_id] = session
        return jsonify({"role": "assistant", "content": question})

    # All questions answered → generate spec
    spec = generate_spec(session["answers"])
    return jsonify({
        "role": "assistant",
        "content": f"✅ Project Spec for {spec.get('project')}",
        "spec": spec
    })
