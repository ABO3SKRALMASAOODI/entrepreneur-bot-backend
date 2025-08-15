# routes/agents_pipeline.py

from flask import Blueprint, request, jsonify
import os
import json
import openai

agents_pipeline_bp = Blueprint("agents_pipeline", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ===== Extract Files from Orchestrator Spec =====
def get_agent_files(spec):
    """
    Determine which files need to be implemented by agents.
    Uses multiple sections of the spec to ensure full coverage.
    """
    files = set()

    # Interface stub files
    for f in spec.get("interface_stub_files", []):
        files.add(f["file"])

    # Agent blueprint descriptions
    for agent in spec.get("agent_blueprint", []):
        desc = agent.get("description", "")
        for word in desc.split():
            if "." in word and word.endswith(".py"):
                files.add(word.strip())

    # Function contracts
    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if "file" in func:
            files.add(func["file"])

    # Dependency graph
    for dep in spec.get("dependency_graph", []):
        if "file" in dep:
            files.add(dep["file"])
        for d in dep.get("dependencies", []):
            files.add(d)

    # Global reference index
    for ref in spec.get("global_reference_index", []):
        if "file" in ref:
            files.add(ref["file"])

    return sorted(files)


# ===== Extract Relevant Details for a Single File =====
def extract_file_spec(spec, file_name):
    """
    Pull only the details needed for the agent implementing file_name,
    plus relevant cross-file context so the agent never guesses.
    """
    file_spec = {
        "file_name": file_name,
        "functions": [],
        "db_tables": [],
        "api_endpoints": [],
        "protocols": [],
        "errors_module": spec.get("errors_module"),
        "shared_schemas": spec.get("shared_schemas"),
        "config_and_constants": None,
        "global_naming_contract": spec.get("global_naming_contract", {}),
        "dependency_graph": spec.get("dependency_graph", []),
    }

    # Functions for this file
    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if func.get("file") == file_name:
            file_spec["functions"].append(func)

    # DB tables touched by this file
    for table in spec.get("db_schema", []):
        if "db" in file_name.lower() or any(table["table"] in json.dumps(func) for func in file_spec["functions"]):
            file_spec["db_tables"].append(table)

    # API endpoints relevant to this file
    for api in spec.get("api_contracts", []):
        if file_name in json.dumps(api) or any(func.get("name") in json.dumps(api) for func in file_spec["functions"]):
            file_spec["api_endpoints"].append(api)

    # Inter-agent protocols relevant to this file
    for proto in spec.get("inter_agent_protocols", []):
        if file_name in json.dumps(proto) or any(func.get("name") in json.dumps(proto) for func in file_spec["functions"]):
            file_spec["protocols"].append(proto)

    # Config & constants
    for f in spec.get("interface_stub_files", []):
        if f["file"] == "config.py":
            file_spec["config_and_constants"] = f

    return file_spec


# ===== Spawn Agents for Each File =====
def run_agents_for_spec(spec):
    """
    Executes one coding agent per file in the spec.
    Returns a list of {file, code}.
    """
    files = get_agent_files(spec)
    outputs = []

    for file_name in files:
        file_spec = extract_file_spec(spec, file_name)

        # Build the strictest possible prompt
        agent_prompt = f"""
You are a coding agent assigned to implement ONLY the file: {file_name}

Follow these rules with ZERO deviation:
1. Implement EXACTLY as described in the given file_spec.
2. Use the function signatures, parameters, return types, and pseudocode steps from file_spec — word for word.
3. Do NOT invent logic, rename anything, or skip any step.
4. All constants & configs come from config.py — never hardcode.
5. Imports must match the exact files/names in dependency_graph.
6. Output only fully working, production-ready Python code — no placeholders, no TODOs.
7. Do not include any comments unless explicitly stated in file_spec.
8. The output must be only raw Python code — no markdown fences, no explanations.

=== FILE SPEC ===
{json.dumps(file_spec, indent=2)}

=== CROSS-FILE CONTEXT ===
Data Dictionary: {json.dumps(spec.get("data_dictionary", []), indent=2)}
Database Schema: {json.dumps(spec.get("db_schema", []), indent=2)}
API Contracts: {json.dumps(spec.get("api_contracts", []), indent=2)}
Inter-Agent Protocols: {json.dumps(spec.get("inter_agent_protocols", []), indent=2)}
Errors Module: {json.dumps(spec.get("errors_module", {}), indent=2)}
Shared Schemas: {spec.get("shared_schemas", "")}
"""

        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                temperature=0.0,
                messages=[
                    {"role": "system", "content": "You are a coding agent that outputs only the complete code for your assigned file."},
                    {"role": "user", "content": agent_prompt}
                ]
            )

            outputs.append({
                "file": file_name,
                "code": resp.choices[0].message["content"].strip()
            })

        except Exception as e:
            outputs.append({
                "file": file_name,
                "code": f"❌ Agent failed: {e}"
            })

    return outputs


# ===== Flask Route to Run Agents =====
@agents_pipeline_bp.route("/run_agents", methods=["POST"])
def run_agents_endpoint():
    """
    Expects JSON:
    {
        "spec": { ... }  # full orchestrator output
    }
    """
    body = request.get_json(force=True) or {}
    spec = body.get("spec")
    if not spec:
        return jsonify({"error": "Missing spec"}), 400

    try:
        agent_outputs = run_agents_for_spec(spec)
        return jsonify({
            "role": "assistant",
            "agents_output": agent_outputs
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
