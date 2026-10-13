"""End-to-end application tests with mocked generation and temporary storage."""

import asyncio
import hashlib
import json
import sqlite3
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import LEGACY_SCHEMA, connect_database, initialize_database
from app.main import create_app
from app.repositories import analyses, conversations
from app.services.analysis_workflow import coaching_input
from app.services.coaching import CoachingError, PROMPT_VERSION, SYSTEM_PROMPT, analyze_conversation
from app.services.coaching_models import CoachingReport
from app.services.evidence_validator import validate_evidence
from app.services.llm_provider import ProviderError
from app.workflow_models import CustomerContext

CONTEXT = {"company": "Fictional Example", "relevant_needs": "Reduce support delays", "previous_interactions": "None known", "objective": "Qualify rollout and next steps"}


class MockProvider:
    max_attempts = 1

    def __init__(self, *, failure=None, gate=None):
        self.failure, self.gate = failure, gate
        self.calls = []

    async def generate(self, messages, schema):
        self.calls.append(json.loads(messages[1]["content"]))
        while self.gate is not None and not self.gate[0]:
            await asyncio.sleep(.01)
        if self.failure == "provider":
            raise ProviderError("Mock provider timed out. No retry.")
        payload = self.calls[-1]
        turns = payload["source_turns"]
        full = any(t["role"] is not None for t in turns)
        sales = next((t for t in turns if t["role"] == "salesperson"), turns[0])
        evidence = [{"turn_id": sales["turn_id"], }]
        if self.failure == "evidence": evidence[0]["turn_id"] = "t9999"
        finding = {"text": "Mock observation for " + payload["input_data"]["objective"], "evidence": evidence}
        dimensions = {name: {"score": 3 if full else None, "reason": "Mocked score; not a live quality evaluation.", "evidence": evidence}
                      for name in CoachingReport.model_fields["dimensions"].annotation.model_fields}
        improvements = [{"suggestion": suggestion, "why_it_matters": "Supports " + payload["input_data"]["objective"],
                         "suggested_phrasing": phrasing, "evidence": evidence}
                        for suggestion, phrasing in [("Quantify success", "What outcome would make this worthwhile?"),
                                                     ("Confirm follow-up ownership", "Who should own the next action?")]] if full else []
        if self.failure == "one_improvement": improvements = improvements[:1]
        return json.dumps({"source_version": payload["source_version"], "mode": "full" if full else "limited", "summary": finding,
            "customer_needs_and_pain_points": [], "outcome": None, "questions_asked": [], "open_questions": [], "next_steps": [],
            "dimensions": dimensions, "strengths": [], "improvements": improvements,
            "fewer_improvements_reason": "Insufficient attributed evidence." if len(improvements) < 2 else None,
            "evidence_limitations": ["Mocked output, not a live coaching report."] + ([] if full else ["Speaker attribution is unavailable; insufficient evidence for salesperson feedback."])})


def config(tmp_path, provider="ollama"):
    return Settings(_env_file=None, database_path=tmp_path / "app.sqlite3", spending_ledger_path=tmp_path / "spending.sqlite3", llm_provider=provider)


def terminal(client, identifier):
    for _ in range(100):
        response = client.get("/analyses/" + identifier)
        assert response.status_code == 200
        if response.json()["status"] in ("completed", "failed"): return response.json()
        time.sleep(.01)
    pytest.fail("Mock job did not finish")


def fixture(client):
    response = client.post("/imports/fixture", json={"fixture": "kapibala"})
    assert response.status_code == 200
    return response.json()["conversation"]


def start(client, identifier, *, request_id=None, allow_paid=False):
    return client.post(f"/conversations/{identifier}/analyses", json={"request_id": request_id or str(uuid4()), "allow_paid": allow_paid})


def test_fixture_complete_flow_context_snapshots_and_restart(tmp_path):
    settings, provider = config(tmp_path), MockProvider()
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        saved = fixture(client)
        identifier = saved["id"]
        original = saved["transcript"]["original_text"]
        assert saved["provider"] == "offline_fixture"
        assert saved["transcript"]["source_metadata"]["synthetic"] is True
        assert client.post("/imports/fixture", json={}).json()["reused"] is True
        assert len(client.get("/conversations").json()) == 1
        assert client.put(f"/conversations/{identifier}/context", json=CONTEXT).status_code == 200
        request_id = str(uuid4())
        first = start(client, identifier, request_id=request_id)
        assert first.status_code == 202
        result = terminal(client, first.json()["id"])
        assert result["status"] == "completed"
        assert len(result["report"]["improvements"]) == 2
        assert result["customer_context"] == CONTEXT
        assert result["salesperson"] is None  # Roles are known; personal names are not invented.
        source = coaching_input(client.get(f"/conversations/{identifier}").json())
        validate_evidence(CoachingReport.model_validate(result["report"]), source)
        assert start(client, identifier, request_id=request_id).json()["id"] == result["id"]
        assert len(provider.calls) == 1
        changed = dict(CONTEXT, objective="Evaluate security prerequisites")
        client.put(f"/conversations/{identifier}/context", json=changed)
        second = terminal(client, start(client, identifier).json()["id"])
        assert second["report"]["summary"]["text"] != result["report"]["summary"]["text"]
        assert result["objective"] == CONTEXT["objective"]
        assert provider.calls[-1]["input_data"]["objective"] == changed["objective"]
        assert client.get(f"/conversations/{identifier}").json()["transcript"]["original_text"] == original
    with TestClient(create_app(settings, lambda *a, **k: provider)) as restarted:
        assert restarted.get("/analyses/" + result["id"]).json()["report"] == result["report"]
        assert len(restarted.get(f"/conversations/{identifier}").json()["analyses"]) == 2
    assert len(provider.calls) == 2


