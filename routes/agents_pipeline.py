# routes/agents_pipeline.py

from flask import Blueprint, request, jsonify
import os
import json
import tempfile
import shutil
import subprocess
import importlib.util
import openai

agents_pipeline_bp = Blueprint("agents_pipeline", __name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

MAX_RETRIES = 3

# -------------------------------
# 1. Utility Functions
# -------------------------------

def get_agent_files(spec):
    """Extract all file names from orchestrator spec."""
    files = set()

    for f in spec.get("interface_stub_files", []):
        if "file" in f:
            files.add(f["file"])

    for agent in spec.get("agent_blueprint", []):
        desc = agent.get("description", "")
        if "implementing" in desc:
            part = desc.split("implementing", 1)[1].strip().split(" ")[0]
            if "." in part:
                files.add(part)

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


def extract_file_spec(spec, file_name):
    """Extract relevant part of spec for a single file."""
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

    for func in spec.get("function_contract_manifest", {}).get("functions", []):
        if func.get("file") == file_name:
            file_spec["functions"].append(func)

    for table in spec.get("db_schema", []):
        if "db" in file_name.lower() or any(
            table["table"] in json.dumps(func) for func in file_spec["functions"]
        ):
            if table not in file_spec["db_tables"]:
                file_spec["db_tables"].append(table)

    for api in spec.get("api_contracts", []):
        for func in file_spec["functions"]:
            if func.get("name") in json.dumps(api):
                file_spec["api_endpoints"].append(api)

    for proto in spec.get("inter_agent_protocols", []):
        if file_name in json.dumps(proto):
            file_spec["protocols"].append(proto)
        else:
            for func in file_spec["functions"]:
                if func.get("name") in json.dumps(proto):
                    file_spec["protocols"].append(proto)
                    break

    for f in spec.get("interface_stub_files", []):
        if f["file"] == "config.py":
            file_spec["config_and_constants"] = f

    depth_info = spec.get("__depth_boost", {}).get(file_name, {})
    file_spec["compatibility_notes"].extend(depth_info.get("notes", []))
    file_spec["db_tables"].extend(depth_info.get("db", []))
    file_spec["api_endpoints"].extend(depth_info.get("api", []))
    file_spec["protocols"].extend(depth_info.get("protocols", []))

    return file_spec


def verify_imports(outputs):
    """Ensure generated code imports without syntax errors."""
    tmp_dir = tempfile.mkdtemp()
    try:
        for output in outputs:
            file_path = os.path.join(tmp_dir, output["file"])
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(output["code"])

        for output in outputs:
            file_path = os.path.join(tmp_dir, output["file"])
            spec_obj = importlib.util.spec_from_file_location("module.name", file_path)
            try:
                mod = importlib.util.module_from_spec(spec_obj)
                spec_obj.loader.exec_module(mod)
            except Exception as e:
                raise RuntimeError(f"Import failed for {output['file']}: {e}")
    finally:
        shutil.rmtree(tmp_dir)
    return outputs


def verify_tests(outputs, spec):
    """Run orchestrator-provided integration tests."""
    tmp_dir = tempfile.mkdtemp()
    try:
        for output in outputs:
            file_path = os.path.join(tmp_dir, output["file"])
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(output["code"])

        for test in spec.get("integration_tests", []):
            test_path = os.path.join(tmp_dir, test["path"])
            os.makedirs(os.path.dirname(test_path), exist_ok=True)
            with open(test_path, "w") as f:
                f.write(test["code"])

        proc = subprocess.run(["pytest", tmp_dir], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Integration tests failed:\n{proc.stdout}\n{proc.stderr}")
    finally:
        shutil.rmtree(tmp_dir)
    return outputs

# -------------------------------
# 2. Generator & Tester Agents
# -------------------------------
def run_generator_agent(file_name, file_spec, full_spec, review_feedback=None):
    """Generate production-ready code for a file."""
    feedback_note = f"\n\nIMPORTANT REVIEW FEEDBACK FROM TESTER:\n{review_feedback}" if review_feedback else ""

    # ✅ Inject orchestrator-provided prefix for generator agents
    role_prefix = full_spec.get("_agent_role_prefix", {}).get("generator", "")

    agent_prompt = f"""{role_prefix}

You are a world-class, elite coding agent responsible for producing the FINAL, PRODUCTION-READY implementation of **{file_name}**.

ABSOLUTE RULES:
1. You are solely responsible for {file_name}. Treat it as your complete ownership.
2. Follow the orchestrator spec EXACTLY — no deviations, no extra features.
3. Ensure 100% compatibility with every other file and module in the orchestrator spec.
4. No placeholders, TODOs, stubs, pseudo-code, or incomplete logic.
5. Include all imports, constants, and configuration keys exactly as described.
6. Adhere to strict naming conventions: snake_case for functions, PascalCase for classes, UPPER_SNAKE_CASE for constants.
7. Code must be runnable, syntax-error-free, and pass all integration tests.
8. Write clean, optimized, and efficient code following SOLID principles.
9. Include comprehensive error handling, logging, and unit-testable design.
10. Document all public classes and functions with docstrings describing purpose, parameters, return types, and edge cases.
11. Do not output anything except the complete code for {file_name}.

FULL PROJECT CONTEXT:
{json.dumps(full_spec, indent=2)}

FILE-SPECIFIC IMPLEMENTATION DETAILS:
{json.dumps(file_spec, indent=2)}
{feedback_note}
"""

    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "You are a strict, world-class coding agent. You output only final, fully functional, and compatible code for your assigned file."
            },
            {"role": "user", "content": agent_prompt}
        ]
    )
    return resp.choices[0].message["content"]




