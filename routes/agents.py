# routes/agents.py
from flask import Blueprint, request, jsonify
import os, json, re
import openai

agents_bp = Blueprint('agents', __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Simple in-memory state for each "conversation"
# In production, use Redis or DB
user_sessions = {}

# Helper to parse JSON from LLM output
def _extract_json_safe(text: str):
    """More forgiving JSON extractor."""
    if not text:
        return None
    s = text.strip()
    # Remove markdown fences if present
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.MULTILINE).strip()

    # First try direct parse
    try:
        return json.loads(s)
    except Exception:
        pass

    # Try substring search for JSON object or array
    start = min([p for p in [s.find("{"), s.find("[")] if p != -1] or [-1])
    if start != -1:
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

Constraints (hard requirements):
{constraints}

Produce STRICT JSON (no markdown) with EXACT shape:
{
  "version": "1.0",
  "project": "<short name>",
  "tech_stack": {
    "frontend": { "framework": "<string>", "version": "<semver>" },
    "backend":  { "framework": "<string>", "version": "<semver>" },
    "language_standards": ["<e.g. ES2022>", "<PEP8>"]
  },
  "file_tree": [
    { "path": "app.py", "purpose": "Flask app entrypoint" },
    { "path": "templates/base.html", "purpose": "Layout with <main> and blocks" },
    { "path": "templates/index.html", "purpose": "Home page" },
    { "path": "templates/about.html", "purpose": "About page" },
    { "path": "templates/pricing.html", "purpose": "Pricing page" },
    { "path": "templates/blog_list.html", "purpose": "Blog list" },
    { "path": "templates/blog_post.html", "purpose": "Blog article page" },
    { "path": "templates/contact.html", "purpose": "Contact form page" },
    { "path": "static/css/style.css", "purpose": "Global styles & utility classes" },
    { "path": "static/js/main.js", "purpose": "Interactions + analytics hook" },
    { "path": "static/img/", "purpose": "Images" },
    { "path": "static/favicon.ico", "purpose": "Favicon" },
    { "path": "static/site.webmanifest", "purpose": "PWA/manifest (basic)" },
    { "path": "sitemap.xml", "purpose": "SEO sitemap" },
    { "path": "robots.txt", "purpose": "Crawler rules" },
    { "path": "requirements.txt", "purpose": "Dependencies" },
    { "path": "README.md", "purpose": "Project setup & run instructions" },
    { "path": "tests/test_routes.py", "purpose": "Smoke tests for routes" }
  ],
  "api_contracts": [
    {
      "name": "submitContact",
      "method": "POST",
      "path": "/api/contact",
      "request": { "body": { "name":"string", "email":"string", "message":"string" } },
      "response": { "200": { "ok": true }, "400": { "error": "string" }, "500": { "error": "string" } }
    }
  ],
  "data_models": [
    { "name": "ContactMessage", "fields": [
      { "name": "name", "type": "string", "required": true },
      { "name": "email", "type": "string", "required": true },
      { "name": "message", "type": "string", "required": true },
      { "name": "created_at", "type": "datetime", "required": true }
    ]}
  ],
  "coding_guidelines": {
    "templating": "Use Jinja blocks and extends; no inline styles",
    "css": "Use utility-like classes + mobile-first breakpoints",
    "js": "No large frameworks; addListeners in DOMContentLoaded",
    "accessibility": "WCAG AA contrast, aria-labels for nav and form",
    "imports": "Use relative imports; keep files under 300 lines unless necessary",
    "error_handling": "Return JSON errors from APIs; show form errors inline"
  },
  "acceptance_criteria": [
    "All pages render using base layout and are responsive (mobile/tablet/desktop).",
    "Contact form validates on client and server and returns JSON { ok: true }.",
    "SEO files exist (sitemap.xml, robots.txt, meta tags in base.html).",
    "Favicon and manifest present.",
    "tests/test_routes.py passes basic GET smoke tests.",
    "README includes install/run instructions."
  ],
  "tasks": [
    {
      "id": "t1",
      "file": "app.py",
      "role": "Backend Developer",
      "agent": "backend",
      "instructions": "Create Flask app with routes: '/', '/about', '/pricing', '/blog', '/blog/<slug>', '/contact', and '/api/contact' (POST). Render templates; POST validates JSON and returns { ok: true }.",
      "depends_on": []
    },
    {
      "id": "t2",
      "file": "templates/base.html",
      "role": "Frontend Developer",
      "agent": "frontend",
      "instructions": "Layout with <header> navbar (active link), <main> block, <footer>; include meta tags, OG tags, favicon, and link css/js; use semantic landmarks and skip-to-content link.",
      "depends_on": ["t1"]
    },
    {
      "id": "t3",
      "file": "templates/index.html",
      "role": "Frontend Developer",
      "agent": "frontend",
      "instructions": "Hero with CTA, features grid, testimonials section; extends base.html.",
      "depends_on": ["t2"]
    },
    {
      "id": "t4",
      "file": "templates/contact.html",
      "role": "Frontend Developer",
      "agent": "frontend",
      "instructions": "Form with name/email/message; client-side validation; posts to /api/contact; show success/error banner.",
      "depends_on": ["t2"]
    },
    {
      "id": "t5",
      "file": "static/css/style.css",
      "role": "Frontend Developer",
      "agent": "frontend",
      "instructions": "Mobile-first utilities (container, grid, spacing, colors), responsive navbar, forms, cards; AA contrast.",
      "depends_on": []
    },
    {
      "id": "t6",
      "file": "static/js/main.js",
      "role": "Frontend Developer",
      "agent": "frontend",
      "instructions": "DOMContentLoaded handler, nav active-state, smooth scroll, simple analytics hook.",
      "depends_on": []
    },
    {
      "id": "t7",
      "file": "sitemap.xml",
      "role": "Docs",
      "agent": "docs",
      "instructions": "Include '/', '/about', '/pricing', '/blog', '/contact' URLs.",
      "depends_on": ["t1"]
    },
    {
      "id": "t8",
      "file": "tests/test_routes.py",
      "role": "Backend Developer",
      "agent": "backend",
      "instructions": "Pytest: assert GET routes return 200; POST /api/contact returns 200 with valid payload; 400 with invalid.",
      "depends_on": ["t1"]
    },
    {
      "id": "t9",
      "file": "README.md",
      "role": "Docs",
      "agent": "docs",
      "instructions": "Install/run instructions, endpoints, and structure.",
      "depends_on": ["t1","t2","t3","t4","t5","t6","t7","t8"]
    }
  ]
}

