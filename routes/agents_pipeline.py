# routes/agents_pipeline.py

from flask import Blueprint, request, jsonify
import os
import json
import re
import openai

agents_pipeline_bp = Blueprint("agents_pipeline", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")


# ===== Extract Files from Orchestrator Spec =====
def get_agent_files(spec):
    files = set()

    for f in spec.get("interface_stub_files", []):
        files.add(f["file"])

    for agent in spec.get("agent_blueprint", []):
        desc = agent.get("description", "")
        for word in desc.split():
            if "." in word and word.endswith(".py"):
                files.add(word.strip())

    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if "file" in func:
            files.add(func["file"])

    for dep in spec.get("dependency_graph", []):
        if "file" in dep:
            files.add(dep["file"])
        for d in dep.get("dependencies", []):
            files.add(d)

    for ref in spec.get("global_reference_index", []):
        if "file" in ref:
            files.add(ref["file"])

    return sorted(files)


# ===== Extract Relevant Details for a Single File =====
def extract_file_spec(spec, file_name):
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

    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if func.get("file") == file_name:
            file_spec["functions"].append(func)

    for table in spec.get("db_schema", []):
        if "db" in file_name.lower() or any(table["table"] in json.dumps(func) for func in file_spec["functions"]):
            file_spec["db_tables"].append(table)

    for api in spec.get("api_contracts", []):
        if file_name in json.dumps(api) or any(func.get("name") in json.dumps(api) for func in file_spec["functions"]):
            file_spec["api_endpoints"].append(api)

    for proto in spec.get("inter_agent_protocols", []):
        if file_name in json.dumps(proto) or any(func.get("name") in json.dumps(proto) for func in file_spec["functions"]):
            file_spec["protocols"].append(proto)

    for f in spec.get("interface_stub_files", []):
        if f["file"] == "config.py":
            file_spec["config_and_constants"] = f

    return file_spec


# ===== Output Validation =====
def validate_generated_code(file_name, file_spec, code, spec):
    """
    Returns (bool, errors_list) where bool indicates pass/fail.
    """

    errors = []
    required_funcs = [f["name"] for f in file_spec["functions"]]

    # Check all required functions exist
    for func in required_funcs:
        if not re.search(rf"def\s+{func}\s*\(", code):
            errors.append(f"Missing required function: {func}")

    # Check for unexpected functions
    defined_funcs = re.findall(r"def\s+([a-zA-Z_]\w*)\s*\(", code)
    for df in defined_funcs:
        if df not in required_funcs and required_funcs:
            errors.append(f"Extra unexpected function: {df}")

    # Check imports match dependency graph
    allowed_imports = []
    for dep in spec.get("dependency_graph", []):
        if dep.get("file") == file_name:
            allowed_imports.extend(dep.get("dependencies", []))
    for imp in re.findall(r"from\s+([\w\.]+)\s+import", code):
        if not any(dep_file.replace(".py", "") in imp for dep_file in allowed_imports):
            errors.append(f"Invalid import: {imp}")

    # Config constants must be imported, not hardcoded
    if "config.py" in [d for dep in spec.get("dependency_graph", []) if dep.get("file") == file_name]:
        if re.search(r"=\s*['\"]\w+['\"]", code):
            errors.append("Hardcoded string constant found instead of config import")

    # Special case: requirements.txt should have only packages
    if file_name == "requirements.txt":
        lines = [l.strip() for l in code.splitlines() if l.strip()]
        for l in lines:
            if l.endswith(".py"):
                errors.append("requirements.txt contains file name instead of package")

    return (len(errors) == 0, errors)


# ===== Spawn Agents for Each File =====
def run_agents_for_spec(spec):
    files = get_agent_files(spec)
    outputs = []

    for file_name in files:
        file_spec = extract_file_spec(spec, file_name)

        agent_prompt = f"""
You are a coding agent assigned to implement ONLY the file: {file_name}

Rules:
1. Implement EXACTLY what is described in file_spec — no extra features.
2. If you need logic from another file, import it exactly as per dependency_graph — never reimplement.
3. Follow function signatures, parameters, return types, and pseudocode steps exactly.
4. All constants & configs must be imported from config.py — never hardcode.
5. Output only raw code — no markdown, no explanations.
6. Do not implement other files' logic.

=== FILE SPEC ===
{json.dumps(file_spec, indent=2)}

=== CROSS-FILE CONTEXT ===
Data Dictionary: {json.dumps(spec.get("data_dictionary", []), indent=2)}
Database Schema: {json.dumps(spec.get("db_schema", []), indent=2)}
API Contracts: {json.dumps(spec.get("api_contracts", []), indent=2)}
Inter-Agent Protocols: {json.dumps(spec.get("inter_agent_protocols", []), indent=2)}
Errors Module: {json.dumps(spec.get("errors_module", {}), indent=2)}
"""

        retries = 0
        while retries < 2:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                temperature=0.0,
                messages=[
                    {"role": "system", "content": "You output only the complete, correct code for the assigned file."},
                    {"role": "user", "content": agent_prompt}
                ]
            )
            code_output = resp.choices[0].message["content"].strip()

            valid, errs = validate_generated_code(file_name, file_spec, code_output, spec)
            if valid:
                outputs.append({"file": file_name, "code": code_output})
                break
            else:
                agent_prompt += f"\n\nYour last output failed validation for: {errs}. Regenerate correctly."
                retries += 1
        else:
            outputs.append({"file": file_name, "code": f"❌ Failed after retries. Last errors: {errs}"})

    return outputs


# ===== Flask Route =====
@agents_pipeline_bp.route("/run_agents", methods=["POST"])
def run_agents_endpoint():
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
