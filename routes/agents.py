from flask import Blueprint, request, jsonify
import os, json, re
import openai
from datetime import datetime

agents_bp = Blueprint("agents", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ===== In-memory session store =====
# Move this here so it's defined before orchestrator() uses it
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
  "version": "4.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<detailed summary>",
  "project_type": "web_app",
  "target_users": ["designers", "small business owners"],
  "design_preferences": {
    "style": "no preference",
    "colors": ["#FFFFFF", "#000000"],
    "layout": "responsive",
    "tone": "professional",
    "branding": "none",
    "accessibility": "WCAG 2.1 AA"
  },
  "tech_stack": {
    "frontend": {"framework": "React", "version": "18.2.0"},
    "backend": {"framework": "Flask", "version": "2.3.2"},
    "languages": ["Python 3.11", "JavaScript ES2022"],
    "databases": ["PostgreSQL 15"],
    "tools": ["Docker 24", "Webpack 5"]
  },
  "global_naming_contract": {
    "variables": [
      {"name": "user_id", "type": "uuid", "description": "Unique user identifier"},
      {"name": "ALLOWED_FILE_TYPES", "type": "list[str]", "description": "Accepted MIME types for uploads"}
    ],
    "functions": [
      {"name": "upload_design", "description": "Uploads a design"},
      {"name": "save_to_db", "description": "Persists record to database"}
    ],
    "classes": [
      {"name": "DesignModel", "description": "DB ORM model for designs"}
    ],
    "api_endpoints": [
      "/api/designs",
      "/api/designs/{id}"
    ],
    "events": [
      "DESIGN_UPLOADED",
      "UPLOAD_FAILED"
    ],
    "css_classes": [
      "upload-form",
      "upload-button",
      "error-message"
    ]
  },
  "function_contracts": [
    {
      "name": "upload_design",
      "defined_in": "src/backend/designs.py",
      "purpose": "Uploads a new product design to storage and DB",
      "parameters": [
        {"name": "file", "type": "binary", "required": true},
        {"name": "title", "type": "string", "required": true},
        {"name": "category", "type": "string", "required": true}
      ],
      "returns": {"status": "string", "design_id": "uuid"},
      "example_call": "upload_design(file, title, category)",
      "example_output": {"status": "success", "design_id": "uuid"}
    },
    {
      "name": "save_to_db",
      "defined_in": "src/backend/db.py",
      "parameters": [
        {"name": "record", "type": "object", "required": true}
      ],
      "returns": {"id": "uuid"}
    }
  ],
  "api_contracts": [
    {
      "name": "CreateDesign",
      "method": "POST",
      "path": "/api/designs",
      "request": {
        "headers": {"Content-Type": "multipart/form-data"},
        "body": {"file": "binary", "title": "string", "category": "string"}
      },
      "response": {
        "200": {"design_id": "uuid"},
        "400": {"error": "string"}
      }
    }
  ],
  "db_schema": [
    {
      "table": "designs",
      "columns": [
        {"name": "id", "type": "uuid", "constraints": "PRIMARY KEY"},
        {"name": "title", "type": "varchar(255)", "constraints": "NOT NULL"},
        {"name": "category", "type": "varchar(100)", "constraints": "NOT NULL"}
      ],
      "indexes": ["title", "category"]
    }
  ],
  "file_tree": [
    {"path": "src/main.py", "purpose": "Flask entrypoint", "imports": ["flask", "src.backend.designs"], "functions": ["create_app"]},
    {"path": "src/backend/designs.py", "purpose": "Design API logic", "imports": ["save_to_db", "S3Uploader"], "functions": ["upload_design"]},
    {"path": "src/backend/db.py", "purpose": "Database helpers", "functions": ["save_to_db"]}
  ],
  "inter_agent_protocols": [
    {
      "protocol_id": "p1",
      "from_agent": "frontend",
      "to_agent": "backend",
      "trigger_event": "form_submit",
      "function": "upload_design",
      "request_schema": {"file": "binary", "title": "string", "category": "string"},
      "response_schema": {"status": "string", "design_id": "uuid"},
      "error_schema": {"error": "string"}
    }
  ],
  "simulation": {
    "steps": [
      {"step": "frontend calls backend.upload_design()", "expected": "status=success, design_id != null"},
      {"step": "backend calls save_to_db()", "expected": "id returned"}
    ],
    "result": "pass"
  },
  "tasks": [
    {"id": "t1", "file": "src/backend/designs.py", "agent": "backend", "instructions": "Implement upload_design() exactly per function_contracts[0]"},
    {"id": "t2", "file": "src/frontend/components/UploadForm.js", "agent": "frontend", "instructions": "Submit form data matching /api/designs request schema"}
  ],
  "test_cases": [
    {"function": "upload_design", "tests": [{"name": "valid_upload", "input": {...}, "expected": {...}}]}
  ]
}

"""
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

    # Always ensure session exists
    if user_id not in user_sessions:
        user_sessions[user_id] = {"stage": None, "project": "", "design": ""}

    session = user_sessions[user_id]

    # If no stage, try to skip the Q&A flow if both values provided
    if not session["stage"]:
        if project and design:
            session.update({"stage": "done", "project": project, "design": design})
        elif project:
            session.update({"stage": "design", "project": project})
        else:
            session["stage"] = "project"

    # Stage: ask for project
    if session["stage"] == "project":
        if not project:
            return jsonify({"role": "assistant", "content": "What is your project idea?"})
        session["project"] = project
        session["stage"] = "design"
        return jsonify({"role": "assistant", "content": "Do you have preferences for design style, colors, layout, branding, tone, or accessibility?"})

    # Stage: ask for design, then generate spec
    if session["stage"] == "design":
        session["design"] = design if design else "no preference"
        session["stage"] = "done"

    # Stage: done → always generate spec
    try:
        spec = generate_spec(session["project"], session["design"] or "no preference")
        return jsonify({"role": "assistant", "content": f"✅ Full project spec generated:\n\n{json.dumps(spec, indent=2)}"})
    except Exception as e:
        return jsonify({"role": "assistant", "content": f"❌ Failed to generate spec: {e}"})
