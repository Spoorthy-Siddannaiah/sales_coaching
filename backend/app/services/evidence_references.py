"""Model selects source IDs; Python extracts exact text without normalization."""

import copy
import json
import hashlib

from pydantic import Field, ValidationError

from app.services.coaching_models import CoachingInput, CoachingReport, StrictModel
from app.services.evidence_validator import ReportValidationError


class EvidenceReference(StrictModel):
    turn_id: str = Field(pattern=r"^t[0-9]{4}$")


def source_version(source: CoachingInput) -> str:
    # Bind IDs to exact text plus verified spans/roles, not mutable customer context.
    snapshot = {"transcript": source.transcript, "verified_turns": [turn.model_dump() for turn in source.verified_turns]}
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def source_turns(source: CoachingInput) -> list[dict]:
    # IDs are stable for this ordered transcript version, not across edits.
    if not source.verified_turns:
        return [{"turn_id": f"t{index:04d}", "role": None, "text": text}
                for index, text in enumerate(source.transcript.splitlines(keepends=True), 1) if text.strip()]
    return [{"turn_id": f"t{index:04d}", "role": turn.role,
             "text": source.transcript[turn.start:turn.end]}
            for index, turn in enumerate(source.verified_turns, 1)]


def generation_schema() -> dict:
    schema = copy.deepcopy(CoachingReport.model_json_schema())
    # Keep the persisted report contract; generation uses evidence IDs and may
    # omit boilerplate, which Python supplies before report validation.
    schema["$defs"]["Evidence"] = EvidenceReference.model_json_schema()
    schema["properties"]["evidence_limitations"].pop("minItems", None)
    schema["properties"]["source_version"] = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    schema["required"].append("source_version")
    return schema


def turn_catalogue(source: CoachingInput) -> list[dict]:
    """Anonymous segments are text boundaries, never inferred speaker turns."""
    kind = "verified_turn" if source.verified_turns else "unattributed_segment"
    return [dict(item, kind=kind) for item in source_turns(source)]


def extract_report(raw: str, source: CoachingInput) -> CoachingReport:
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("source_version") != source_version(source):
        raise ReportValidationError("report.source_version: Missing or mismatched transcript snapshot.")
    del data["source_version"]  # Internal envelope field is never persisted as report content.
    catalogue = {item["turn_id"]: item for item in source_turns(source)}

    def visit(value, path="report"):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key == "evidence" and isinstance(item, list):
                    extracted = []
                    seen = set()
                    for index, candidate in enumerate(item):
                        reference_path = f"{path}.evidence[{index}]"
                        try:
                            reference = EvidenceReference.model_validate(candidate)
                        except ValidationError as error:
                            issues = "; ".join(".".join(map(str, e["loc"])) + " (" + e["type"] + ")" for e in error.errors(include_input=False))
                            raise ReportValidationError(f"{reference_path}: invalid evidence reference: {issues}") from error
                        turn = catalogue.get(reference.turn_id)
                        if turn is None:
                            raise ReportValidationError(f"{reference_path}.turn_id: Unknown evidence turn ID.")
                        if reference.turn_id in seen:
                            raise ReportValidationError(f"{reference_path}.turn_id: Duplicate evidence turn ID in this finding.")
                        seen.add(reference.turn_id)
                        quote = turn["text"]
                        if not quote.strip():
                            raise ReportValidationError(f"{reference_path}: Evidence span contains no substantive text.")
                        extracted.append({"quote": quote, "role": turn["role"]})
                    value[key] = extracted
                else:
                    visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(data)
    return CoachingReport.model_validate(data)
