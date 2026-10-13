import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.external_evaluation import external_input
from app.services.coaching import CoachingError, analyze_conversation
from app.services.evidence_references import generation_schema
from app.services.llm_provider import OllamaProvider, ProviderError
from app.services.openai_provider import OpenAIProvider, create_provider
from app.services.spending import SpendingLedger, cost_micro_usd


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, openai_api_key="mock-key", spending_ledger_path=tmp_path / "ledger.sqlite3")


def envelope(**updates):
    data = {"model": "gpt-4.1-mini-2025-04-14", "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "choices": [{"finish_reason": "stop", "message": {"content": "{}", "refusal": None}}]}
    data.update(updates)
    return data


def run_provider(settings, handler, *, schema=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIProvider(settings, client, call_id="test")
            raw = await provider.generate([{"role": "user", "content": "hello"}], schema or {})
            return raw, provider
    return asyncio.run(run())


def test_structured_request_and_actual_usage(settings):
    def handler(request):
        assert request.url == "https://api.openai.com/v1/chat/completions"
        payload = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer mock-key"
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["response_format"]["json_schema"]["schema"] == generation_schema()
        assert payload["max_completion_tokens"] == 4096
        return httpx.Response(200, json=envelope())
    raw, provider = run_provider(settings, handler, schema=generation_schema())
    assert raw == "{}"
    assert provider.metadata["input_tokens"] == 100
    assert provider.metadata["estimated_cost_usd"] == 0.00012
    assert provider.ledger.summary()["remaining_budget_usd"] == 4.99988


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_errors_do_not_retry(settings, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "private provider payload"})
    with pytest.raises(ProviderError, match=f"HTTP {status}") as caught:
        run_provider(settings, handler)
    assert "private" not in str(caught.value)
    assert len(calls) == 1
    assert SpendingLedger(settings).summary()["tracked_cost_usd"] > 0


def test_timeout_is_reserved_persistently_and_cannot_repeat(settings):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret-free mocked timeout", request=request)
    with pytest.raises(ProviderError, match="No retry"):
        run_provider(settings, handler)
    ledger = SpendingLedger(settings)
    assert ledger.summary()["calls"] == 1
    with pytest.raises(ProviderError, match="already attempted"):
        run_provider(settings, handler)
    assert len(calls) == 1
    with ledger.connect() as db:
        assert db.execute("SELECT status,input_tokens FROM spending").fetchone() == ("reserved_or_uncertain", None)


@pytest.mark.parametrize("failure", ["length", "refusal", "model", "usage", "envelope"])
def test_invalid_envelopes(settings, failure):
    data = envelope()
    if failure == "length": data["choices"][0]["finish_reason"] = "length"
    if failure == "refusal": data["choices"][0]["message"]["refusal"] = "Cannot comply"
    if failure == "model": data["model"] = "other-model"
    if failure == "usage": data["usage"]["prompt_tokens"] = -1
    if failure == "envelope": data = {}
    with pytest.raises(ProviderError):
        run_provider(settings, lambda request: httpx.Response(200, json=data))


def test_bad_report_never_triggers_paid_repair(settings):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=envelope())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await analyze_conversation(external_input(), OpenAIProvider(settings, client))
    with pytest.raises(CoachingError, match="1 attempt"):
        asyncio.run(run())
    assert len(calls) == 1


def test_budget_preserves_reserve_and_accounts_for_multiple_attempts(settings):
    ledger = SpendingLedger(settings)
    # $3.20 outstanding uncertainty leaves $0.80 usable before the $1 reserve.
    ledger.reserve("prior", 8000000, 0)
    with pytest.raises(ProviderError, match="reserve"):
        ledger.reserve("repair", 0, 600000)  # $0.96 cannot be spent.
    assert SpendingLedger(settings).summary()["remaining_budget_usd"] == 1.8
    ledger.reserve("small", 100, 100)
    with pytest.raises(ProviderError, match="already attempted"):
        ledger.reserve("small", 100, 100)