Rules:
- Do NOT output trivial scaffolds (index.html only). Enforce at least 6 templates/pages when min_pages>=6.
- All task.file paths MUST exist in file_tree.
- Keep consistent names across api_contracts, templates, and tasks.
- NO MARKDOWN. JSON ONLY.
"""




def generate_spec(project: str, constraints: dict):
    default_constraints = {
        "backend_runtime": "python-flask",
        "frontend_runtime": "vanilla",
        "package_manager": "pip",
        "hosting": "static+flask-api",
        "forbid": ["node", "express", "server.js"]
    }
    merged = {**default_constraints, **(constraints or {})}

    # Use .replace instead of .format to avoid KeyError with curly braces in JSON
    user_prompt = SPEC_USER_TEMPLATE \
        .replace("{project}", project) \
        .replace("{constraints}", json.dumps(merged, indent=2))

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

    file_paths = {f.get("path") for f in spec.get("file_tree", []) if f.get("path")}
    bad = [t for t in spec.get("tasks", []) if t.get("file") not in file_paths]
    if bad:
        print(f"⚠️ Tasks reference unknown files, removing them: {bad[:3]}")
        spec["tasks"] = [t for t in spec.get("tasks", []) if t.get("file") in file_paths]

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
REQUIRED_KEYS = ["pages", "features"]

@agents_bp.route('/orchestrator', methods=['POST', 'OPTIONS'])
def orchestrator():
    if request.method == 'OPTIONS':
        return ('', 200)

    body = request.get_json(force=True) or {}
    user_id = body.get("user_id", "default")
    user_input = (body.get("project") or "").strip()
    constraints = body.get("constraints", {})

    session = user_sessions.get(user_id, {"project": "", "constraints": {}})

    # Step 1: No project yet
    if not session["project"]:
        if len(user_input.split()) < 3:
            return jsonify({
                "role": "assistant",
                "content": "Can you tell me more? What kind of website or app do you need — for a business, blog, store, portfolio, or something else?"
            })
        session["project"] = user_input
        user_sessions[user_id] = session
        return jsonify({"role": "assistant", "content": "How many pages should it have?"})

    # Step 2: Ask for pages
    if "pages" not in session["constraints"] and "pages" not in constraints:
        if user_input.isdigit():
            session["constraints"]["pages"] = int(user_input)
            user_sessions[user_id] = session
            return jsonify({"role": "assistant", "content": "Should it have any special features like payments, blog, accounts, or forms?"})
        else:
            return jsonify({"role": "assistant", "content": "Please give a number for how many main pages."})

    # Step 3: Ask for features
    if "features" not in session["constraints"] and "features" not in constraints:
        if user_input:
            session["constraints"]["features"] = user_input.lower()
            user_sessions[user_id] = session
        else:
            return jsonify({"role": "assistant", "content": "What special features should it have? (e.g. payments, blog, accounts)"})

    # Merge constraints
    session["constraints"].update(constraints)
    user_sessions[user_id] = session

    # Step 4: Check if all required keys are filled
    REQUIRED_KEYS = ["pages", "features"]
    if all(k in session["constraints"] for k in REQUIRED_KEYS):
        spec = generate_spec(session["project"], session["constraints"])
        if "error" in spec:
            return jsonify({
                "role": "assistant",
                "content": f"❌ I couldn't generate the project spec: {spec['error']}. Try adjusting your request or simplifying the requirements."
            })
        lines = [f"**Project:** {spec.get('project','')}", "\n**Tasks:**"]
        for i, t in enumerate(spec.get("tasks", []), 1):
            lines.append(f"{i}. **{t.get('file')}** — _{t.get('role')}_")
        return jsonify({"role": "assistant", "content": "\n".join(lines), "spec": spec})

    return jsonify({"role": "assistant", "content": "I still need a bit more detail before I can start building the spec."})