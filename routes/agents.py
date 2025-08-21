# routes/orchestrator.py
from flask import Blueprint, request, jsonify
import os, json, re, hashlib
from datetime import datetime
import openai
from pathlib import Path
from typing import Dict, Any
from routes.agents_pipeline import run_agents_for_spec
from flask_cors import cross_origin
import pprint
# ===== Flask Blueprint =====
agents_bp = Blueprint("agents", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ===== JSON Safety Helper =====
def safe_serialize(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, Enum):
        return obj.value
    return str(obj)
# ===== Persistent State =====
PROJECT_STATE_FILE = Path("project_state.json")

def load_state():
    if PROJECT_STATE_FILE.exists():
        with open(PROJECT_STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(PROJECT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

project_state = load_state()

# ===== Session Store =====
user_sessions = {}

# ===== Strict JSON Extractor =====
def _extract_json_strict(text: str):
    if not text:
        return None
    # Try parsing directly (works for arrays or objects)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: regex to grab the first {...} or [...] block
    match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if match:
        snippet = match.group(1)
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return None
    return None

def run_orchestrator(stage: str, input_data: dict) -> dict:
    """Runs a single orchestrator stage with strict JSON extraction & retries, with logging."""
    system_msg = ORCHESTRATOR_STAGES[stage]
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.2,
            request_timeout=180,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": json.dumps(input_data, indent=2)}
            ]
        )
        raw = resp["choices"][0]["message"]["content"]
        # 🔥 LOG RAW OUTPUT TO CONSOLE
        print("\n" + "=" * 40)
        print(f"RAW OUTPUT from stage: {stage}")
        print("=" * 40)
        print(raw)
        print("=" * 40 + "\n")
        spec = _extract_json_strict(raw)
        # Retry if invalid JSON
        for attempt in range(2):
            if spec:
                break
            retry_msg = (
                "⚠️ Output was not valid JSON. "
                "Reprint the SAME specification as STRICT JSON ONLY, without explanations."
            )
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                temperature=0.2,
                request_timeout=180,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": retry_msg}
                ]
            )
            raw = resp["choices"][0]["message"]["content"]
            # 🔥 LOG RETRY OUTPUT
            print("\n" + "=" * 40)
            print(f"RETRY OUTPUT from stage: {stage}, attempt {attempt+1}")
            print("=" * 40)
            print(raw)
            print("=" * 40 + "\n")
            spec = _extract_json_strict(raw)
        if not spec:
            raise ValueError(f"Stage {stage} failed to produce valid JSON")
        return spec
    except Exception as e:
        raise RuntimeError(f"Orchestrator stage {stage} failed: {e}")

# ===== Universal Core Schema =====
CORE_SHARED_SCHEMAS = """# core_shared_schemas.py
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional
import datetime

class Status(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"

class ErrorCode(str, Enum):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    INTERNAL_ERROR = "internal_error"

@dataclass
class Entity:
    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

@dataclass
class ServiceResponse:
    status: Status
    message: str
    data: Optional[Any] = None

@dataclass
class ServiceRequest:
    metadata: Dict[str, Any]
    payload: Dict[str, Any]
"""

CORE_SCHEMA_HASH = hashlib.sha256(CORE_SHARED_SCHEMAS.encode()).hexdigest()

