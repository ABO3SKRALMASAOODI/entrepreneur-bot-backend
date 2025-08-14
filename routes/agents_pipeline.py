# agents_pipeline.py
import os
import json
import openai
from typing import List, Dict, Any

openai.api_key = os.getenv("OPENAI_API_KEY")

def run_single_agent(agent: Dict[str, Any], assigned_file: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs a single agent for its assigned file.
    """
    prompt = f"""
You are an agent for a {spec.get("project_type", "software")} project.
You are assigned to implement ONLY this file: {assigned_file}

STRICT RULES:
1. Do NOT create or modify any other files.
2. Follow orchestrator spec exactly.
3. Output ONLY the code for your assigned file. No explanations, no markdown, no comments unless part of the actual code.
4. You have the FULL project specification for context — but you must ONLY implement your assigned file.

FULL PROJECT SPEC:
{json.dumps(spec, indent=2)}
    """

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a senior coding agent."},
                {"role": "user", "content": prompt}
            ]
        )
        return {
            "agent_name": agent["name"],
            "file": assigned_file,
            "output": resp.choices[0].message["content"]
        }
    except Exception as e:
        return {
            "agent_name": agent["name"],
            "file": assigned_file,
            "output": f"❌ Error: {e}"
        }

def run_all_agents_for_spec(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Runs all agents listed in the spec["agent_blueprint"].
    Assigns one file per agent.
    """
    outputs = []

    # Collect all files mentioned in agent_blueprint
    for agent in spec.get("agent_blueprint", []):
        # Extract file name from description if explicitly mentioned
        assigned_file = None
        desc = agent.get("description", "")
        if "implementing " in desc.lower():
            # Attempt to extract file name from description
            try:
                assigned_file = desc.split("implementing ")[-1].strip().split(" ")[0]
            except Exception:
                pass
        
        # Fallback: derive file from agent name
        if not assigned_file:
            base_name = agent["name"].replace("Agent", "").lower()
            assigned_file = f"{base_name}.py"

        outputs.append(run_single_agent(agent, assigned_file, spec))

    return outputs