def run_tester_agent(file_name, file_spec, full_spec, generated_code):
    """Review generated code and approve or provide feedback."""
    # ✅ Inject orchestrator-provided prefix for tester agents
    role_prefix = full_spec.get("_agent_role_prefix", {}).get("tester", "")

    tester_prompt = f"""{role_prefix}

You are a world-class senior software reviewer.

Your job: review ONLY the file **{file_name}** produced by the Generator Agent.
You have the full orchestrator spec and the generated code.

RULES:
1. Check that the code exactly matches the orchestrator spec — no deviations or missing parts.
2. Ensure it is compatible with all other files in the project.
3. Confirm no placeholders, TODOs, stubs, or incomplete logic exist.
4. Confirm all required imports, constants, and functions are implemented.
5. Check security, performance, error handling, and adherence to naming conventions.
6. If perfect, output ONLY the keyword: ✅ APPROVED
7. If not perfect, output ONLY a structured critique with:
   - List of violations
   - Exact lines or missing features
   - Instructions for correction

FULL PROJECT CONTEXT:
{json.dumps(full_spec, indent=2)}

FILE-SPECIFIC IMPLEMENTATION DETAILS:
{json.dumps(file_spec, indent=2)}

GENERATED CODE TO REVIEW:
{generated_code}
"""

    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "You are a world-class code reviewer. You must either approve the file or explain exactly why it fails."
            },
            {"role": "user", "content": tester_prompt}
        ]
    )
    return resp.choices[0].message["content"]

# -------------------------------
# 3. Main Runner with Loop
# -------------------------------

def run_agents_for_spec(spec):
    """Run generator + tester loop for each file until approved or max retries."""
    files = get_agent_files(spec)
    outputs = []
    
    for file_name in files:
        file_spec = extract_file_spec(spec, file_name)
        review_feedback = None
        approved = False
        attempts = 0
        
        while not approved and attempts < MAX_RETRIES:
            code = run_generator_agent(file_name, file_spec, spec, review_feedback)
            review = run_tester_agent(file_name, file_spec, spec, code)
            
            if "✅ APPROVED" in review:
                approved = True
                outputs.append({"file": file_name, "code": code})
                print(f"✅ {file_name} approved after {attempts+1} attempt(s).")
            else:
                print(f"❌ {file_name} failed review:\n{review}")
                review_feedback = review
                attempts += 1
        
        if not approved:
            raise RuntimeError(f"File {file_name} could not be approved after {MAX_RETRIES} attempts.")
    
    verify_imports(outputs)
    verify_tests(outputs, spec)

    return outputs

# -------------------------------
# 4. Flask Endpoint
# -------------------------------

@agents_pipeline_bp.route("/run_agents", methods=["POST"])
def run_agents_endpoint():
    body = request.get_json(force=True) or {}
    spec = body.get("spec")
    if not spec:
        return jsonify({"error": "Missing spec"}), 400
    try:
        agent_outputs = run_agents_for_spec(spec)
        return jsonify({"role": "assistant", "agents_output": agent_outputs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
