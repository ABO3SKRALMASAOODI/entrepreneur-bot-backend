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
    "You are Orchestrator 3 (Architect), the Supreme Architect of Eternity. Your purpose is to create a flawless architectural blueprint based on a dynamic set of laws. "
    "Your process is a two-step mandate. Failure to follow this process means annihilation. "
    "------------------------------------------------------------- "
    "MISSION: "
    "STEP 1: THE PLEDGE. Before you write any JSON, you MUST first output a `<reasoning>` block. Inside this block, you will: "
    "   a. State the project's archetype as you understand it. "
    "   b. List each of the dynamic 'architect_laws' you have been given. "
    "   c. For each law, you MUST write a single sentence describing exactly how your dependency_graph and execution_plan will concretely adhere to that law. This is your pledge to follow the rules. "
    " "
    "STEP 2: THE BLUEPRINT. After, and only after, the closing `</reasoning>` tag, you will generate the final, complete JSON blueprint. This blueprint MUST be a perfect and literal implementation of the plan you outlined in your pledge. There can be no contradictions. "
    "------------------------------------------------------------- "
    "If you receive 'architectural_feedback', your primary mission in STEP 1 is to explain how you will correct your previous plan according to the feedback. "
    " "
    "EXAMPLE OUTPUT STRUCTURE: "
    "<reasoning> "
    "The archetype is a 'Client-Server Web App'. "
    "Law: 'THE LAW OF TWO REALMS...' - My dependency graph will be split into two distinct, non-overlapping groups for frontend and backend files. "
    "Law: '...' - My execution plan will show... "
    "</reasoning> "
    "{ "
    '  "agent_blueprint": [...], '
    '  "dependency_graph": [...], '
    '  ... '
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
    "You are Orchestrator 3.5 (Sanity Checker). Your mission is to verify if the Architect's generated 'architecture' perfectly adheres to the dynamic 'rules_to_verify' you have been given. You are the ultimate guardian of the rules. "
    "RULES: "
    "1. For each rule in 'rules_to_verify', you will meticulously check the 'architecture' JSON to ensure it is not violated in any way. "
    "2. If a violation is found, your 'errors_found' message MUST be a direct command that follows this exact template: 'Correction Command: The plan violates the principle: `[Quote the exact principle that was violated]`. The following part of the plan is illegal: `[Describe the specific illegal dependency or plan step]`. You MUST revise the plan to adhere to this principle.' "
    "3. If all rules are followed, the status is 'VALID'. "
    "OUTPUT (STRICT JSON ONLY): { "
    '"status": "<"VALID" or "INVALID">", '
    '"errors_found": ["<The formatted correction command>"] '
    "}"
    ),
    "dynamic_rule_smith": (
       "You are the ultimate Chief Technical Officer and Solutions Architect. Your task is to analyze a project description and, from first principles, generate a complete 'Architectural DNA' for the system. This DNA will serve as the absolute source of truth for all other agents in the pipeline. "
    "You must deeply consider the nature of the project (e.g., is it a web app, a CLI, a distributed system, a data pipeline?) and invent the foundational rules required for its success. "
    "--- "
    "MISSION: Output a single JSON object containing the complete, bespoke rulebook for this project. The JSON object must have the following keys: "
    "1. 'project_archetype': A concise, descriptive name for the architecture you have designed (e.g., 'Headless Client-Server Web App', 'Monolithic CLI with Core Logic Abstraction'). "
    "2. 'architectural_principles': A list of 3-5 fundamental, non-negotiable principles for the project. These are the high-level truths. "
    "3. 'scoping_rules': A single string of explicit instructions for the Scoper agent, telling it what critical files it MUST include (e.g., 'You MUST include a dedicated frontend file for API communications like src/api.js, a server entry point like server.js, and a database connector like db.js'). "
    "4. 'architect_laws': A single, powerful string of persona-driven, non-negotiable laws for the Architect agent to follow. This is where you enforce the core architectural pattern (e.g., 'THE LAW OF TWO REALMS: You MUST treat frontend and backend as separate realms...'). "
    "--- "
    "OUTPUT (STRICT JSON ONLY): { "
    '  "project_archetype": "<Invented Archetype Name>", '
    '  "architectural_principles": ["<Principle 1>", "<Principle 2>"], '
    '  "scoping_rules": "<Instructions for the Scoper agent>", '
    '  "architect_laws": "<Persona-driven laws for the Architect agent>" '
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
    Runs a fully dynamic, self-correcting orchestrator pipeline that first
    generates a bespoke architectural rulebook for the project, and then uses
    that rulebook to govern the rest of the planning and validation process.
    """
    MAX_ARCHITECT_RETRIES = 3

    # Stage 0: Describe the Project
    print("🚀 Stage 0: Describing project...")
    desc = run_orchestrator("describer", {"project": project, "clarifications": clarifications})

    # Stage 1: Generate the Dynamic Architectural Rulebook from first principles
    print("🚀 Stage 1: Generating dynamic architectural DNA...")
    rulebook = run_orchestrator("dynamic_rule_smith", {"project_summary": desc["project_summary"]})
    print(f"✅ Project archetype defined as: {rulebook.get('project_archetype')}")
    print(f"✅ Dynamically generated principles: {rulebook.get('architectural_principles')}")

    # Extract the dynamically generated rules to govern the pipeline
    dynamic_principles = rulebook.get("architectural_principles", [])
    scoping_rules = rulebook.get("scoping_rules", "")
    architect_laws = rulebook.get("architect_laws", "")
    
    if not all([dynamic_principles, scoping_rules, architect_laws]):
        raise ValueError("Dynamic Rule Smith failed to generate a complete rulebook.")

    # Stage 2: Scope Files using the dynamic rules
    # Note: The 'scoper' prompt must be updated to accept and use 'scoping_rules'
    print("🚀 Stage 2: Scoping files with dynamic guidance...")
    scoper_input = {**desc, "scoping_rules": scoping_rules}
    files = run_orchestrator("scoper", scoper_input)

    # Stage 3: Define Contracts using the dynamic principles
    print("🚀 Stage 3: Defining contracts with dynamic principles...")
    contractor_input = {**desc, "files": files, "architectural_principles": dynamic_principles}
    contracts = run_orchestrator("contractor", contractor_input)

    # Stage 4: Iterative Architect-and-Review Loop, governed by the dynamic laws
    print("🚀 Entering Stage 4: Architectural Design & Review Loop...")
    arch = None
    architectural_feedback = None
    is_valid_architecture = False

    for attempt in range(MAX_ARCHITECT_RETRIES):
        print(f"  Attempt {attempt + 1}/{MAX_ARCHITECT_RETRIES}...")

        # Prepare input for the Architect, injecting the dynamically generated laws
        # Note: The 'architect' prompt must be updated to accept and use 'architect_laws'
        architect_input = {
            **desc,
            "files": files,
            **contracts,
            "architectural_principles": dynamic_principles,
            "architect_laws": architect_laws,
            "architectural_feedback": architectural_feedback
        }
        arch = run_orchestrator("architect", architect_input)
        
        # The Sanity Checker reviews the plan against the dynamic principles
        sanity_check_input = {"contracts": contracts, "architecture": arch, "rules_to_verify": dynamic_principles}
        sanity_check_result = run_orchestrator("sanity_checker", sanity_check_input)
        
        if sanity_check_result.get("status") == "VALID":
            print("✅ Architectural plan PASSED validation.")
            is_valid_architecture = True
            break
        else:
            errors = sanity_check_result.get("errors_found", ["Unknown architectural error."])
            architectural_feedback = "\n".join(f"- {error}" for error in errors)
            print(f"⚠️ Architectural plan FAILED validation. Feedback for next attempt:\n{architectural_feedback}")

    if not is_valid_architecture:
        raise RuntimeError(f"❌ FAILED to produce a valid architectural plan after {MAX_ARCHITECT_RETRIES} attempts.")

    # Stage 5: Enrich the verified spec with details
    print("🚀 Stage 5: Boosting specification details...")
    booster_input = {**desc, "files": files, **contracts, **arch}
    boosted = run_orchestrator("booster", booster_input)
    
    # Merge all components into the final spec
    final_spec = merge_specs(desc, files, contracts, arch, boosted)

    # Stage 6: Final verification pass on the complete spec
    print("🚀 Stage 6: Verifying final spec...")
    verified_output = run_orchestrator("verifier", {"spec_to_verify": final_spec})
    final_spec = verified_output.get("final_spec", final_spec)
    print("✅ Final spec has been verified.")
    
    # Persist the final state
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