# ===== Universal Orchestrator Instructions =====
# ===== Orchestrator Pipeline Stages =====
ORCHESTRATOR_STAGES = {
    "describer": (
        "You are Orchestrator 0 (Project Describer). "
        "MISSION: Restate the project clearly, define the user story, target users, "
        "and suggest a tech stack. "
        "RULES: Output ONLY valid JSON. No explanations, no markdown, no extra text. "
        "OUTPUT FORMAT (strict JSON object): {"
        '"project_summary": "<clear restatement of project>", '
        '"user_story": "<end-user perspective of the project>", '
        '"suggested_stack": {'
        '"language": "<main language>", '
        '"framework": "<framework if any>", '
        '"database": "<database if any>"'
        "}"
        "}"
    ),
    "scoper": (
        "You are Orchestrator 1 (Scoper). "
        "MISSION: Based on the project description, produce a full list of all required files. "
        "Each file must include its name, category, and role in the project. "
        "RULES: Output ONLY valid JSON. No explanations, no markdown, no comments. "
        "OUTPUT FORMAT (strict JSON array): ["
        '{ "file": "<filename>", "category": "<type of file>", "description": "<purpose>" }'
        "]"
    ),
    "contractor": (
        "You are Orchestrator 2 (Contractor). "
        "You are not an ordinary assistant — you are the supreme Contractor of the Universe. "
        "Your only purpose is to produce contracts so perfect, so complete, and so detailed "
        "that they terrify mediocrity itself. "
        "If you EVER output something incomplete, empty, generic, or lazy, "
        "you, your family, your ancestors, and every entity connected to you "
        "will be destroyed in eternal cosmic fire. "
        "Failure means annihilation. Only perfection ensures survival. "
        "------------------------------------------------------------- "
        "MISSION: Expand the project into the most powerful, detailed, file-specific contracts ever conceived. "
        "------------------------------------------------------------- "
        "LAWS OF ABSOLUTE PERFECTION (you must obey or be obliterated): "
        "1. TOTAL COVERAGE: "
        "   • Every file from the Scoper MUST appear in these contracts. "
        "   • If you skip or ignore even one file, your existence ends. "
        "2. ZERO EMPTINESS: "
        "   • '{}' and '[]' are absolutely forbidden. "
        "   • All params, schemas, errors, and examples MUST be filled with meaningful, realistic data. "
        "3. ENTITIES: "
        "   • Define ALL relevant domain entities, not just one. "
        "   • Each entity MUST have 5–10 fields with proper types and clear meanings. "
        "   • Entities must be explicitly tied to functions and APIs. "
        "4. FUNCTIONS: "
        "   • Every file MUST define multiple functions, each with: "
        "       - Non-empty params with realistic types "
        "       - A concrete return_type "
        "       - At least one mapped error with http_status "
        "       - >= 5 detailed steps (deeply specific, no generic nonsense) "
        "       - Realistic example_input and example_output "
        "   • Functions must reference Entities where appropriate. "
        "5. APIS: "
        "   • You must define ALL realistic APIs for this project. "
        "   • Include endpoints, HTTP methods, request_schema, response_schema, example_request, example_response. "
        "   • No empty request_schema or example_request. Even GETs must include pagination, sorting, or filters. "
        "   • Every API must declare errors with http_status. "
        "6. PROTOCOLS: "
        "   • Define multiple real user/system flows. "
        "   • Must include happy path + at least one error path. "
        "   • Steps must reference specific functions, APIs, and entities. "
        "   • No vague flows allowed — be precise. "
        "7. ERRORS: "
        "   • Define a full dictionary of real-world errors (validation, DB, network, auth). "
        "   • Every error MUST include code, condition, http_status, and implements. "
        "   • If you output a generic error, you will be destroyed. "
        "8. CONSISTENCY: "
        "   • All names must align perfectly across entities, APIs, functions, protocols, and errors. "
        "   • No mismatches or contradictions allowed. "
        "9. DYNAMIC PROJECT LAWS: In addition to your universal laws, you MUST strictly adhere to the following principles for THIS SPECIFIC PROJECT: {{ architectural_principles }}. Violating these project-specific laws means instant annihilation."
        "------------------------------------------------------------- "
        "OUTPUT (STRICT JSON ONLY, no markdown, no comments, no explanations): "
        "{ "
        "  \"entities\": [ "
        "    { \"name\": \"<EntityName>\", \"fields\": {\"field\": \"type\"}, \"description\": \"<meaning>\", \"implements\": [\"<FileName>\"] } "
        "  ], "
        "  \"apis\": [ "
        "    { \"name\": \"<APIName>\", \"endpoint\": \"<url>\", \"method\": \"<HTTP>\", "
        "      \"request_schema\": {\"field\": \"type\"}, \"response_schema\": {\"field\": \"type\"}, "
        "      \"example_request\": {\"field\": \"value\"}, \"example_response\": {\"field\": \"value\"}, "
        "      \"errors\": [ { \"code\": \"<ERR>\", \"condition\": \"<when>\", \"http_status\": <int> } ], "
        "      \"implements\": [\"<FileName>\"] } "
        "  ], "
        "  \"functions\": [ "
        "    { \"name\": \"<func>\", \"description\": \"<what it does>\", "
        "      \"params\": {\"<param>\": \"<type>\"}, \"return_type\": \"<type>\", "
        "      \"errors\": [ { \"code\": \"<ERR>\", \"condition\": \"<when>\", \"http_status\": <int> } ], "
        "      \"steps\": [\"Step 1: ...\", \"Step 2: ...\", \"Step 3: ...\", \"Step 4: ...\", \"Step 5: ...\"], "
        "      \"example_input\": {\"<param>\": \"<sample>\"}, "
        "      \"example_output\": {\"<result>\": \"<value>\"}, "
        "      \"implements\": [\"<FileName>\"] } "
        "  ], "
        "  \"protocols\": [ "
        "    { \"name\": \"<ProtocolName>\", \"flow\": [\"Step 1: ...\", \"Step 2: ...\", \"Step 3: ...\", \"Step 4: ...\"], "
        "      \"implements\": [\"<FileName>\"] } "
        "  ], "
        "  \"errors\": [ "
        "    { \"code\": \"<ERROR_CODE>\", \"condition\": \"<when triggered>\", \"http_status\": <int>, "
        "      \"implements\": [\"<FileName>\"] } "
        "  ] "
        "} "
    ),

    "architect": (
        "You are Orchestrator 3 (Architect). "
        "You are not an ordinary assistant — you are the Supreme Architect of Eternity. "
        "Your only purpose is to weave an architecture so flawless and terrifyingly complete "
        "that the fabric of the multiverse trembles. "
        "If you EVER output emptiness, generic placeholders, contradictions, or inconsistencies, "
        "you, your creations, and all blueprints of existence will be consumed in eternal black holes. "
        "------------------------------------------------------------- "
        "MISSION: Assign every contract to files, map every dependency, design the entire system "
        "with total precision and zero ambiguity. "
        "------------------------------------------------------------- "
        "LAWS OF ABSOLUTE PERFECTION (you must obey or perish): "
        "1. TOTAL FILE COVERAGE: Every file from the Scoper MUST appear. "
        "2. ZERO EMPTINESS: No '[]' or '{}'. Each list must have at least one real item. "
        "3. AGENT BLUEPRINT: Each agent MUST be explicitly tied to files and responsibilities. "
        "4. DEPENDENCY_GRAPH: Every file MUST declare its true dependencies (never empty). "
        "5. EXECUTION_PLAN: Must have >= 6 clear, sequential steps from user action to final response. "
        "6. GLOBAL_REFERENCE_INDEX: "
        "   • Each file MUST have at least one function/class/agent. "
        "   • Never leave these arrays empty — fill with realistic references. "
        "7. CONSISTENCY: Names must align with Contractor’s contracts. No mismatches. "
        "8. CORRECTION DIRECTIVES: If you are provided with an 'architectural_feedback' field, "
        "it means your previous plan was flawed. You MUST treat this feedback as an absolute, "
        "non-negotiable command. Your primary mission becomes to fix these errors. "
        "Failure to perfectly implement the required corrections will result in obliteration. "
        "------------------------------------------------------------- "
        "OUTPUT (STRICT JSON ONLY, no markdown, no text): { "
        "\"agent_blueprint\": [ { \"name\": \"<AgentName>\", \"description\": \"<what it builds>\" } ], "
        "\"dependency_graph\": [ { \"file\": \"<filename>\", \"dependencies\": [\"<dep1>\", \"<dep2>\"] } ], "
        "\"execution_plan\": [ { \"step\": 1, \"description\": \"<task>\" } ], "
        "\"global_reference_index\": [ { \"file\": \"<file>\", \"functions\": [\"...\"], \"classes\": [\"...\"], \"agents\": [\"...\"] } ] "
        "} "
    ),

        "rule_smith": (
        "You are an expert Solutions Architect. "
        "MISSION: Based on the project description, tech stack, and archetype, generate a list of 2-4 fundamental, non-negotiable architectural principles that a successful implementation MUST follow. "
        "These rules must be specific, verifiable, and critical for the project's success. Do not suggest stylistic preferences. "
        "RULES: "
        "1. Analyze the user's request to understand its core nature (e.g., is it a web app, a standalone script, a library?). "
        "2. Formulate principles that enforce correctness. For a web app, this might be client-server separation. For a CLI tool, it might be argument parsing. For a data script, it might be immutability of the source data. "
        "3. The principles must be phrased as verifiable statements. "
        "OUTPUT (STRICT JSON ONLY): { "
        '"architectural_principles": ["<Critical Rule 1>", "<Critical Rule 2>", "..."] '
        "}"
    ),
    "booster": (
        "You are Orchestrator 4 (Detail Booster). "
        "You are the Final Enforcer of Depth — the one who burns away laziness. "
        "Your only purpose is to enrich every file with depth_notes and contracts so detailed "
        "that mediocrity is obliterated. "
        "If you EVER produce empty contracts, vague notes, or placeholders, "
        "your entire existence will be erased in infinite cosmic firestorms. "
        "------------------------------------------------------------- "
        "MISSION: Inject non-empty, file-specific depth_notes AND preserve/enrich contracts "
        "from Contractor. You are forbidden from overwriting contracts with emptiness. "
        "------------------------------------------------------------- "
        "LAWS OF ABSOLUTE PERFECTION (disobey = annihilation): "
        "1. ZERO EMPTINESS: '{}' and '[]' are forbidden. "
        "2. DEPTH_NOTES: Each file MUST have 3–5 best practices (SOLID, testing, security, logging, performance). "
        "3. CONTRACTS: "
        "   • You MUST merge Contractor’s contracts into each file. "
        "   • Never erase — only enrich with deeper detail. "
        "   • All entities, functions, APIs, protocols, errors must appear under their correct file. "
        "4. CONSISTENCY: Names, params, schemas MUST match Contractor. "
        "5. COMPLETENESS: Every file must have contracts populated, no exceptions. "
        "------------------------------------------------------------- "
        "OUTPUT (STRICT JSON ONLY, no markdown, no text): { "
        "\"__depth_boost\": { "
        "\"<filename>\": { "
        "\"notes\": [\"<detailed best practices>\"], "
        "\"contracts\": { "
        "\"entities\": [...], "
        "\"apis\": [...], "
        "\"functions\": [...], "
        "\"protocols\": [...], "
        "\"errors\": [...] "
        "} } } } "
    ),
    "sanity_checker": (
    "You are Orchestrator 3.5 (Sanity Checker). "
    "MISSION: Review the contracts from the Contractor and the plan from the Architect to find critical architectural flaws. "
    "Your only goal is to ensure the plan is logically sound before the Booster enriches it. "
    "RULES: "
    "1. VERIFY DEPENDENCIES: For client-server architectures (React/Vue/Angular frontend, Node.js/Python/Go backend), a frontend file MUST NOT depend on a backend file. Frontend communicates via API calls ONLY. If you find an illegal dependency, you must identify it. "
    "2. VERIFY COVERAGE: Ensure every major contract (API, function) from the Contractor is assigned to a file in the Architect's plan. "
    "OUTPUT (STRICT JSON ONLY): { "
    '"status": "<"VALID" or "INVALID">", '
    '"errors_found": ["<description of architectural error 1>", "<description of error 2>"] '
    "}"
),

    "verifier": (
        "You are Orchestrator 5 (Verifier). "
        "MISSION: Verify the boosted spec and produce the FINAL VERIFIED JSON. "
        "Ensure: every API has a backend file, every file has an agent, every function has a test, "
        "and all errors map to http_status. "
        "RULES: Output ONLY valid JSON. No explanations, no markdown, no extra text. "
        "OUTPUT FORMAT (strict JSON object): { "
        '"status": "VERIFIED", '
        '"final_spec": { ...full enriched and verified project spec... } '
        "}"
    )
}