def test_blocked_budget_never_contacts_provider(settings):
    SpendingLedger(settings).reserve("prior", 10000000, 0)
    with pytest.raises(ProviderError, match="reserve"):
        run_provider(settings, lambda request: pytest.fail("Network must not run"))


def test_input_cap_rejects_without_truncation(settings):
    settings.openai_max_input_tokens = 10
    with pytest.raises(ProviderError, match="token limit"):
        run_provider(settings, lambda request: pytest.fail("Network must not run"))
    assert SpendingLedger(settings).summary()["calls"] == 0


def test_missing_key_never_contacts_provider(settings):
    settings.openai_api_key = None
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        run_provider(settings, lambda request: pytest.fail("Network must not run"))


def test_provider_selection_and_root_env(tmp_path):
    env = tmp_path / "config.env"
    env.write_text("LLM_PROVIDER=openai\nOPENAI_MODEL=gpt-4.1-mini\nOPENAI_API_KEY=fixture-key\nSPENDING_LEDGER_PATH=" + str(tmp_path / "ledger.db"))
    config = Settings(_env_file=env)
    with httpx.Client() as client:
        assert isinstance(create_provider(config, client), OpenAIProvider)
        assert config.openai_api_key.get_secret_value() == "fixture-key"
        assert "fixture-key" not in repr(config)
        config.llm_provider = "ollama"
        assert isinstance(create_provider(config, client), OllamaProvider)


@pytest.mark.parametrize("kwargs", [{"budget_usd": 6}, {"budget_reserve_usd": 0}, {"openai_model": "other"}, {"openai_max_output_tokens": 10000}])
def test_configuration_protection(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_external_roles_and_contents_preserved():
    from app.external_evaluation import FIXTURE
    record = json.loads(FIXTURE.read_text())
    source = external_input()
    assert len(source.verified_turns) == len(record["messages"]) == 15
    for turn, message in zip(source.verified_turns, record["messages"]):
        assert source.transcript[turn.start:turn.end] == message["content"]
        assert turn.role == {"a": "salesperson", "b": "customer"}[message["role"]]


def test_money_rounds_up_and_settlement_is_once(settings):
    assert cost_micro_usd(1, 0) == 1
    ledger = SpendingLedger(settings)
    ledger.reserve("test", 100, 100)
    assert ledger.settle("test", 10, 5) == 12
    with pytest.raises(ProviderError): ledger.settle("test", 10, 5)


def test_full_fixture_workflow_context_fits_input_budget_without_truncation(settings):
    """Exercise the actual provider payload/guard with the failed attempt's context."""
    source = external_input().model_copy(update={
        "objective": "Qualify enterprise helpdesk fit before peak season, address integration and security requirements, and agree appropriate next steps.",
        "customer_context": json.dumps({
            "company": "Fictional ecommerce support team",
            "relevant_needs": "Automate order tracking and returns before holiday rush; integrate Shopify/Zendesk; security review required.",
            "previous_interactions": "None known before this synthetic conversation.",
        }),
        "sufficiently_complete": True,
    })
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        estimate = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 2048
        assert settings.openai_max_input_tokens == 24000
        assert estimate <= settings.openai_max_input_tokens - 300
        supplied = json.loads(payload["messages"][1]["content"])
        assert supplied["input_data"]["customer_context"] == source.customer_context
        assert supplied["input_data"]["objective"] == source.objective
        from app.services.evidence_references import turn_catalogue
        assert supplied["source_turns"] == turn_catalogue(source)
        assert payload["response_format"]["json_schema"]["schema"] == generation_schema()
        calls.append(request)
        return httpx.Response(200, json=envelope())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await analyze_conversation(source, OpenAIProvider(settings, client))
    # Intentionally malformed mocked output still fails validation without repair.
    with pytest.raises(CoachingError, match="1 attempt"):
        asyncio.run(run())
    assert len(calls) == 1
