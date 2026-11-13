"""Strict OpenAI Responses JSON schemas for research stages.

Schema constraints validate the wire structure, not factual entailment.
"""


def _array_of_strings():
    return {"type": "array", "items": {"type": "string"}}


def _object(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


PLAN = _object({
    "queries": _array_of_strings(),
    "hypotheses": _array_of_strings(),
    "scope": {"type": "string"},
}, ["queries", "hypotheses", "scope"])

EVIDENCE = _object({
    "claims": {"type": "array", "items": _object({
        "text": {"type": "string"},
        "status": {"type": "string", "enum": [
            "supported", "partially_supported", "disputed", "unverified", "refuted"
        ]},
        "analysis": {"type": "string"},
        "evidence": {"type": "array", "items": _object({
            "source_id": {"type": "string"},
            "quote": {"type": "string"},
            "polarity": {"type": "string", "enum": [
                "supports", "contradicts", "context"
            ]},
        }, ["source_id", "quote", "polarity"])},
    }, ["text", "status", "analysis", "evidence"])},
}, ["claims"])

CRITIC = _object({
    "stop": {"type": "boolean"},
    "next_queries": _array_of_strings(),
    "gaps": _array_of_strings(),
    "contradictions": _array_of_strings(),
    "rationale": {"type": "string"},
}, ["stop", "next_queries", "gaps", "contradictions", "rationale"])

SCHEMAS = {
    "planner": ("research_planner", PLAN),
    "evidence": ("research_evidence", EVIDENCE),
    "critic": ("research_critic", CRITIC),
}


def format_for_stage(stage: str) -> dict:
    match = SCHEMAS.get(stage)
    if match:
        name, schema = match
        return {"type": "json_schema", "name": name,
                "schema": schema, "strict": True}
    return {"type": "json_object"}