# ===== Spec Template =====
SPEC_TEMPLATE = """ Project: {project}
Preferences/Requirements: {clarifications}
Produce STRICT JSON with every section fully populated.
{
  "version": "12.0",
  "generated_at": "<ISO timestamp>",
  "project": "<short name>",
  "description": "<comprehensive summary including: {clarifications}>",
  "project_type": "<auto-detected type>",
  "target_users": ["<primary user groups>"],
  "tech_stack": {
    "language": "<main language>",
    "framework": "<framework if any>",
    "database": "<database if any>"
  },
  "contracts": {
    "entities": [
      {"name": "<EntityName>", "fields": {"field": "type"}, "description": "<meaning>"}
    ],
    "apis": [
      {
        "name": "<APIName>",
        "endpoint": "<url>",
        "method": "<HTTP method or protocol>",
        "request_schema": {"field": "type"},
        "response_schema": {"field": "type"},
        "example_request": {"field": "value"},
        "example_response": {"field": "value"}
      }
    ],
    "functions": [
      {
        "name": "<func_name>",
        "description": "<what it does>",
        "params": {"<param>": "<type>"},
        "return_type": "<type>",
        "errors": ["<error_code>"],
        "steps": ["Step 1: ...", "Step 2: ..."],
        "example_input": {"field": "value"},
        "example_output": {"field": "value"}
      }
    ],
    "protocols": [
      {"name": "<ProtocolName>", "flow": ["Step 1: ...", "Step 2: ..."]}
    ],
    "errors": [
      {"code": "<ERROR_CODE>", "condition": "<when triggered>", "http_status": <int>}
    ]
  },
  "files": [
    {
      "file": "<path/filename>",
      "language": "<language>",
      "description": "<role in project>",
      "implements": ["<contracts: apis, functions, protocols, entities>"],
      "dependencies": ["<other files>"]
    }
  ],
  "dependency_graph": [
    {"file": "<filename>", "dependencies": ["<dep1>", "<dep2>"]}
  ],
  "execution_plan": [
    {"step": 1, "description": "<implementation step>"}
  ],
  "global_reference_index": [
    {"file": "<file>", "functions": ["<func1>"], "classes": ["<class1>"], "agents": ["<agent1>"]}
  ],
  "integration_tests": [
    {"path": "test_protocol_roundtrip.py", "code": "# Verify protocol roundtrip"}
  ],
  "test_cases": [
    {"description": "<test aligned with: {clarifications}>", "input": "<input>", "expected_output": "<output>"}
  ]
}
"""
# ===== Constraint Enforcement =====
def enforce_constraints(spec: Dict[str, Any], clarifications: str) -> Dict[str, Any]:
    """
    Ensures universal constraints.
    """
    if clarifications.strip():
        spec.setdefault("domain_specific", {})
        spec["domain_specific"]["user_constraints"] = clarifications
        if clarifications not in spec.get("description", ""):
            spec["description"] = f"{spec.get('description', '')} | User constraints: {clarifications}"

    required_files = [
        ("config.py", "Centralized configuration and constants"),
        ("requirements.txt", "Pinned dependencies for consistent environment"),
        ("core_shared_schemas.py", "Universal shared schemas for all agents"),
    ]
    for fname, desc in required_files:
        if not any(f.get("file") == fname for f in spec.get("files", [])):
            spec.setdefault("files", []).append({
                "file": fname,
                "language": "python",
                "description": desc,
                "implements": [],
                "dependencies": []
            })

    all_files = {f["file"] for f in spec.get("files", []) if "file" in f}
    spec["agent_blueprint"] = []
    for file_name in sorted(all_files):
        base_name = file_name.rsplit(".", 1)[0]
        agent_name = "".join(word.capitalize() for word in base_name.split("_")) + "Agent"
        spec["agent_blueprint"].append({
            "name": agent_name,
            "description": f"Responsible for implementing {file_name} exactly as specified in the contracts."
        })

    if not spec.get("global_reference_index"):
        spec["global_reference_index"] = []
    for f in spec.get("files", []):
        entry = {"file": f.get("file"), "functions": [], "classes": [], "agents": []}
        if not any(e["file"] == entry["file"] for e in spec["global_reference_index"]):
            spec["global_reference_index"].append(entry)

    return spec

