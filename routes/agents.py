from flask import Blueprint, request, jsonify
import os, json, re
import openai
from datetime import datetime

agents_bp = Blueprint("agents", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")
user_sessions = {}

# ===== JSON extractor =====
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


# ===== System Prompt =====
SPEC_SYSTEM = (
    "You are an elite senior software architect and AI project orchestrator. "
    "You must produce a FINAL, COMPLETE, ZERO-AMBIGUITY multi-agent project specification. "
    "Agents will NOT make creative or technical choices — every single detail must be here."
    "\n--- RULES ---\n"
    "1. Always first check if design/style/branding preferences are provided. "
    "   If not, set them to 'no preference'.\n"
    "2. Infer ALL technical choices yourself — stack, architecture, versions, dependencies, file tree.\n"
    "3. Output STRICT JSON ONLY — no prose, no markdown.\n"
    "4. Define:\n"
    "   - Global naming contract (variables, constants, functions, classes, DB tables, APIs)\n"
    "   - Function signatures (name, purpose, parameters with type, return type, example payloads)\n"
    "   - API endpoints with request/response JSON schema\n"
    "   - DB schema (tables, columns, types, constraints)\n"
    "   - File paths with purpose + exact content outline\n"
    "   - Component structure for frontend (React components, CSS classes)\n"
    "   - Test cases for every public function\n"
    "   - Exact agent instructions (must be executable as-is)\n"
    "5. All naming must match exactly across all modules.\n"
    "6. If a function is called in one file, define it in another with identical signature.\n"
    "7. For large outputs, split into JSON chunks but maintain valid structure."
)

# ===== Spec Template =====
SPEC_TEMPLATE = """
Project: {project}
Design Preferences: {design}

Produce STRICT JSON:
{
  "version": "3.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<one sentence summary>",
  "project_type": "<web_app|cli_tool|backend_api|ml_system|automation|game|desktop_app|other>",
  "target_users": ["<group1>", "<group2>"],
  "design_preferences": {
    "style": "<UI style or 'no preference'>",
    "colors": ["<hex or name>"],
    "layout": "<layout type>",
    "tone": "<tone of text>",
    "branding": "<brand guidelines>",
    "accessibility": "<notes>"
  },
  "tech_stack": {
    "frontend": {"framework": "<string>", "version": "<semver>"},
    "backend": {"framework": "<string>", "version": "<semver>"},
    "languages": ["<lang version>"],
    "databases": ["<db>"],
    "tools": ["<build tools>"]
  },
  "global_naming_contract": {
    "variables": [{"name": "user_id", "type": "uuid", "description": "Unique user ID"}],
    "functions": [{"name": "upload_design", "description": "Uploads a design"}],
    "classes": [{"name": "DesignModel", "description": "Represents a design"}],
    "api_endpoints": ["/api/designs"]
  },
  "function_contracts": [
    {
      "name": "upload_design",
      "defined_in": "src/backend/designs.py",
      "purpose": "Uploads a new product design to storage and DB",
      "inputs": {"file": "binary", "title": "string", "category": "string"},
      "outputs": {"status": "string", "design_id": "uuid"},
      "example_input": {"file": "<binary data>", "title": "Summer Dress", "category": "Dresses"},
      "example_output": {"status": "success", "design_id": "550e8400-e29b-41d4-a716-446655440000"}
    }
  ],
  "api_contracts": [
    {
      "name": "CreateDesign",
      "method": "POST",
      "path": "/api/designs",
      "request": {"body": {"file": "binary", "title": "string", "category": "string"}},
      "response": {"200": {"design_id": "uuid"}, "400": {"error": "string"}}
    }
  ],
  "db_schema": [
    {
      "table": "designs",
      "columns": [
        {"name": "id", "type": "uuid", "constraints": "PRIMARY KEY"},
        {"name": "title", "type": "varchar(255)", "constraints": "NOT NULL"},
        {"name": "category", "type": "varchar(100)", "constraints": "NOT NULL"}
      ]
    }
  ],
  "file_tree": [
    {"path": "src/main.py", "purpose": "Main backend entrypoint"},
    {"path": "src/backend/designs.py", "purpose": "Design-related backend logic"}
  ],
  "tasks": [
    {
      "id": "t1",
      "file": "src/backend/designs.py",
      "role": "Backend Developer",
      "agent": "backend",
      "instructions": "Write upload_design() exactly as per function_contracts[0], using S3Uploader from src/backend/storage.py",
      "depends_on": []
    }
  ],
  "test_cases": [
    {
      "function": "upload_design",
      "tests": [
        {"name": "ValidUpload", "input": {"file": "<valid>", "title": "Test", "category": "Dresses"}, "expected": {"status": "success"}},
        {"name": "InvalidFileType", "input": {"file": "<.txt>", "title": "Test", "category": "Dresses"}, "expected": {"status": "error"}}
      ]
    }
  ]
}
"""

# ===== Spec Generator =====
# ===== Spec Generator =====
def generate_spec(project: str, design: str):
    filled = SPEC_TEMPLATE.replace("{project}", project).replace("{design}", design).replace(
        "<ISO timestamp>", datetime.utcnow().isoformat() + "Z"
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.15,
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

    # Stage 1: Get project idea
    if session["stage"] == "project":
        if not project:
            return jsonify({
                "role": "assistant",
                "content": "What is your project idea?"
            })
        session["project"] = project
        session["stage"] = "design"
        return jsonify({
            "role": "assistant",
            "content": "Do you have preferences for design style, colors, layout, branding, tone, or accessibility?"
        })

    # Stage 2: Get design preferences and generate spec
    if session["stage"] == "design":
        session["design"] = design if design else "no preference"
        session["stage"] = "done"

        try:
            spec = generate_spec(session["project"], session["design"])
            # Show full spec directly in the response
            return jsonify({
                "role": "assistant",
                "content": f"✅ Full project spec generated:\n\n{json.dumps(spec, indent=2)}"
            })
        except Exception as e:
            return jsonify({
                "role": "assistant",
                "content": f"❌ Failed to generate spec: {e}"
            })
