# routes/agents.py
from flask import Blueprint, request, jsonify
import openai
import os

agents_bp = Blueprint('agents', __name__)

openai.api_key = os.getenv("OPENAI_API_KEY")

@agents_bp.route('/orchestrator', methods=['POST'])
def orchestrator():
    data = request.get_json()
    project_description = data.get("project", "")

    if not project_description:
        return jsonify({"error": "No project description provided"}), 400

    prompt = f"""
    You are an orchestrator AI. Break down this project into a list of files and tasks.
    Project: {project_description}
    Return JSON with fields: project, tasks (list of {{file, role, instructions}})
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a code project orchestrator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        plan_text = response.choices[0].message['content']
        return jsonify({"plan": plan_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