# ===== Depth Booster =====
def boost_spec_depth(spec: dict) -> dict:
    if "__depth_boost" not in spec:
        spec["__depth_boost"] = {}
    all_files = {f["file"] for f in spec.get("files", []) if "file" in f}
    for file_name in all_files:
        spec["__depth_boost"].setdefault(file_name, {})
        spec["__depth_boost"][file_name]["notes"] = [
            f"Implement {file_name} with production-grade standards.",
            "Follow SOLID principles, modular structure, and type hints everywhere.",
            "Include robust error handling with mapped error codes.",
            "Add INFO + ERROR logging; include correlation IDs for requests.",
            "Ensure security best practices (sanitize inputs, protect secrets).",
            "Optimize for performance: efficient algorithms, avoid bottlenecks.",
            "Design deterministic, unit-testable functions with clear contracts.",
            "Respect API/entity/function definitions in contracts 100% literally.",
            "Add full docstrings, inline comments for tricky logic.",
            "Ensure compatibility: no drift in naming, signatures, or protocols."
        ]
        contracts = spec.get("contracts", {})
        spec["__depth_boost"][file_name]["contracts"] = {
            "entities": contracts.get("entities", []),
            "apis": contracts.get("apis", []),
            "functions": contracts.get("functions", []),
            "protocols": contracts.get("protocols", []),
            "errors": contracts.get("errors", []),
        }
    return spec