def test_notional_saved_native_source_is_limited_without_role_inference(tmp_path):
    settings, provider = config(tmp_path), MockProvider()
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        text = "Salesperson: visible labels alone do not verify speakers.\nCustomer: we need help improving support before peak season."
        with connect_database(settings.database_path) as db:
            db.execute("INSERT INTO conversations (id,provider,source_id,title,created_at) VALUES ('native','notion','page','Native','now')")
            db.execute("INSERT INTO transcript_versions (id,conversation_id,content_hash,original_text,imported_at) VALUES ('native-t','native','hash',?,'now')", (text,))
        assert start(client, "native").status_code == 422
        client.put("/conversations/native/context", json=CONTEXT)
        completed = terminal(client, start(client, "native").json()["id"])
        assert completed["status"] == "completed"
        report = completed["report"]
        assert report["mode"] == "limited"
        assert all(d["score"] is None for d in report["dimensions"].values())
        assert report["improvements"] == []
        assert report["fewer_improvements_reason"]
        assert all(t["role"] is None for t in provider.calls[0]["source_turns"])


@pytest.mark.parametrize("failure", ["provider", "evidence", "one_improvement"])
def test_analysis_failure_is_saved_without_retry_or_false_report(tmp_path, failure):
    provider, settings = MockProvider(failure=failure), config(tmp_path)
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        saved = fixture(client)
        response = start(client, saved["id"])
        result = terminal(client, response.json()["id"])
        assert result["status"] == "failed" and result["report"] is None
        assert result["error_message"] and len(provider.calls) == 1
        assert client.get(f"/conversations/{saved['id']}").json()["transcript"]["original_text"] == saved["transcript"]["original_text"]


def test_polling_pending_analyzing_single_job_and_shutdown(tmp_path):
    gate, provider = [False], None
    provider = MockProvider(gate=gate)
    settings = config(tmp_path)
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        saved = fixture(client)
        request_id = str(uuid4())
        response = start(client, saved["id"], request_id=request_id)
        assert response.json()["status"] == "pending"
        for _ in range(50):
            running = client.get("/analyses/" + request_id).json()
            if running["status"] == "analyzing": break
            time.sleep(.01)
        assert running["status"] == "analyzing"
        assert start(client, saved["id"]).status_code == 409
        assert start(client, saved["id"], request_id=request_id).json()["id"] == request_id
        assert len(provider.calls) == 1
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        assert client.get("/analyses/" + request_id).json()["status"] == "failed"
        assert len(provider.calls) == 1


def test_stale_pending_is_failed_on_startup_without_provider_call(tmp_path):
    settings = config(tmp_path)
    initialize_database(settings.database_path)
    from app.services.fixture_import import import_fixture
    saved = import_fixture(settings.database_path, "kapibala")["conversation"]
    identifier = str(uuid4())
    analyses.create_analysis(settings.database_path, identifier, saved["transcript"]["id"], CONTEXT, "openai", "gpt-4.1-mini")
    with TestClient(create_app(settings, lambda *a, **k: pytest.fail("No automatic resume"))) as client:
        assert client.get("/analyses/" + identifier).json()["status"] == "failed"


def test_paid_request_requires_explicit_approval_before_execution(tmp_path):
    settings = config(tmp_path, "openai")
    with TestClient(create_app(settings, lambda *a, **k: pytest.fail("Paid call must not run"))) as client:
        saved = fixture(client)
        assert start(client, saved["id"]).status_code == 409
        assert client.get(f"/conversations/{saved['id']}").json()["analyses"] == []


def test_context_and_fixture_validation_and_not_found(tmp_path):
    with TestClient(create_app(config(tmp_path))) as client:
        assert client.get("/conversations/missing").status_code == 404
        assert client.get("/analyses/missing").status_code == 404
        assert client.post("/imports/fixture", json={"fixture": "../../.env"}).status_code == 422
        saved = fixture(client)
        assert client.put(f"/conversations/{saved['id']}/context", json=dict(CONTEXT, company=" ")).status_code == 422
        assert client.put("/conversations/missing/context", json=CONTEXT).status_code == 404
        assert client.get("/runtime").json()["provider"] == "ollama"


