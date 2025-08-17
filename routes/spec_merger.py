# routes/spec_merger.py

import json
from typing import Dict, Any, List

# =============================
# SPEC MERGER + VALIDATOR
# =============================

def merge_specs(parts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Deterministically merge outputs from multiple orchestrators:
    - contracts
    - files
    - utilities
    - tests
    - description
    """
    final_spec = {
        "version": "13.0",
        "generated_at": parts.get("meta", {}).get("generated_at"),
        "project": parts.get("description", {}).get("project", ""),
        "description": parts.get("description", {}).get("description", ""),
        "project_type": parts.get("description", {}).get("project_type", "general"),
        "target_users": parts.get("description", {}).get("target_users", []),
        "tech_stack": parts.get("description", {}).get("tech_stack", {}),
        "contracts": parts.get("contracts", {}),
        "files": parts.get("files", []),
        "integration_tests": parts.get("tests", {}).get("integration_tests", []),
        "test_cases": parts.get("tests", {}).get("test_cases", []),
        "dependency_graph": [],
        "global_reference_index": [],
    }

    # Inject utilities into files
    utilities = parts.get("utilities", [])
    for f in final_spec["files"]:
        util = next((u for u in utilities if u["file"] == f["file"]), None)
        if util:
            f["description"] = util.get("description", f.get("description", ""))

    # Build dependency graph
    final_spec["dependency_graph"] = [
        {"file": f["file"], "dependencies": f.get("dependencies", [])}
        for f in final_spec["files"]
    ]

    # Build reference index (skeleton)
    final_spec["global_reference_index"] = [
        {"file": f["file"], "functions": [], "classes": [], "agents": []}
        for f in final_spec["files"]
    ]

    return final_spec


def validate_spec(spec: Dict[str, Any]) -> List[str]:
    """
    Validate completeness of the merged spec.
    Returns a list of errors; empty list means valid.
    """
    errors = []

    # Contracts must exist
    if not spec.get("contracts", {}).get("apis"):
        errors.append("Missing APIs in contracts")
    if not spec.get("contracts", {}).get("functions"):
        errors.append("Missing functions in contracts")
    if not spec.get("contracts", {}).get("entities"):
        errors.append("Missing entities in contracts")

    # Every file must implement at least 1 contract
    contract_names = {
        c["name"]
        for cat in spec["contracts"].values()
        if isinstance(cat, list)
        for c in cat
        if "name" in c
    }
    for f in spec.get("files", []):
        if not f.get("implements"):
            errors.append(f"File {f['file']} has no implements")
        else:
            for impl in f["implements"]:
                if impl not in contract_names:
                    errors.append(f"File {f['file']} implements unknown contract {impl}")

    return errors


def boost_spec_depth(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich the spec with depth notes and missing details.
    """
    for f in spec.get("files", []):
        if "notes" not in f:
            f["notes"] = []
        f["notes"] += [
            "Follow SOLID principles & type hints",
            "Add full docstrings + inline comments",
            "Implement robust error handling",
            "Use logging with correlation IDs",
            "Write deterministic, testable functions"
        ]
    return spec
