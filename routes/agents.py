# routes/agents.py
from flask import Blueprint, request, jsonify
import os, json, re
import openai
from datetime import datetime

agents_bp = Blueprint("agents", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ===== Helper: safe JSON extraction =====
def _extract_json_safe(text: str):
    """Extract JSON object/array from LLM output, even if surrounded by text/markdown."""
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
    "You are an elite senior software architect and lead AI orchestrator. "
    "Your job is to take a user's idea and produce a COMPLETE multi-agent project spec. "
    "This spec must eliminate ALL possibility of incompatibility between modules and agents."
    "\n--- RULES ---\n"
    "1. Do NOT ask for coding or tech choices — infer optimal stack yourself.\n"
    "2. Output STRICT JSON ONLY — no prose, no markdown.\n"
    "3. For EVERY function, class, and variable, define:\n"
    "   - Exact name\n"
    "   - Purpose\n"
    "   - Inputs (name, type, description)\n"
    "   - Outputs (name, type, description)\n"
    "4. Define a global naming contract so all agents use identical identifiers.\n"
    "5. Define complete API contracts (method, path, request/response JSON schema).\n"
    "6. Define data models & DB schema if needed.\n"
    "7. Map dependencies so agents know which module calls which.\n"
    "8. Include testing requirements for every public function.\n"
    "9. Split into independent modules if large.\n"
    "10. Ensure file paths in `tasks` exist in `file_tree`.\n"
    "11. Guarantee consistent imports & interface contracts.\n"
    "12. Output must be valid JSON — use the exact template provided."
)

# ===== JSON Template =====
SPEC_USER_TEMPLATE = """
Project request:
{project}

Produce STRICT JSON in EXACT format:
{
  "version": "2.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short descriptive name>",
  "project_type": "<web_app|cli_tool|backend_api|ml_system|automation|game|desktop_app|other>",
  "description": "<one paragraph summary>",
  "target_users": ["<end user group 1>", "<end user group 2>"],
  "tech_stack": {
    "frontend": {"framework": "<string>", "version": "<semver or latest>"},
    "backend": {"framework": "<string>", "version": "<semver or latest>"},
    "languages": ["<e.g., Python 3.11>", "<JavaScript ES2022>"],
    "databases": ["<if any>"],
    "tools": ["<build tools, libs, deps>"]
  },
  "file_tree": [
    {"path": "src/main.py", "purpose": "Main entrypoint"},
    {"path": "tests/test_main.py", "purpose": "Basic tests"}
  ],
  "global_naming_contract": {
    "variables": [{"name": "user_id", "type": "uuid", "description": "Unique user identifier"}],
    "functions": [{"name": "upload_design", "description": "Upload new product design"}]
  },
  "function_contracts": [
    {
      "name": "upload_design",
      "defined_in": "src/backend/designs.py",
      "inputs": {"file": "image", "metadata": "object"},
      "outputs": {"status": "string", "design_id": "uuid"}
    }
  ],
  "api_contracts": [
    {
      "name": "CreateDesign",
      "method": "POST",
      "path": "/api/designs",
      "request": {"body": {"file": "binary", "title": "string"}},
      "response": {"200": {"design_id": "uuid"}, "400": {"error": "string"}}
    }
  ],
  "data_models": [
    {"name": "Design", "fields": [
      {"name": "id", "type": "uuid", "required": true},
      {"name": "title", "type": "string", "required": true}
    ]}
  ],
  "modules": [
    {"name": "frontend", "description": "Handles UI rendering & user interaction"},
    {"name": "backend", "description": "Processes requests & manages DB"}
  ],
  "agent_roles": [
    {
      "name": "frontend",
      "responsibilities": ["UI layout", "Form submission", "API integration"],
      "dependencies": ["backend"]
    }
  ],
  "coding_guidelines": {
    "style": "Follow language-specific style guides (e.g., PEP8, ESLint)",
    "testing": "Write tests for all public functions",
    "error_handling": "Gracefully handle and log errors"
  },
  "acceptance_criteria": [
    "All modules integrate without naming mismatches",
    "Passes all automated tests",
    "Meets user-visible feature requirements"
  ],
  "tasks": [
    {
      "id": "t1",
      "file": "src/main.py",
      "role": "Backend Developer",
      "agent": "backend",
      "instructions": "Implement entrypoint and module loader",
      "depends_on": []
    }
  ]
}
"""
# ===== Spec Generator =====
def generate_spec(project: str):
    """
    Generates a COMPLETE multi-agent project specification for ANY type of software.
    Automatically includes:
    - File tree & purpose
    - Function & naming contracts
    - API endpoints
    - Data models
    - Agent roles
    - Dependencies
    - Coding standards & acceptance criteria
    """

    # Inject current timestamp into template
    template_filled = SPEC_USER_TEMPLATE.replace(
        "{project}", project
    ).replace(
        "<ISO timestamp>", datetime.utcnow().isoformat() + "Z"
    )

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # You can change to a bigger model for more detail
            temperature=0.2,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": template_filled}
            ],
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

    raw_output = resp.choices[0].message["content"]
    spec = _extract_json_safe(raw_output)

    if not spec:
        raise ValueError("❌ Failed to parse JSON spec from AI output")

    # Validate required keys
    required_keys = ["project", "tech_stack", "file_tree", "tasks"]
    for key in required_keys:
        if key not in spec:
            raise ValueError(f"❌ Missing key in spec: {key}")

    # Validate file references
    file_paths = {f.get("path") for f in spec.get("file_tree", []) if f.get("path")}
    bad_tasks = [t for t in spec.get("tasks", []) if t.get("file") not in file_paths]
    if bad_tasks:
        print(f"⚠️ Removing tasks with invalid file references: {bad_tasks[:3]}")
        spec["tasks"] = [t for t in spec.get("tasks", []) if t.get("file") in file_paths]

    # Handle large JSON output by splitting into chunks
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