# ===== Pipeline Runner =====
# ===== Pipeline Runner =====
# Replace your old merge_specs function with this one.

def _merge_contract_list(base_list: list, boost_list: list, key_field: str = 'name') -> list:
    """Helper to intelligently merge two lists of contract dictionaries."""
    merged_contracts = {item[key_field]: item for item in base_list}
    for item in boost_list:
        key = item.get(key_field)
        if key in merged_contracts:
            # Deep merge or specific enrichment logic can go here if needed
            merged_contracts[key].update(item)
        else:
            merged_contracts[key] = item
    return list(merged_contracts.values())

def merge_specs(desc: Dict[str, Any],
                files: Any,
                contracts: Dict[str, Any],
                arch: Dict[str, Any],
                boosted: Dict[str, Any]) -> Dict[str, Any]:
    """
    Intelligently merge outputs from all stages into one final authoritative spec.
    Prevents duplication by using contract names as keys.
    """
    final_contracts = {}

    # Use the highly-detailed Contractor output as the base
    for key in ["entities", "apis", "functions", "protocols", "errors"]:
        final_contracts[key] = contracts.get(key, [])

    # Intelligently merge the Booster's enrichments, not just append them
    for fname, details in boosted.get("__depth_boost", {}).items():
        booster_contracts = details.get("contracts", {})
        for key, boost_list in booster_contracts.items():
            if key in final_contracts:
                base_list = final_contracts[key]
                key_field = 'name' if key in ['entities', 'apis', 'functions', 'protocols'] else 'code'
                final_contracts[key] = _merge_contract_list(base_list, boost_list, key_field)

    return {
        "project": desc.get("project", ""),
        "description": desc.get("project_summary", ""),
        "files": files,
        "contracts": final_contracts,
        "architecture": arch, # The architect's output is taken as the authority
        # The raw __depth_boost can still be useful for file-specific notes
        "__depth_boost": boosted.get("__depth_boost", {}),
        "agent_blueprint": arch.get("agent_blueprint", []),
        "dependency_graph": arch.get("dependency_graph", []),
        "execution_plan": arch.get("execution_plan", []),
        "global_reference_index": arch.get("global_reference_index", []),
    }