def test_migration_preserves_legacy_records_and_creates_backup(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute("INSERT INTO conversations VALUES ('c','notion','page','Original',NULL,'now')")
        db.execute("INSERT INTO transcript_versions (id,conversation_id,content_hash,original_text,imported_at) VALUES ('t','c','h','Exact original\ntext','now')")
        db.execute("INSERT INTO analyses (id,transcript_version_id,customer_context,objective,salesperson,status,model,report,created_at) VALUES ('a','t','{}','Legacy objective','Legacy name','completed','old','{}','now')")
    initialize_database(path)
    initialize_database(path)
    with connect_database(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT original_text FROM transcript_versions").fetchone()[0] == "Exact original\ntext"
        assert db.execute("SELECT report,salesperson FROM analyses").fetchone()[:] == ("{}", "Legacy name")
    assert path.with_name("old.before-workflow.sqlite3").exists()


@pytest.mark.parametrize("failure", [None, "evidence", "provider"])
def test_prompt_identity_persists_for_success_and_failures(tmp_path, failure):
    settings, provider = config(tmp_path), MockProvider(failure=failure)
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        from app.services.evidence_validator import VALIDATOR_VERSION
        runtime = client.get("/runtime").json()
        assert runtime["prompt_version"] == PROMPT_VERSION
        assert runtime["validator_version"] == VALIDATOR_VERSION
        saved = fixture(client)
        result = terminal(client, start(client, saved["id"]).json()["id"])
        assert result["provider_metadata"]["prompt_version"] == PROMPT_VERSION
        assert result["provider_metadata"]["validator_version"] == VALIDATOR_VERSION
        assert result["status"] == ("completed" if failure is None else "failed")
        identifier = result["id"]
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        assert client.get("/analyses/" + identifier).json() == result


def test_prompt_identity_is_content_derived_and_historical_metadata_compatible(tmp_path):
    assert PROMPT_VERSION == "sales-coaching-" + hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:16]
    settings, provider = config(tmp_path), MockProvider()
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        saved = fixture(client)
        result = terminal(client, start(client, saved["id"]).json()["id"])
        # Simulate a historical record in temporary test storage only.
        with connect_database(settings.database_path) as db:
            db.execute("UPDATE analyses SET provider_metadata='{}' WHERE id=?", (result["id"],))
        historical = client.get("/analyses/" + result["id"]).json()
        assert historical["provider_metadata"] == {}
        assert historical["report"] == result["report"]
        assert historical["status"] == "completed"


def test_new_transcript_version_changes_input_without_rewriting_saved_report(tmp_path):
    settings, provider = config(tmp_path), MockProvider()
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        saved = fixture(client)
        first = terminal(client, start(client, saved["id"]).json()["id"])
        old = saved["transcript"]
        # A same-length test-only edit preserves verified span positions.
        changed = old["original_text"].replace("Hi there", "Hi again", 1)
        assert changed != old["original_text"] and len(changed) == len(old["original_text"])
        version = str(uuid4())
        with connect_database(settings.database_path) as db:
            db.execute("""INSERT INTO transcript_versions
                (id,conversation_id,content_hash,original_text,source_metadata,turns,warnings,imported_at)
                VALUES (?,?,?,?,?,?,?,?)""", (version, saved["id"], hashlib.sha256(changed.encode()).hexdigest(),
                changed, json.dumps(old["source_metadata"]), json.dumps(old["turns"]), json.dumps(old["warnings"]),
                "2099-01-01T00:00:00+00:00"))
        second = terminal(client, start(client, saved["id"]).json()["id"])
        assert second["transcript_version_id"] == version
        assert first["transcript_version_id"] != version
        assert provider.calls[0]["source_turns"][0]["text"] != provider.calls[1]["source_turns"][0]["text"]
        assert client.get("/analyses/" + first["id"]).json()["report"] == first["report"]
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        assert client.get(f"/conversations/{saved['id']}").json()["transcript"]["original_text"] == changed
        assert client.get("/analyses/" + first["id"]).json()["report"] == first["report"]


def test_opt_in_diagnostics_are_wired_to_failed_application_attempt(tmp_path):
    settings = config(tmp_path)
    settings.retain_rejected_diagnostics = True
    settings.rejected_diagnostics_path = tmp_path / "diagnostics"
    provider = MockProvider(failure="evidence")
    with TestClient(create_app(settings, lambda *a, **k: provider)) as client:
        saved = fixture(client)
        result = terminal(client, start(client, saved["id"]).json()["id"])
        assert result["status"] == "failed" and result["report"] is None
        diagnostics = list(settings.rejected_diagnostics_path.glob("*.json"))
        assert len(diagnostics) == 1
        payload = json.loads(diagnostics[0].read_text())
        assert payload["prompt_version"] == PROMPT_VERSION
        assert payload["error_type"] == "ReportValidationError"
        assert payload["free_text_retained"] is False
        assert "diagnostics" not in result["error_message"]
