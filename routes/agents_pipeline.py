# routes/agents_pipeline.py

from flask import Blueprint, request, jsonify
import os
import json
import openai

agents_pipeline_bp = Blueprint("agents_pipeline", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")


# ===== Extract Files from Orchestrator Spec =====
def get_agent_files(spec):
    files = set()

    # From interface stub files
    for f in spec.get("interface_stub_files", []):
        files.add(f["file"])

    # From agent blueprint
    for agent in spec.get("agent_blueprint", []):
        desc = agent.get("description", "")
        if "implementing" in desc:
            part = desc.split("implementing", 1)[1].strip().split(" ")[0]
            if part.endswith(".py") or "." in part:
                files.add(part)

    # From function contracts
    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if "file" in func:
            files.add(func["file"])

    # From dependency graph
    for dep in spec.get("dependency_graph", []):
        if "file" in dep:
            files.add(dep["file"])
        for d in dep.get("dependencies", []):
            files.add(d)

    # From global reference index
    for ref in spec.get("global_reference_index", []):
        if "file" in ref:
            files.add(ref["file"])

    return sorted(files)

def extract_file_spec(spec, file_name):
    """
    Extract details relevant to the given file so the coding agent
    gets ALL deep implementation notes from the orchestrator, including
    pseudocode, DB/API/protocol links, and compatibility rules.
    This version always enriches with depth boost content.
    """
    file_spec = {
        "file_name": file_name,
        "functions": [],
        "db_tables": [],
        "api_endpoints": [],
        "protocols": [],
        "shared_schemas": spec.get("shared_schemas"),
        "config_and_constants": None,
        "compatibility_notes": []
    }

    # Functions for this file
    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if func.get("file") == file_name:
            file_spec["functions"].append(func)

    # DB tables
    for table in spec.get("db_schema", []):
        for col in table.get("columns", []):
            if "db" in file_name.lower() or any(
                table["table"] in json.dumps(func) for func in file_spec["functions"]
            ):
                if table not in file_spec["db_tables"]:
                    file_spec["db_tables"].append(table)

    # API endpoints
    for api in spec.get("api_contracts", []):
        for func in file_spec["functions"]:
            if func.get("name") in json.dumps(api):
                file_spec["api_endpoints"].append(api)

    # Protocols
    for proto in spec.get("inter_agent_protocols", []):
        if file_name in json.dumps(proto):
            file_spec["protocols"].append(proto)
        else:
            for func in file_spec["functions"]:
                if func.get("name") in json.dumps(proto):
                    file_spec["protocols"].append(proto)
                    break

    # Config reference
    for f in spec.get("interface_stub_files", []):
        if f["file"] == "config.py":
            file_spec["config_and_constants"] = f

    # Always merge deep compatibility notes from __depth_boost or generate defaults
    depth_info = spec.get("__depth_boost", {}).get(file_name, {})
    file_spec["compatibility_notes"].extend(depth_info.get("notes", []))
    file_spec["db_tables"].extend(depth_info.get("db", []))
    file_spec["api_endpoints"].extend(depth_info.get("api", []))
    file_spec["protocols"].extend(depth_info.get("protocols", []))

    return file_spec


def run_agents_for_spec(spec):
    files = get_agent_files(spec)
    outputs = []

    for file_name in files:
        file_spec = extract_file_spec(spec, file_name)

        agent_prompt = (
            f"You are a world-class coding agent assigned to implement ONLY the file: {file_name}\n\n"
            f"Follow these ABSOLUTE RULES:\n"
            f"1. Implement EXACTLY what is described — no features beyond spec.\n"
            f"2. Follow ALL pseudocode steps and edge cases provided.\n"
            f"3. Maintain strict compatibility with dependent files as per dependency_graph.\n"
            f"4. Use only constants/configs from config.py; never hardcode values.\n"
            f"5. Use imports exactly as described; import shared items from core_shared_schemas.py.\n"
            f"6. Produce fully working, production-ready code — no placeholders, no TODOs.\n"
            f"7. Output ONLY valid Python code for this file, nothing else.\n"
            f"8. Implement comprehensive error handling, logging, and unit-testable design.\n\n"
            f"FILE-SPECIFIC IMPLEMENTATION DETAILS (full depth from orchestrator):\n"
            f"{json.dumps(file_spec, indent=2)}"
        )

        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a coding agent that outputs only complete, fully compatible code for your assigned file."},
                {"role": "user", "content": agent_prompt}
            ]
        )

        outputs.append({
            "file": file_name,
            "code": resp.choices[0].message["content"]
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