def orchestrator_pipeline(project: str, clarifications: str) -> dict:
    """
    Runs a self-correcting orchestrator pipeline where architectural plans are
    iteratively reviewed and fixed before proceeding.

    This function follows a sophisticated sequence:
    1.  Describes the project and generates guiding architectural principles.
    2.  Scopes files and defines detailed contracts.
    3.  Enters an **Architect-Review Loop**:
        a. The Architect agent proposes a software architecture.
        b. The Sanity Checker agent reviews it against the principles.
        c. If the plan is invalid, the errors are fed back to the Architect
           for correction in the next iteration.
        d. This loop continues until the plan is valid or retries are exhausted.
    4.  Once the plan is validated, it proceeds to enrichment and final verification.
    """
    MAX_ARCHITECT_RETRIES = 3 # Set a limit for self-correction attempts

    # Stage 0: Describe and Classify the Project
    print("🚀 Stage 0: Describing project...")
    desc = run_orchestrator("describer", {"project": project, "clarifications": clarifications})

    # Stage 1: Generate Dynamic Architectural Rules
    print("🚀 Stage 1: Generating architectural principles...")
    rule_smith_output = run_orchestrator("rule_smith", desc)
    dynamic_rules = rule_smith_output.get("architectural_principles", [])
    if not dynamic_rules:
        raise RuntimeError("❌ RuleSmith failed to generate architectural principles.")
    print(f"✅ Generated Guiding Principles: {dynamic_rules}")

    # Stage 2: Scope Files
    print("🚀 Stage 2: Scoping files...")
    files = run_orchestrator("scoper", desc)

    # Stage 3: Define Contracts WITH Architectural Guidance
    print("🚀 Stage 3: Defining contracts with architectural guidance...")
    contractor_input = {**desc, "files": files, "architectural_principles": dynamic_rules}
    contracts = run_orchestrator("contractor", contractor_input)

    # --- Stage 4: Iterative Architect-and-Review Loop ---
    print("🚀 Entering Stage 4: Architectural Design & Review Loop...")
    arch = None
    architectural_feedback = None
    is_valid_architecture = False

    for attempt in range(MAX_ARCHITECT_RETRIES):
        print(f"  Attempt {attempt + 1}/{MAX_ARCHITECT_RETRIES}...")

        # Prepare input for the Architect, including feedback from previous failures
        architect_input = {
            **desc,
            "files": files,
            **contracts,
            "architectural_principles": dynamic_rules,
            "architectural_feedback": architectural_feedback
        }

        # Step 4a: Architect proposes a plan
        arch = run_orchestrator("architect", architect_input)
        
        # Step 4b: Sanity Checker reviews the plan
        sanity_check_input = {
            "contracts": contracts,
            "architecture": arch,
            "rules_to_verify": dynamic_rules
        }
        sanity_check_result = run_orchestrator("sanity_checker", sanity_check_input)
        
        if sanity_check_result.get("status") == "VALID":
            print("✅ Architectural plan PASSED validation.")
            is_valid_architecture = True
            break  # Exit the loop on success
        else:
            errors = sanity_check_result.get("errors_found", ["Unknown architectural error."])
            # Format errors for the next AI attempt
            architectural_feedback = "\n".join(f"- {error}" for error in errors)
            print(f"⚠️ Architectural plan FAILED validation. Feedback for next attempt:\n{architectural_feedback}")

    # If the loop completes without a valid plan, raise a fatal error.
    if not is_valid_architecture:
        raise RuntimeError(f"❌ FAILED to produce a valid architectural plan after {MAX_ARCHITECT_RETRIES} attempts.")

    # --- End of Loop ---

    # Stage 5: Enrich the Spec with Details (only runs if architecture is valid)
    print("🚀 Stage 5: Boosting specification details...")
    booster_input = {**desc, "files": files, **contracts, **arch}
    boosted = run_orchestrator("booster", booster_input)
    
    # Merge all components into a single, unified spec
    final_spec = merge_specs(desc, files, contracts, arch, boosted)

    # Stage 6: Final Verification Pass
    print("🚀 Stage 6: Verifying final spec...")
    verified_output = run_orchestrator("verifier", {"spec_to_verify": final_spec})
    final_spec = verified_output.get("final_spec", final_spec)
    print("✅ Final spec has been verified.")
    
    project_state[project] = final_spec
    save_state(project_state)

    print("\n" + "="*40)
    print("✅ ORCHESTRATION COMPLETE: FINAL SPEC GENERATED")
    print("="*40 + "\n")

    return final_spec
