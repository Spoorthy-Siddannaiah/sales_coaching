"""Opt-in local diagnostics: never retain prompts, quotes or free-form model text."""

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from app.services.evidence_validator import contradicts_verified_attribution, attribution_conflict, VALIDATOR_VERSION


def retain_rejection(directory: Path, raw: str, *, prompt_version: str, attempt: int,
                     error_type: str, field: str = "report", reason_code: str = "validation_failure",
                     analysis_id: str | None = None, retain_attribution_excerpt: bool = False) -> None:
    """Allowlist only structural facts; exclusions are stronger than string redaction.

    Failure to retain diagnostics must never mask the original validation failure.
    Files are local-only and intentionally insufficient to reconstruct the response.
    """
    payload = {
        "prompt_version": prompt_version, "validator_version": VALIDATOR_VERSION, "attempt": attempt,
        "failing_field": field if re.fullmatch(r"report(?:\.evidence_limitations\[\d+\])?", field) else "report",
        "reason_code": reason_code if reason_code == "verified_attribution_contradiction" else "validation_failure",
        "analysis_id": analysis_id if isinstance(analysis_id, str) and re.fullmatch(r"[a-f0-9-]{36}", analysis_id) else None,
        "error_type": error_type, "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "response_characters": len(raw), "free_text_retained": False,
    }
    try:
        data = json.loads(raw)
        payload["json_valid"] = True
        if isinstance(data, dict):
            payload["mode"] = data.get("mode") if data.get("mode") in ("full", "limited") else None
            limitations = data.get("evidence_limitations")
            if isinstance(limitations, list):
                payload["attribution_checks"] = [
                    {"index": index, "contradictory_claim_detected": contradicts_verified_attribution(item)}
                    for index, item in enumerate(limitations) if isinstance(item, str)
                ]
            # Separate opt-in: retain only the triggering attribution fragment,
            # not the rest of the limitation (which may include private details).
            index_match = re.fullmatch(r"report\.evidence_limitations\[(\d+)\]", field)
            if retain_attribution_excerpt and index_match and isinstance(limitations, list):
                index = int(index_match.group(1))
                if index < len(limitations) and isinstance(limitations[index], str):
                    conflict = attribution_conflict(limitations[index])
                    if conflict:
                        payload["rejected_attribution"] = {
                            "statement_index": index, "matching_rule": conflict[0],
                            "limitation_excerpt": conflict[1], "remainder_excluded": True,
                        }
            for field in ("next_steps", "questions_asked", "improvements"):
                if isinstance(data.get(field), list):
                    payload[field + "_count"] = len(data[field])
    except (ValueError, TypeError):
        payload["json_valid"] = False
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(directory / (str(uuid4()) + ".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, indent=2)
    except OSError:
        pass  # Retention is best-effort; no payload or filesystem detail enters logs/UI.