# ===== Orchestrator Route =====
@agents_bp.route("/orchestrator", methods=["POST", "OPTIONS"])
def orchestrator():
    """
    One-shot orchestrator:
    - Takes a single project description
    - Infers all technical details automatically
    - Returns full multi-agent spec in JSON
    """
    if request.method == "OPTIONS":
        return ("", 200)

    body = request.get_json(force=True) or {}
    project_desc = (body.get("project") or "").strip()

    if not project_desc:
        return jsonify({
            "role": "assistant",
            "content": "Please describe your project idea in one or two sentences."
        })

    try:
        spec = generate_spec(project_desc)

        # Short summary for the chat
        summary_lines = [
            f"**Project:** {spec.get('project', '')}",
            f"**Type:** {spec.get('project_type', '')}",
            f"**Modules:** {', '.join([m['name'] for m in spec.get('modules', [])])}",
            "",
            "**Tasks:**"
        ]
        for i, t in enumerate(spec.get("tasks", []), 1):
            summary_lines.append(
                f"{i}. **{t.get('file')}** — _{t.get('role')}_"
            )

        return jsonify({
            "role": "assistant",
            "content": "\n".join(summary_lines),
            "spec": spec
        })

    except Exception as e:
        return jsonify({
            "role": "assistant",
            "content": f"❌ Spec generation failed: {e}"
        })
# ===== Extended JSON Template for Simulation =====
SIMULATION_ENHANCED_TEMPLATE = """
Project request:
{project}

Produce STRICT JSON with this extra section:
{
  ...
  "inter_agent_protocols": [
    {
      "protocol_id": "p1",
      "from_agent": "frontend",
      "to_agent": "backend",
      "trigger_event": "user_uploads_design",
      "request_function": "upload_design",
      "request_schema": {
        "file": "binary",
        "title": "string",
        "category": "string"
      },
      "response_schema": {
        "status": "string",
        "design_id": "uuid"
      },
      "error_schema": {
        "error_code": "string",
        "message": "string"
      },
      "timeout_seconds": 5
    }
  ],
  "pre_coding_simulation": {
    "steps": [
      {
        "step_id": "s1",
        "description": "Frontend calls backend.upload_design with valid payload",
        "expected_response": {"status": "success", "design_id": "uuid"},
        "on_error": "Show error to user"
      }
    ],
    "failure_detection": [
      {
        "check": "If backend returns unexpected field",
        "resolution": "Update function contract to match backend output"
      }
    ],
    "simulation_result": "Pass or fail"
  }
}
"""

# ===== Simulation-Oriented Spec Generator =====
def generate_simulation_spec(project: str):
    """
    Generates a complete multi-agent project specification with:
    - Function contracts
    - Inter-agent protocols
    - Pre-coding simulation steps
    """
    filled_template = SIMULATION_ENHANCED_TEMPLATE.replace("{project}", project)

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.15,
            messages=[
                {"role": "system", "content": SPEC_SYSTEM},
                {"role": "user", "content": filled_template}
            ],
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}")

    raw_output = resp.choices[0].message["content"]
    spec = _extract_json_safe(raw_output)

    if not spec:
        raise ValueError("❌ Failed to parse JSON simulation spec")

    # Ensure all protocols have matching functions in function_contracts
    fc_names = {f["name"] for f in spec.get("function_contracts", [])}
    for proto in spec.get("inter_agent_protocols", []):
        if proto.get("request_function") not in fc_names:
            raise ValueError(f"⚠️ Protocol {proto['protocol_id']} uses undefined function {proto['request_function']}")

    return spec

# ===== Simulation-Oriented Orchestrator =====
@agents_bp.route("/orchestrator-sim", methods=["POST", "OPTIONS"])
def orchestrator_with_simulation():
    """
    Same as /orchestrator but includes:
    - Inter-agent communication protocols
    - Pre-coding simulation of data flow
    """
    if request.method == "OPTIONS":
        return ("", 200)

    body = request.get_json(force=True) or {}
    project_desc = (body.get("project") or "").strip()

    if not project_desc:
        return jsonify({
            "role": "assistant",
            "content": "Please describe your project idea."
        })

    try:
        spec = generate_simulation_spec(project_desc)

        summary_lines = [
            f"**Project:** {spec.get('project', '')}",
            f"**Type:** {spec.get('project_type', '')}",
            "",
            "**Inter-Agent Protocols:**"
        ]
        for proto in spec.get("inter_agent_protocols", []):
            summary_lines.append(
                f"- {proto['from_agent']} → {proto['to_agent']} : {proto['request_function']}"
            )

        summary_lines.append("")
        summary_lines.append(f"**Simulation Result:** {spec.get('pre_coding_simulation', {}).get('simulation_result', 'Unknown')}")

        return jsonify({
            "role": "assistant",
            "content": "\n".join(summary_lines),
            "spec": spec
        })

    except Exception as e:
        return jsonify({
            "role": "assistant",
            "content": f"❌ Simulation spec generation failed: {e}"
        })