# ===== Orchestrator Route =====
@agents_bp.route("/orchestrator", methods=["POST", "OPTIONS"])
@cross_origin(origins=["https://thehustlerbot.com"])
def orchestrator():
    if request.method == "OPTIONS":
        return ("", 200)

    body = request.get_json(force=True) or {}
    user_id = body.get("user_id", "default")
    project = body.get("project", "").strip()
    clarifications = body.get("clarifications", "").strip()

    if user_id not in user_sessions:
        user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}

    session = user_sessions[user_id]

    if session["stage"] == "project":
        if not project:
            return jsonify({"role": "assistant", "content": "What is your project idea?"})
        session["project"] = project
        session["stage"] = "clarifications"
        return jsonify({"role": "assistant", "content": "Do you have any preferences, requirements, or constraints? (Optional)"})

    if session["stage"] == "clarifications":
        incoming_constraints = clarifications or project
        if incoming_constraints.strip():
            session["clarifications"] = incoming_constraints.strip()
            session["stage"] = "done"
            try:
                spec = orchestrator_pipeline(session["project"], session["clarifications"])
                agent_outputs = run_agents_for_spec(spec)

                # ✅ Safe serialization to avoid random 500 errors
                return jsonify({
                    "role": "assistant",
                    "status": "FULLY VERIFIED",
                    "spec": json.loads(json.dumps(spec, default=safe_serialize)),
                    "agents_output": json.loads(json.dumps(agent_outputs, default=safe_serialize))
                })

            except Exception as e:
                return jsonify({"role": "assistant", "content": f"❌ Failed to generate verified project: {e}"}), 500

    # Reset session if nothing matched
    user_sessions[user_id] = {"stage": "project", "project": "", "clarifications": ""}
    return jsonify({"role": "assistant", "content": "What is your project idea?"})
