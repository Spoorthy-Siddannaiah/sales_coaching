"""Deterministic quote and role checks, independent of the model."""

import re
import hashlib
from pathlib import Path

from app.services.coaching_models import CoachingInput, CoachingReport, Evidence


# Fingerprint the loaded provenance rules and extraction contract, not the prompt.
VALIDATOR_VERSION = "evidence-" + hashlib.sha256(b"".join(
    (Path(__file__).parent / name).read_bytes()
    for name in ("evidence_validator.py", "evidence_references.py", "coaching_models.py")
)).hexdigest()[:16]


class ReportValidationError(ValueError):
    def __init__(self, message: str, *, field: str = "report", code: str = "validation_failure"):
        super().__init__(message)
        self.field, self.code = field, code



def attribution_conflict(statement: str) -> tuple[str, str] | None:
    """Return a named rule and only its bounded, attribution-only matching fragment.

    This is not a semantic judge. Negated propositions and hypothetical missing
    roles are not assertions that supplied roles are absent.
    """
    subject = r"speaker (?:attribution|roles?|labels?)"
    predicate = r"(?:unavailable|unknown|missing|not (?:available|provided|known|verified))"
    rules = [
        ("direct_missing_roles", rf"(?<!no )\b{subject}\s+(?:(?:is|are|was|were|remains?|seems?)\s+)?{predicate}\b"),
        ("roles_not_provided", rf"\b{subject}\s+(?:has|have) not been (?:provided|verified|established)\b"),
        ("absence_causes_limitation", rf"\b(?:due to|because of) (?:missing|unknown|unavailable) {subject}\b"),
        ("explicit_role_absence", rf"\b(?:there (?:is|are) |we have |the transcript has )no (?:verified )?{subject}\b"),
        ("cannot_identify_roles", r"\b(?:we |the analysis )?(?:cannot|can't|can not|are unable to) (?:identify|distinguish) (?:the )?(?:salesperson (?:or|and) (?:the )?customer|customer (?:or|and) (?:the )?salesperson)\b"),
    ]
    for clause in re.split(r"[.;!?]|\b(?:but|however|although)\b", statement.lower()):
        clause = clause.strip()
        if re.match(r"(?:do not|never|avoid)\b", clause):
            continue
        for rule, pattern in rules:
            for match in re.finditer(pattern, clause):
                prefix = clause[:match.start()]
                if re.search(r"(?:does not mean|do not mean|not true that|not claiming that|does not imply)\s*$", prefix):
                    continue
                # 'There are no speaker labels missing' denies absence.
                if rule == "explicit_role_absence" and re.match(r"\s+(?:missing|unavailable|unknown)\b", clause[match.end():]):
                    continue
                return rule, match.group(0)[:180]
        match = re.fullmatch(rf"(?:no|missing|unavailable|unknown) (?:verified )?{subject}", clause)
        if match:
            return "terse_role_absence", match.group(0)[:180]
    return None


def contradicts_verified_attribution(statement: str) -> bool:
    return attribution_conflict(statement) is not None

def validate_evidence(report: CoachingReport, source: CoachingInput) -> None:
    full = bool(source.verified_turns)
    if report.mode != ("full" if full else "limited"):
        raise ReportValidationError("mode: Report mode does not match verified attribution.")
    if full:
        for index, item in enumerate(report.evidence_limitations):
            if contradicts_verified_attribution(item):
                field = f"report.evidence_limitations[{index}]"
                raise ReportValidationError(
                    f"{field}: Verified speaker attribution must not be reported as unavailable.",
                    field=field, code="verified_attribution_contradiction")
    if full and source.sufficiently_complete and len(report.improvements) < 2:
        raise ReportValidationError("improvements: A sufficiently complete attributed conversation requires at least two evidence-supported improvements.")
    if len(report.improvements) < 2 and not (report.fewer_improvements_reason or "").strip():
        raise ReportValidationError("fewer_improvements_reason: Explain why fewer than two improvements are supported.")
    if not full and not any("speaker" in item.lower() and "unavailable" in item.lower() for item in report.evidence_limitations):
        raise ReportValidationError("evidence_limitations: Limited mode must disclose that speaker attribution is unavailable.")

    def check(evidence: Evidence, path: str) -> None:
        if not evidence.quote.strip() or evidence.quote not in source.transcript:
            raise ReportValidationError(f"{path}.quote: A quotation is absent from the original transcript.")
        if not full and evidence.role is not None:
            raise ReportValidationError(f"{path}.role: Speaker roles are unavailable; use null attribution.")
        if full and evidence.role is None:
            raise ReportValidationError(f"{path}.role: Full-mode evidence requires a verified speaker role.")
        if evidence.role is not None and not any(
            turn.role == evidence.role and evidence.quote in source.transcript[turn.start:turn.end]
            for turn in source.verified_turns
        ):
            raise ReportValidationError(f"{path}.role: Quotation does not occur within a verified turn for its role.")

    # Traverse typed objects so future evidence-bearing fields cannot be skipped.
    def visit(value: object, path: str = "report") -> None:
        from pydantic import BaseModel
        if isinstance(value, Evidence):
            check(value, path)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                visit(getattr(value, name), f"{path}.{name}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(report)
    for name, dimension in report.dimensions.model_dump().items():
        if not dimension["reason"].strip():
            raise ReportValidationError(f"dimensions.{name}.reason: Provide a nonblank assessment or insufficient-evidence explanation.")
        if not full and dimension["score"] is not None:
            raise ReportValidationError(f"dimensions.{name}.score: Unattributed transcripts cannot receive salesperson scores.")
        if dimension["score"] is not None and not any(item["role"] == "salesperson" for item in dimension["evidence"]):
            raise ReportValidationError(f"dimensions.{name}.evidence: A score needs verified salesperson evidence.")
