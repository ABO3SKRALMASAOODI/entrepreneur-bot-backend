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

    # From agent blueprint descriptions (may have split files)
    for agent in spec.get("agent_blueprint", []):
        # Try to find explicit file name in description
        desc = agent.get("description", "")
        if "implementing" in desc:
            # e.g. "Responsible for implementing blockchain_service_part1.py exactly..."
            part = desc.split("implementing", 1)[1].strip().split(" ")[0]
            if part.endswith(".py") or "." in part:
                files.add(part)

    # From function contract manifest
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


# ===== Spawn Agents for Each File =====
def run_agents_for_spec(spec):
    files = get_agent_files(spec)
    outputs = []

    for file_name in files:
        agent_prompt = (
            f"PART: {file_name}\n"
            f"STRICT INSTRUCTIONS:\n"
            f"1. Implement exactly what is required for {file_name}.\n"
            f"2. Use only the details from the orchestrator spec.\n"
            f"3. Do not modify other files or define things outside this file.\n"
            f"4. Follow naming conventions and imports exactly.\n"
            f"5. Only output valid code for this file, nothing else.\n\n"
            f"FULL PROJECT SPEC:\n{json.dumps(spec, indent=2)}"
        )

        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a coding agent that outputs only the full code for your assigned file."},
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
