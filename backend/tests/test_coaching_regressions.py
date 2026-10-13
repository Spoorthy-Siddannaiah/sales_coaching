"""Observed live failures, checked offline. No provider or network requests."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.external_evaluation import external_input
from app.services.coaching import CoachingError, analyze_conversation
from app.services.coaching_models import CoachingReport
from app.services.evidence_references import extract_report, generation_schema, source_turns, turn_catalogue, source_version
from app.services.evidence_validator import ReportValidationError, validate_evidence

REJECTED = Path(__file__).parent / "fixtures/rejected_kapibala_report.json"


def original_report():
    return json.loads(REJECTED.read_text())


def baseline():
    # Minimal authored mock, not a corrected live report or quality assessment.
    data = original_report()
    data["summary"]["evidence"] = data["summary"]["evidence"][:1]
    data["outcome"] = None
    for name in ("customer_needs_and_pain_points", "questions_asked", "open_questions", "next_steps", "strengths", "improvements"):
        data[name] = []
    for dimension in data["dimensions"].values():
        dimension["score"] = 3
        dimension["evidence"] = [original_report()["dimensions"]["discovery_questions"]["evidence"][0]]
    data["fewer_improvements_reason"] = "Minimal mocked report for validator tests."
    data["evidence_limitations"] = ["Quotation matching does not establish semantic correctness."]
    return data


def evidence_items(value):
    if isinstance(value, dict):
        if "quote" in value and "role" in value:
            yield value
        for item in value.values(): yield from evidence_items(item)
    elif isinstance(value, list):
        for item in value: yield from evidence_items(item)


def invalid_quotes():
    source = external_input()
    return [e for e in evidence_items(original_report()) if e["quote"] not in source.transcript]


@pytest.mark.parametrize("index", range(7))
def test_each_original_bad_quote_still_fails_exact_validation(index):
    data = baseline()
    data["summary"]["evidence"] = [invalid_quotes()[index]]
    with pytest.raises(ReportValidationError, match="absent"):
        validate_evidence(CoachingReport.model_validate(data), external_input())


def test_original_report_is_unchanged_and_rejected():
    report = CoachingReport.model_validate(original_report())
    with pytest.raises(ReportValidationError): validate_evidence(report, external_input())
    quotes = list(evidence_items(original_report()))
    assert len(quotes) == 42 and len(invalid_quotes()) == 7
    assert len({e["quote"] for e in invalid_quotes()}) == 3


def wire_report():
    data = baseline()
    data["source_version"] = source_version(external_input())
    catalogue = source_turns(external_input())
    def visit(value):
        if isinstance(value, dict):
            if "evidence" in value:
                refs = []
                for e in value["evidence"]:
                    turn = next(t for t in catalogue if t["role"] == e["role"] and e["quote"] in t["text"])
                    start = turn["text"].index(e["quote"])
                    refs.append({"turn_id": turn["turn_id"]})
                value["evidence"] = refs
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(data)
    return data


@pytest.mark.parametrize("turn_id", ["t0005", "t0008", "t0010"])
def test_extraction_preserves_problematic_newlines_and_capitalization(turn_id):
    source = external_input()
    turn = next(t for t in source_turns(source) if t["turn_id"] == turn_id)
    data = wire_report()
    data["summary"]["evidence"] = [{"turn_id": turn_id}]
    report = extract_report(json.dumps(data), source)
    assert report.summary.evidence[0].quote == turn["text"]
    assert "\n" in report.summary.evidence[0].quote
    validate_evidence(report, source)


@pytest.mark.parametrize("update", [
    {"turn_id": "t9999"}, {"role": "salesperson"}, {"start": -1},
    {"start": 99999}, {"end": 99999}, {"start": 10, "end": 1},
    {"quote": "Do not accept a model-written quotation"}, {"role": None},
])
def test_invalid_reference_is_rejected_without_fallback(update):
    data = wire_report()
    data["summary"]["evidence"][0].update(update)
    with pytest.raises((ReportValidationError, ValidationError)):
        extract_report(json.dumps(data), external_input())


def test_source_turn_extraction_preserves_unicode():
    source = external_input()
    data = wire_report()
    data["summary"]["evidence"] = [{"turn_id": "t0002"}]
    report = extract_report(json.dumps(data), source)
    assert "days—with" in report.summary.evidence[0].quote
    assert report.summary.evidence[0].quote == source_turns(source)[1]["text"]


def test_catalogue_is_stable_and_does_not_duplicate_or_rewrite_text():
    source = external_input()
    assert turn_catalogue(source) == turn_catalogue(source)
    for item, turn in zip(turn_catalogue(source), source_turns(source)):
        assert item["text"] == turn["text"]
    schema = generation_schema()["$defs"]["Evidence"]
    assert set(schema["required"]) == {"turn_id"}
    assert schema["additionalProperties"] is False and "quote" not in schema["properties"]


@pytest.mark.parametrize("limitation", ["Speaker attribution is unavailable.", "Speaker labels are unknown.", "Missing speaker attribution."])
def test_verified_roles_cannot_be_disclosed_as_missing(limitation):
    data = baseline()
    data["evidence_limitations"] = [limitation]
    with pytest.raises(ReportValidationError, match="attribution"):
        validate_evidence(CoachingReport.model_validate(data), external_input())


def test_full_mode_cannot_null_out_evidence_role():
    data = baseline()
    data["summary"]["evidence"][0]["role"] = None
    with pytest.raises(ReportValidationError, match="requires"):
        validate_evidence(CoachingReport.model_validate(data), external_input())


def test_verified_roles_do_not_imply_names_or_timestamps():
    data = baseline()
    data["evidence_limitations"] = ["Speaker names are unknown. Speaker attribution is available; timestamps are unavailable."]
    validate_evidence(CoachingReport.model_validate(data), external_input())


@pytest.mark.parametrize("dimension", list(baseline()["dimensions"]))
def test_maximum_score_with_one_salesperson_turn_is_not_rejected(dimension):
    data = baseline()
    data["dimensions"][dimension]["score"] = 5
    assert len(data["dimensions"][dimension]["evidence"]) == 1
    validate_evidence(CoachingReport.model_validate(data), external_input())
    # Acceptance proves provenance/structure, not the semantic merit of 5/5.


def test_no_opportunity_can_receive_null_with_explanation():
    data = baseline()
    data["dimensions"]["objection_handling"] = {
        "score": None, "reason": "No observable objection-handling opportunity in this mocked input.", "evidence": []}
    validate_evidence(CoachingReport.model_validate(data), external_input())


@pytest.mark.parametrize("score", [0, 6, 3.5, "5"])
def test_out_of_range_or_wrong_type_score_rejected(score):
    data = baseline()
    data["dimensions"]["discovery_questions"]["score"] = score
    with pytest.raises(ValidationError): CoachingReport.model_validate(data)


def test_missing_required_schema_field_rejected():
    data = baseline()
    del data["dimensions"]["discovery_questions"]["reason"]
    with pytest.raises(ValidationError): CoachingReport.model_validate(data)


def test_bad_reference_diagnostic_identifies_dimension_without_source_text():
    data = wire_report()
    data["dimensions"]["objection_handling"]["evidence"] = [{"turn_id": "t9999"}]
    with pytest.raises(ReportValidationError, match=r"report.dimensions.objection_handling.evidence\[0\].turn_id") as error:
        extract_report(json.dumps(data), external_input())
    assert "Unknown evidence turn ID" in str(error.value)
    assert "OmniSupport" not in str(error.value)


def test_numeric_score_without_salesperson_evidence_names_dimension():
    data = baseline()
    data["dimensions"]["objection_handling"]["evidence"] = []
    with pytest.raises(ReportValidationError, match=r"dimensions.objection_handling.evidence"):
        validate_evidence(CoachingReport.model_validate(data), external_input())


def test_limited_mode_references_remain_role_neutral():
    source = external_input().model_copy(update={"verified_turns": []})
    data = wire_report()
    data["source_version"] = source_version(source)
    data["mode"] = "limited"
    data["evidence_limitations"].append("Speaker attribution is unavailable.")
    def visit(value):
        if isinstance(value, dict):
            if "turn_id" in value: value.update(turn_id="t0001")
            if "score" in value: value["score"] = None
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(data)
    report = extract_report(json.dumps(data), source)
    validate_evidence(report, source)
    assert report.summary.evidence[0].quote == source_turns(source)[0]["text"]


def test_mocked_generation_receives_observed_semantic_safeguards():
    class MockProvider:
        max_attempts = 1
        async def generate(self, messages, schema):
            prompt = messages[0]["content"]
            for instruction in (
                "One current-systems question is", "Unsupported salesperson percentages",
                "Missing impact or success criteria", "promised actions, conditional commitments",
                "Do not call a kickoff scheduled", "ONLY questions still unanswered",
                "ONLY remaining actions", "Do not repeat completed actions",
                "supplied email channel", "never claim speaker attribution is missing",
            ):
                assert instruction in prompt
            payload = json.loads(messages[1]["content"])
            # The full chronology must reach the provider; not just its opening.
            assert "I received the security datasheet" in "".join(t["text"] for t in payload["source_turns"])
            assert "You can send it to my email" in "".join(t["text"] for t in payload["source_turns"])
            assert payload["source_turns"] == turn_catalogue(external_input())
            assert schema == generation_schema()
            return json.dumps(wire_report())
    result = asyncio.run(analyze_conversation(external_input(), MockProvider()))
    assert result.attempts == 1


def test_model_retyped_historical_report_cannot_bypass_reference_contract():
    class MockProvider:
        max_attempts = 1
        async def generate(self, messages, schema):
            return REJECTED.read_text()
    with pytest.raises(CoachingError):
        asyncio.run(analyze_conversation(external_input(), MockProvider()))


def test_null_dimension_needs_nonblank_explanation():
    data = baseline()
    data["dimensions"]["objection_handling"].update(score=None, reason=" ", evidence=[])
    with pytest.raises(ReportValidationError, match=r"dimensions.objection_handling.reason"):
        validate_evidence(CoachingReport.model_validate(data), external_input())


def test_mocked_single_response_objection_resolution_accepts_five():
    from app.services.coaching_models import CoachingInput, VerifiedTurn
    customer = "We cannot proceed unless we can export our data without a lock-in fee."
    salesperson = "Your contract includes a complete CSV export at no additional charge, including after cancellation."
    acceptance = "That addresses my concern; the documented export terms meet our requirement."
    text = "\n".join([customer, salesperson, acceptance])
    source = CoachingInput(transcript=text, objective="Address export concern", customer_context="Fictional customer requires data portability.", verified_turns=[
        VerifiedTurn(start=0, end=len(customer), role="customer"),
        VerifiedTurn(start=len(customer)+1, end=len(customer)+1+len(salesperson), role="salesperson"),
        VerifiedTurn(start=len(customer)+len(salesperson)+2, end=len(text), role="customer")])
    class Provider:
        max_attempts = 1
        async def generate(self, messages, schema):
            data = wire_report()
            data["source_version"] = source_version(source)
            def visit(value):
                if isinstance(value, dict):
                    if "turn_id" in value: value.update(turn_id="t0002")
                    for item in value.values(): visit(item)
                elif isinstance(value, list):
                    for item in value: visit(item)
            visit(data)
            data["dimensions"]["objection_handling"] = {
                "score": 5, "reason": "One substantive response addresses the portability concern; the customer explicitly accepts the terms.",
                "evidence": [{"turn_id":"t0002"}, {"turn_id":"t0003"}]}
            return json.dumps(data)
    result = asyncio.run(analyze_conversation(source, Provider()))
    assert result.report.dimensions.objection_handling.score == 5
    assert result.report.dimensions.objection_handling.evidence[0].quote == salesperson
    assert result.attempts == 1


@pytest.mark.parametrize("case", ["discovery", "chronology", "uncertainty"])
def test_quality_rules_reach_provider_and_mocked_report_preserves_source(case):
    """Contract/provenance regression, not a claim that a model obeys prose rules."""
    source = external_input()
    def ref(turn_id):
        turn = next(t for t in source_turns(source) if t["turn_id"] == turn_id)
        return {"turn_id": turn_id}
    data = wire_report()
    instructions = {
        "discovery": ["Customer-volunteered details and customer questions", "not salesperson", "acknowledge", "do not", "questioner"],
        "chronology": ["read later evidence", "ONLY remaining actions", "historical completed actions", "not a confirmed meeting date"],
        "uncertainty": ["preserve what was known", "Do not assert unverified SOC 2", "claimed performance percentage", "measuring customer-specific"],
    }
    if case == "discovery":
        data["questions_asked"] = [
            {"text": "Salesperson asks about current systems.", "evidence": [ref("t0002")]},
            {"text": "Customer asks about handoff and security.", "evidence": [ref("t0005")]},
        ]
        data["dimensions"]["discovery_questions"]["reason"] = "Relevant systems question, but impact and measurable success were not investigated."
    elif case == "chronology":
        data["outcome"] = {"text": "Customer reports review and signup completed.", "evidence": [ref("t0009")]}
        data["next_steps"] = [{"text": "Onboarding team to contact the customer to arrange kickoff.", "evidence": [ref("t0010")]}]
    else:
        data["improvements"] = [
            {"suggestion": "Verify security status.", "why_it_matters": "Avoid unsupported assurances.", "suggested_phrasing": "Let me verify the official security documentation before confirming compliance.", "evidence": [ref("t0006")]},
            {"suggestion": "Validate expected automation.", "why_it_matters": "Applicability is not established.", "suggested_phrasing": "Let us measure which of your ticket types could be automated in a pilot.", "evidence": [ref("t0004")]},
        ]
        data["fewer_improvements_reason"] = None
    class MockProvider:
        max_attempts = 1
        calls = 0
        async def generate(self, messages, schema):
            self.calls += 1
            for rule in instructions[case]:
                assert rule in messages[0]["content"]
            assert json.loads(messages[1]["content"])["source_turns"] == turn_catalogue(source)
            return json.dumps(data)
    provider = MockProvider()
    result = asyncio.run(analyze_conversation(source, provider))
    assert provider.calls == result.attempts == 1
    validate_evidence(result.report, source)
    if case == "discovery":
        assert [item.evidence[0].role for item in result.report.questions_asked] == ["salesperson", "customer"]
        assert "not investigated" in result.report.dimensions.discovery_questions.reason
    elif case == "chronology":
        assert len(result.report.next_steps) == 1
        assert result.report.next_steps[0].evidence[0].quote == source_turns(source)[9]["text"]
        assert result.report.outcome.evidence[0].role == "customer"
    else:
        assert "verify" in result.report.improvements[0].suggested_phrasing
        assert "measure" in result.report.improvements[1].suggested_phrasing


@pytest.mark.parametrize("text", [
    "Speaker attribution is verified, but interpretation accuracy is not guaranteed.",
    "No speaker attribution is missing.", "There are no missing speaker labels.",
    "Speaker names are unknown; speaker roles are verified.",
    "Speaker attribution is not missing.", "Speaker roles are not unavailable.",
    "Do not claim speaker attribution is unavailable.",
])
def test_legitimate_attribution_limitations_pass(text):
    data = baseline()
    data["evidence_limitations"] = [text]
    validate_evidence(CoachingReport.model_validate(data), external_input())


@pytest.mark.parametrize("text", [
    "Speaker attribution is unavailable.", "Speaker roles are unknown.",
    "Speaker labels were missing.", "No verified speaker roles.",
    "There are no speaker labels in this transcript.",
    "Speaker attribution is verified, but speaker roles are unavailable.",
    "Speaker roles are not provided.", "Speaker attribution unavailable.",
    "Speaker attribution has not been provided.",
    "Due to missing speaker attribution, assessment is limited.",
])
def test_direct_contradictory_attribution_claims_fail(text):
    data = baseline()
    data["evidence_limitations"] = [text]
    with pytest.raises(ReportValidationError, match="attribution"):
        validate_evidence(CoachingReport.model_validate(data), external_input())


def test_rejected_diagnostics_are_opt_in_and_exclude_free_text(tmp_path):
    secret_marker = "PRIVATE_TRANSCRIPT_AND_CREDENTIAL_MARKER"
    data = wire_report()
    data["evidence_limitations"] = ["Speaker attribution is unavailable. " + secret_marker]
    data["summary"]["text"] = secret_marker
    class MockProvider:
        max_attempts = 1
        async def generate(self, messages, schema): return json.dumps(data)
    with pytest.raises(CoachingError):
        asyncio.run(analyze_conversation(external_input(), MockProvider()))
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(CoachingError):
        asyncio.run(analyze_conversation(external_input(), MockProvider(), diagnostics_path=tmp_path))
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    retained = files[0].read_text()
    assert secret_marker not in retained and "OmniSupport" not in retained
    assert '"contradictory_claim_detected": true' in retained
    assert '"free_text_retained": false' in retained
    assert files[0].stat().st_mode & 0o777 == 0o600


def test_diagnostics_write_failure_preserves_original_rejection(tmp_path):
    from app.services.rejection_diagnostics import retain_rejection
    destination = tmp_path / "file"
    destination.write_text("not a directory")
    retain_rejection(destination, "not JSON: private text", prompt_version="test", attempt=1, error_type="JSONDecodeError")
    assert destination.read_text() == "not a directory"


@pytest.mark.parametrize("text", [
    "Interpretation uncertainty does not mean speaker roles are unknown.",
    "It is not true that speaker attribution is unavailable.",
    "This analysis would be impossible without verified speaker roles.",
])
def test_denied_and_hypothetical_missing_role_claims_are_valid(text):
    data = baseline()
    data["evidence_limitations"] = [text]
    validate_evidence(CoachingReport.model_validate(data), external_input())


def test_denial_does_not_hide_a_separate_contradictory_assertion():
    data = baseline()
    data["evidence_limitations"] = ["This does not mean speaker roles are unknown, but speaker attribution is unavailable."]
    with pytest.raises(ReportValidationError) as error:
        validate_evidence(CoachingReport.model_validate(data), external_input())
    assert error.value.field == "report.evidence_limitations[0]"
    assert error.value.code == "verified_attribution_contradiction"


def test_safe_diagnostics_identify_failing_field_without_retaining_statement(tmp_path):
    from app.services.rejection_diagnostics import retain_rejection
    from app.services.evidence_validator import VALIDATOR_VERSION
    retain_rejection(tmp_path, json.dumps({"evidence_limitations": ["private statement"]}),
        prompt_version="test", attempt=1, error_type="ReportValidationError",
        field="report.evidence_limitations[0]", reason_code="verified_attribution_contradiction")
    data = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert data["failing_field"] == "report.evidence_limitations[0]"
    assert data["reason_code"] == "verified_attribution_contradiction"
    assert data["validator_version"] == VALIDATOR_VERSION
    assert "private statement" not in json.dumps(data)


@pytest.mark.parametrize("statement", [
    "Speaker roles are verified, but interpretation accuracy is not guaranteed.",
    "Speaker attribution is available; however, the analysis may contain errors.",
    "There are no speaker labels missing.",
])
def test_requested_valid_limitations_and_reproduced_no_labels_false_positive(statement):
    data = baseline()
    data["evidence_limitations"] = [statement]
    validate_evidence(CoachingReport.model_validate(data), external_input())


@pytest.mark.parametrize("statement", [
    "Speaker attribution is unavailable.", "We cannot identify the salesperson or customer.",
])
def test_requested_contradictions_are_rejected(statement):
    data = baseline()
    data["evidence_limitations"] = [statement]
    with pytest.raises(ReportValidationError, match=r"report.evidence_limitations\[0\]"):
        validate_evidence(CoachingReport.model_validate(data), external_input())


def test_excerpt_diagnostic_identifies_rule_and_excludes_surrounding_sensitive_text(tmp_path):
    from app.services.rejection_diagnostics import retain_rejection
    from app.services.evidence_validator import VALIDATOR_VERSION
    statement = "Speaker attribution is unavailable. Private company SECRET-CONTEXT and person@example.com"
    raw = json.dumps({"evidence_limitations": [statement], "summary": {"text": "PRIVATE TRANSCRIPT"}})
    arguments = dict(prompt_version="test", attempt=1, error_type="ReportValidationError",
        field="report.evidence_limitations[0]", reason_code="verified_attribution_contradiction")
    retain_rejection(tmp_path / "default", raw, **arguments)
    default = json.loads(next((tmp_path / "default").glob("*.json")).read_text())
    assert "rejected_attribution" not in default
    retain_rejection(tmp_path / "opt-in", raw, **arguments, retain_attribution_excerpt=True)
    saved = json.loads(next((tmp_path / "opt-in").glob("*.json")).read_text())
    assert saved["rejected_attribution"] == {
        "statement_index": 0, "matching_rule": "direct_missing_roles",
        "limitation_excerpt": "speaker attribution is unavailable", "remainder_excluded": True,
    }
    assert saved["validator_version"] == VALIDATOR_VERSION
    for sensitive in ("SECRET-CONTEXT", "person@example.com", "PRIVATE TRANSCRIPT"):
        assert sensitive not in json.dumps(saved)


def test_unknown_names_are_distinct_from_unavailable_sales_roles():
    data = baseline()
    data["evidence_limitations"] = ["We cannot identify the names of the salesperson or customer."]
    validate_evidence(CoachingReport.model_validate(data), external_input())


@pytest.mark.parametrize("full", [True, False])
def test_explicit_attribution_and_deterministic_limits_use_same_analysis_pipeline(full):
    source = external_input().model_copy(update={"sufficiently_complete": full})
    data = wire_report()
    data["evidence_limitations"] = []
    if full:
        evidence = data["dimensions"]["discovery_questions"]["evidence"]
        data["improvements"] = [
            {"suggestion": title, "why_it_matters": "Mocked supported coaching opportunity.",
             "suggested_phrasing": phrasing, "evidence": evidence}
            for title, phrasing in [("Clarify impact", "What impact do delays have?"),
                                   ("Agree measurable success", "What measurable outcome would make a pilot worthwhile?")]
        ]
        data["fewer_improvements_reason"] = None
    else:
        source = source.model_copy(update={"verified_turns": []})
        data["source_version"] = source_version(source)
        data["mode"] = "limited"
        def neutral(value):
            if isinstance(value, dict):
                if "turn_id" in value: value.update(turn_id="t0001")
                if "score" in value: value["score"] = None
                for item in value.values(): neutral(item)
            elif isinstance(value, list):
                for item in value: neutral(item)
        neutral(data)
    class MockProvider:
        max_attempts = 1
        calls = 0
        async def generate(self, messages, schema):
            self.calls += 1
            payload = json.loads(messages[1]["content"])
            assert payload["attribution"] == {
                "required_mode": "full" if full else "limited",
                "speaker_role_status": "verified_and_available" if full else "unavailable",
                "verified_roles": ["salesperson", "customer"] if full else [],
                "interpretation_accuracy_guaranteed": False,
            }
            assert "server-built attribution metadata is authoritative" in messages[0]["content"]
            assert "minItems" not in schema["properties"]["evidence_limitations"]
            return json.dumps(data)
    provider = MockProvider()
    result = asyncio.run(analyze_conversation(source, provider))
    assert provider.calls == result.attempts == 1
    report = result.report
    validate_evidence(report, source)
    assert len(report.dimensions.model_dump()) == 5
    assert len(report.improvements) == (2 if full else 0)
    assert ("Speaker attribution is unavailable." in report.evidence_limitations) is (not full)
    assert "Exact source quotations establish provenance, not interpretation accuracy." in report.evidence_limitations
    if not full:
        assert all(item["score"] is None for item in report.dimensions.model_dump().values())
    # Persisted schema remains strict even though generation permits an empty list.
    assert CoachingReport.model_json_schema()["properties"]["evidence_limitations"]["minItems"] == 1


@pytest.mark.parametrize("limitation,accepted", [
    ("Speaker attribution is unavailable.", False),
    ("Speaker roles are verified, but interpretation accuracy is not guaranteed.", True),
])
def test_standard_caveats_never_replace_a_model_contradiction(limitation, accepted):
    from app.services.coaching import add_standard_limitations
    source = external_input()
    data = wire_report()
    data["evidence_limitations"] = [limitation]
    prepared = json.loads(add_standard_limitations(json.dumps(data), source))
    assert prepared["evidence_limitations"][0] == limitation
    class MockProvider:
        max_attempts = 1
        async def generate(self, messages, schema): return json.dumps(data)
    if accepted:
        report = asyncio.run(analyze_conversation(source, MockProvider())).report
        assert limitation in report.evidence_limitations
    else:
        with pytest.raises(CoachingError, match="Verified speaker attribution"):
            asyncio.run(analyze_conversation(source, MockProvider()))


def test_standard_caveats_do_not_repair_missing_or_malformed_model_fields():
    from app.services.coaching import add_standard_limitations
    for invalid in (None, "not a list", [123]):
        data = wire_report()
        data["evidence_limitations"] = invalid
        with pytest.raises(ValidationError):
            extract_report(add_standard_limitations(json.dumps(data), external_input()), external_input())
    data = wire_report()
    del data["evidence_limitations"]
    with pytest.raises(ValidationError):
        extract_report(add_standard_limitations(json.dumps(data), external_input()), external_input())



def test_id_only_contract_populates_exact_text_and_actual_roles():
    source = external_input()
    data = wire_report()
    data["summary"]["evidence"] = [{"turn_id": "t0002"}, {"turn_id": "t0003"}]
    report = extract_report(json.dumps(data), source)
    assert [e.role for e in report.summary.evidence] == ["salesperson", "customer"]
    assert [e.quote for e in report.summary.evidence] == [t["text"] for t in source_turns(source)[1:3]]
    validate_evidence(report, source)
    assert "source_version" not in report.model_dump()
    schema = generation_schema()["$defs"]["Evidence"]
    assert set(schema["properties"]) == {"turn_id"}
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("extra", [{"role": "customer"}, {"role": "salesperson"}, {"quote": "Invented quote"}])
def test_role_and_quote_claims_are_rejected_not_overwritten(extra):
    data = wire_report()
    data["summary"]["evidence"] = [{"turn_id": "t0002", **extra}]
    with pytest.raises(ReportValidationError, match="invalid evidence reference"):
        extract_report(json.dumps(data), external_input())


@pytest.mark.parametrize("reference", [{"turn_id": "t9999"}, {"turn_id": "bad"}, {"turn_id": 2}, {}, None])
def test_invalid_id_only_references_fail(reference):
    data = wire_report()
    data["summary"]["evidence"] = [reference]
    with pytest.raises(ReportValidationError):
        extract_report(json.dumps(data), external_input())


def test_duplicate_ids_within_finding_rejected_reuse_across_findings_allowed():
    data = wire_report()
    extract_report(json.dumps(data), external_input())  # Reuse across dimensions is legitimate.
    data["summary"]["evidence"] = [{"turn_id": "t0002"}, {"turn_id": "t0002"}]
    with pytest.raises(ReportValidationError, match="Duplicate"):
        extract_report(json.dumps(data), external_input())


def test_response_snapshot_mismatch_is_rejected():
    source = external_input()
    data = wire_report()
    changed = source.model_copy(update={"transcript": source.transcript + "\nAdditional original source text."})
    with pytest.raises(ReportValidationError, match="mismatched transcript"):
        extract_report(json.dumps(data), changed)
    data.pop("source_version")
    with pytest.raises(ReportValidationError, match="Missing"):
        extract_report(json.dumps(data), source)
    assert source_version(source) == source_version(source.model_copy(update={"objective": "Another objective"}))


def test_id_resolution_does_not_infer_roles_for_unattributed_text():
    source = external_input().model_copy(update={"verified_turns": []})
    data = wire_report()
    data["source_version"] = source_version(source)
    data["mode"] = "limited"
    data["evidence_limitations"] = ["Speaker attribution is unavailable."]
    def neutral(value):
        if isinstance(value, dict):
            if "turn_id" in value: value["turn_id"] = "t0001"
            if "score" in value: value["score"] = None
            for item in value.values(): neutral(item)
        elif isinstance(value, list):
            for item in value: neutral(item)
    neutral(data)
    report = extract_report(json.dumps(data), source)
    validate_evidence(report, source)
    assert report.summary.evidence[0].role is None
    assert report.summary.evidence[0].quote == source_turns(source)[0]["text"]


@pytest.mark.parametrize("dimension", list(baseline()["dimensions"]))
def test_all_five_rubrics_have_explicit_behavioral_levels(dimension):
    from app.services.coaching import SYSTEM_PROMPT
    section = SYSTEM_PROMPT.split("- " + dimension + ":", 1)[1].split("\n- ", 1)[0]
    for level in range(1, 6):
        assert f"  {level}: " in section
    assert "do not reward closing itself" in SYSTEM_PROMPT


def test_fixture_chronology_and_question_attribution_reach_mocked_coaching():
    """Source and pipeline regression, not a model-quality or expected-score oracle."""
    source = external_input()
    turns = source_turns(source)
    assert len(turns) == 15
    assert turns[1]["role"] == "salesperson" and "which CRM or systems" in turns[1]["text"]
    assert turns[4]["role"] == "customer" and "Are you SOC2 compliant" in turns[4]["text"]
    assert "I received the security datasheet" in turns[8]["text"]
    assert "completed the signup process" in turns[8]["text"]
    assert "will reach out" in turns[9]["text"] and "to schedule your kickoff meeting" in turns[9]["text"]
    data = wire_report()
    data["dimensions"]["discovery_questions"]["reason"] = "The salesperson asked about systems but did not investigate ticket volume, business impact or measurable success."
    data["outcome"] = {"text": "Customer reports receiving the security document and completing signup.", "evidence": [{"turn_id": "t0009"}]}
    data["next_steps"] = [{"text": "Onboarding team to contact the customer within three business days to arrange kickoff.", "evidence": [{"turn_id": "t0010"}]}]
    data["open_questions"] = []
    class MockProvider:
        max_attempts = 1
        async def generate(self, messages, schema):
            prompt = messages[0]["content"]
            assert "Customer-volunteered details and customer questions" in prompt
            assert "compare each proposed action with ALL later turns" in prompt
            assert "Superseded follow-ups must not duplicate" in prompt
            assert json.loads(messages[1]["content"])["source_turns"] == turn_catalogue(source)
            return json.dumps(data)
    report = asyncio.run(analyze_conversation(source, MockProvider())).report
    assert "did not investigate" in report.dimensions.discovery_questions.reason
    assert report.outcome.evidence[0].role == "customer"
    assert report.next_steps[0].evidence[0].role == "salesperson"
    assert len(report.next_steps) == 1 and not report.open_questions
    assert "receiving" in report.outcome.text and "signup" in report.outcome.text


def test_original_merged_message_is_preserved_without_invented_turn_boundaries():
    """Pinned upstream message hash was independently rechecked; no network in tests."""
    import hashlib
    from app.external_evaluation import FIXTURE
    record = json.loads(FIXTURE.read_text())
    message = record["messages"][8]
    assert set(message) == {"role", "content"}
    assert hashlib.sha256(message["content"].encode()).hexdigest() == "54d12a9b1506011b8fa034a41cee8f32c47b48db484d278cd467d92cad942c82"
    catalogue = source_turns(external_input())
    assert len(catalogue) == len(record["messages"]) == 15
    assert catalogue[8]["text"] == message["content"]
    text = catalogue[8]["text"]
    assert text.index("I'll review the document") < text.index("I received the security datasheet") < text.index("completed the signup process")
    assert catalogue[9]["text"] == record["messages"][9]["content"]


@pytest.mark.parametrize("instruction", [
    "Do not start from the purchase outcome or a default score of 5",
    "best-supported anchor, not the highest plausible score",
    "Customer security questions do not count as salesperson discovery",
    "workload/context, business impact, decision criteria and measurable success",
    "A salesperson's assertion is evidence that the claim was made, not substantiation",
    "later statement within that same message supersedes the earlier intention",
    "A generic 'confirm receipt' suggestion is redundant",
    "Repeating a need in a product pitch is not confirmation of priority or business impact",
    "customer agreement to buy is not a substitute",
    "Missing business-impact investigation is a substantive discovery gap",
    "Include customer questions as well as seller questions",
    "including multiple questions in one message and questions later answered",
    "benchmarks or case studies need explicit source support",
    "do not turn a claimed upper bound into a typical result",
    "customer-reported acceptance may support resolution but does not independently verify a technical claim",
    "promised contact to arrange it is not a confirmed meeting date",
    "Identify seller behaviors before scoring",
    "Check every substantive requirement of the selected anchor; choose the highest fully supported score",
    "Reconcile reasons with gaps and recommendations, without automatically lowering scores because improvements exist",
    "Discovery reasons must distinguish seller questions/follow-ups from answers to customer questions",
    "Volunteered needs require actual seller investigation or confirmation to earn credit",
    "Unsupported numbers are product claims, not independently substantiated customer results",
    "contact is not completed onboarding",
    "Review both speakers from first turn to last for omitted questions; invent none",
])
def test_scoring_and_final_state_instructions_are_in_actual_provider_request(instruction):
    class MockProvider:
        max_attempts = 1
        async def generate(self, messages, schema):
            assert instruction in " ".join(messages[0]["content"].split())
            assert json.loads(messages[1]["content"])["source_turns"] == turn_catalogue(external_input())
            return json.dumps(wire_report())
    asyncio.run(analyze_conversation(external_input(), MockProvider()))


def test_customer_volunteered_security_question_cannot_alone_support_discovery_score():
    data = wire_report()
    data["dimensions"]["discovery_questions"].update(score=5, evidence=[{"turn_id": "t0005"}])
    report = extract_report(json.dumps(data), external_input())
    with pytest.raises(ReportValidationError, match="verified salesperson evidence"):
        validate_evidence(report, external_input())


def test_mocked_final_state_and_missed_discovery_survive_exact_extraction():
    """Tests plumbing for authored judgments, not real-model compliance or score calibration."""
    source = external_input().model_copy(update={"sufficiently_complete": True})
    data = wire_report()
    data["dimensions"]["discovery_questions"].update(
        score=2, reason="The systems question is narrow; workload, impact and measurable success were not investigated.",
        evidence=[{"turn_id": "t0002"}])
    data["outcome"] = {"text": "Customer reports document receipt, acceptance and completed signup.", "evidence": [{"turn_id": "t0009"}]}
    data["next_steps"] = [{"text": "Onboarding team to contact the customer within three business days to arrange kickoff; date not confirmed.", "evidence": [{"turn_id": "t0010"}]}]
    data["open_questions"] = []
    data["improvements"] = [
        {"suggestion": "Investigate workload and business impact before assuming fit.",
         "why_it_matters": "Systems alone do not establish operational value.",
         "suggested_phrasing": "What ticket volume do you handle, and what impact do delays have on your team?",
         "evidence": [{"turn_id": "t0002"}]},
        {"suggestion": "Agree a measurable success criterion before recommending automation.",
         "why_it_matters": "A claimed automation rate is not a measured customer outcome.",
         "suggested_phrasing": "Which measurable result would make a pilot successful, and how should we evaluate it?",
         "evidence": [{"turn_id": "t0004"}]},
    ]
    data["fewer_improvements_reason"] = None
    class MockProvider:
        max_attempts = 1
        calls = 0
        async def generate(self, messages, schema):
            self.calls += 1
            received = json.loads(messages[1]["content"])["source_turns"]
            assert received[8]["text"] == source_turns(source)[8]["text"]
            assert received[8]["role"] == "customer"
            return json.dumps(data)
    provider = MockProvider()
    report = asyncio.run(analyze_conversation(source, provider)).report
    assert provider.calls == 1
    assert report.dimensions.discovery_questions.score == 2
    assert report.dimensions.discovery_questions.evidence[0].role == "salesperson"
    assert report.outcome.evidence[0].quote == source_turns(source)[8]["text"]
    assert len(report.next_steps) == 1 and "arrange kickoff" in report.next_steps[0].text
    assert "receipt" not in report.next_steps[0].text and "signup" not in report.next_steps[0].text
    assert len(report.improvements) == 2
    assert all("receipt" not in item.suggestion and "signup" not in item.suggestion for item in report.improvements)
    validate_evidence(report, source)


def test_provenance_validation_does_not_pretend_to_judge_inflated_scores():
    """Explicit boundary: exact source/role evidence alone cannot establish excellence."""
    data = wire_report()
    data["dimensions"]["discovery_questions"].update(
        score=5, reason="Authored inflated judgment; not a semantic oracle.", evidence=[{"turn_id": "t0002"}])
    validate_evidence(extract_report(json.dumps(data), external_input()), external_input())
