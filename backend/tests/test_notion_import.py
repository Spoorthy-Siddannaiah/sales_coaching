"""Contract tests composed from official block/list examples.

The meeting_notes pointer is documented. Paragraph transcript children below
exercise generic documented rich text; they are NOT observed native responses
and do not prove the actual transcript format or speaker attribution.
"""

import copy
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.notion_client import NotionImportError
from app.services.notion_import import parse_page_id

PAGE = "11111111-1111-4111-8111-111111111111"
MEETING = "22222222-2222-4222-8222-222222222222"
ROOT = "33333333-3333-4333-8333-333333333333"
TEXT = "44444444-4444-4444-8444-444444444444"
OTHER = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def retry_waits(monkeypatch):
    """Exercise the retry policy without wall-clock waits or real requests."""
    waits = []
    async def record_sleep(delay):
        waits.append(delay)
    monkeypatch.setattr("app.services.notion_client.sleep", record_sleep)
    return waits


def paragraph(identifier: str, text: str, has_children: bool = False) -> dict[str, Any]:
    return {"object": "block", "id": identifier, "type": "paragraph", "has_children": has_children,
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}, "plain_text": text}]}}


def block_list(blocks: list[dict[str, Any]], cursor: str | None = None) -> dict[str, Any]:
    return {"object": "list", "results": blocks, "has_more": cursor is not None, "next_cursor": cursor}


@pytest.fixture
def native_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    meeting = {"object": "block", "id": MEETING, "type": "meeting_notes", "has_children": True,
               "meeting_notes": {"title": [{"plain_text": "Test meeting"}], "status": "notes_ready",
                                 "children": {"transcript_block_id": ROOT}}}
    responses = {
        f"/v1/pages/{PAGE}": {"object": "page", "id": PAGE},
        f"/v1/blocks/{PAGE}/children": block_list([meeting]),
        f"/v1/blocks/{ROOT}": paragraph(ROOT, "", True),
        f"/v1/blocks/{ROOT}/children": block_list([paragraph(TEXT, "We need a simpler onboarding process.")]),
    }
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        key = request.url.path + ("?" + request.url.params["start_cursor"] if "start_cursor" in request.url.params else "")
        result = responses[key]  # An unexpected request must fail the test.
        if isinstance(result, Exception):
            raise result
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handler)))
    path = tmp_path / "test.sqlite3"
    settings = Settings(_env_file=None, database_path=path, notion_api_token="fake-test-token")
    with TestClient(create_app(settings)) as client:
        yield client, responses, calls, path


def post(client: TestClient) -> httpx.Response:
    return client.post("/imports/notion", json={"page": PAGE})


def test_native_contract_retrieval_and_snapshot(native_api) -> None:
    client, responses, calls, path = native_api
    response = post(client)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["reused"] is False
    assert result["transcript"]["original_text"] == "We need a simpler onboarding process."
    assert result["transcript"]["turns"] == []
    assert result["speaker_attribution"] == "unavailable"
    assert result["turn_timestamps"] == "unavailable"
    assert result["transcript"]["source_metadata"]["snapshot"]["transcript_root"] == responses[f"/v1/blocks/{ROOT}"]
    assert all(request.headers["Authorization"] == "Bearer fake-test-token" for request in calls)
    assert all(request.headers["Notion-Version"] == "2026-03-11" for request in calls)
    assert "fake-test-token" not in response.text
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transcript_versions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0


def test_missing_transcript_reference(native_api) -> None:
    client, responses, _, path = native_api
    del responses[f"/v1/blocks/{PAGE}/children"]["results"][0]["meeting_notes"]["children"]["transcript_block_id"]
    response = post(client)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "transcript_reference_missing"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0


@pytest.mark.parametrize("status, expected_code", [(401, "notion_unauthorized"), (403, "notion_forbidden"), (404, "notion_not_found"), (429, "notion_rate_limited"), (500, "notion_api_error")])
def test_provider_errors(native_api, status: int, expected_code: str) -> None:
    client, responses, _, _ = native_api
    responses[f"/v1/blocks/{ROOT}"] = httpx.Response(status, json={"object": "error", "message": "provider-private-text"})
    response = post(client)
    assert response.status_code == (502 if status == 500 else status)
    assert response.json()["detail"]["code"] == expected_code
    assert "provider-private-text" not in response.text


def test_empty_native_transcript(native_api) -> None:
    client, responses, _, _ = native_api
    responses[f"/v1/blocks/{ROOT}/children"] = block_list([])
    response = post(client)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "empty_transcript"


def test_page_discovery_and_transcript_pagination_and_nesting(native_api) -> None:
    client, responses, _, _ = native_api
    meeting = copy.deepcopy(responses[f"/v1/blocks/{PAGE}/children"]["results"][0])
    responses[f"/v1/blocks/{PAGE}/children"] = block_list([], "page-next")
    responses[f"/v1/blocks/{PAGE}/children?page-next"] = block_list([meeting])
    responses[f"/v1/blocks/{ROOT}/children"] = block_list([paragraph(TEXT, "First", True)], "next")
    responses[f"/v1/blocks/{TEXT}/children"] = block_list([paragraph(OTHER, "Nested")])
    responses[f"/v1/blocks/{ROOT}/children?next"] = block_list([paragraph("66666666-6666-4666-8666-666666666666", "Last")])
    response = post(client)
    assert response.status_code == 200, response.text
    assert response.json()["transcript"]["original_text"] == "First\nNested\nLast"


def test_duplicates_and_changed_content(native_api) -> None:
    client, responses, _, path = native_api
    first = post(client).json()
    # Observed live: Retrieve a block adds a new request_id on each response.
    responses[f"/v1/blocks/{ROOT}"]["request_id"] = "different-request"
    second = post(client).json()
    assert second["reused"] is True
    assert first["transcript"]["id"] == second["transcript"]["id"]
    responses[f"/v1/blocks/{ROOT}/children"] = block_list([paragraph(TEXT, "Changed content")])
    third = post(client).json()
    assert third["reused"] is False
    assert third["transcript"]["id"] != first["transcript"]["id"]
    assert third["conversation"]["id"] == first["conversation"]["id"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM transcript_versions").fetchone()[0] == 2


def test_timeout(native_api) -> None:
    client, responses, _, _ = native_api
    responses[f"/v1/blocks/{ROOT}"] = httpx.ReadTimeout("sensitive-provider-detail")
    response = post(client)
    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "notion_timeout"
    assert "sensitive-provider-detail" not in response.text


def test_unknown_transcript_structure_is_not_silently_skipped(native_api) -> None:
    client, responses, _, path = native_api
    responses[f"/v1/blocks/{ROOT}/children"] = block_list([{"object": "block", "id": TEXT, "type": "unsupported", "has_children": False, "unsupported": {}}])
    response = post(client)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_structure"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transcript_versions").fetchone()[0] == 0


def test_ordinary_page_rejected(native_api) -> None:
    client, responses, _, _ = native_api
    responses[f"/v1/blocks/{PAGE}/children"] = block_list([paragraph(TEXT, "Sales: Hello")])
    response = post(client)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "native_meeting_missing"


def test_not_ready_and_multiple_meetings(native_api) -> None:
    client, responses, _, _ = native_api
    blocks = responses[f"/v1/blocks/{PAGE}/children"]["results"]
    blocks[0]["meeting_notes"]["status"] = "transcription_in_progress"
    assert post(client).status_code == 409
    blocks.append(copy.deepcopy(blocks[0]))
    assert post(client).json()["detail"]["code"] == "ambiguous_meeting"


def test_native_discovery_in_nested_container(native_api) -> None:
    client, responses, _, _ = native_api
    meeting = responses[f"/v1/blocks/{PAGE}/children"]["results"][0]
    container = {"object": "block", "id": OTHER, "type": "toggle", "has_children": True,
                 "toggle": {"rich_text": []}}
    responses[f"/v1/blocks/{PAGE}/children"] = block_list([container])
    responses[f"/v1/blocks/{OTHER}/children"] = block_list([meeting])
    assert post(client).status_code == 200
    # Unrelated discovery-container edits must not create a new transcript version.
    container["toggle"]["rich_text"] = [{"plain_text": "Changed page layout"}]
    assert post(client).json()["reused"] is True


def test_bad_pagination_does_not_save_partial_content(native_api) -> None:
    client, responses, _, path = native_api
    responses[f"/v1/blocks/{ROOT}/children"]["has_more"] = True
    response = post(client)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "unsupported_structure"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0


def test_invalid_json_and_connection_errors(native_api) -> None:
    client, responses, _, _ = native_api
    responses[f"/v1/blocks/{ROOT}"] = httpx.Response(200, text="not-json")
    assert post(client).json()["detail"]["code"] == "invalid_notion_response"
    responses[f"/v1/blocks/{ROOT}"] = httpx.ConnectError("private-details")
    assert post(client).json()["detail"]["code"] == "notion_connection"


def test_missing_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTION_API_TOKEN", raising=False)
    with TestClient(create_app(Settings(_env_file=None, database_path=tmp_path / "test.sqlite3"))) as client:
        response = post(client)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "notion_not_configured"


@pytest.mark.parametrize("value", [PAGE, PAGE.replace("-", ""), f"https://www.notion.so/Test-{PAGE.replace('-', '')}?pvs=4", f"https://workspace.notion.site/{PAGE}", f"https://app.notion.com/p/{PAGE.replace('-', '')}?source=copy_link"])
def test_page_id_and_url_parsing(value: str) -> None:
    assert parse_page_id(value) == PAGE


@pytest.mark.parametrize("value", ["", "bad-id", "https://[", "https://example.com/" + PAGE, "https://notion.so.evil.test/" + PAGE, "https://app.notion.com.evil.test/p/" + PAGE])
def test_invalid_page_ids(value: str) -> None:
    with pytest.raises(NotionImportError) as error:
        parse_page_id(value)
    assert error.value.status_code == 422


@pytest.mark.parametrize("previous_success", [False, True])
def test_second_page_failure_never_saves_partial_import(native_api, previous_success):
    client, responses, _, path = native_api
    original = post(client).json() if previous_success else None
    responses[f"/v1/blocks/{ROOT}/children"] = block_list([paragraph(TEXT, "Partial changed text")], "next")
    responses[f"/v1/blocks/{ROOT}/children?next"] = httpx.Response(503, text="PRIVATE token=fake-test-token")
    result = post(client)
    assert result.status_code == 502
    assert "PRIVATE" not in result.text and "fake-test-token" not in result.text
    with sqlite3.connect(path) as db:
        for table in ("conversations", "transcript_versions"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == int(previous_success)
        assert db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0
        if original:
            assert db.execute("SELECT original_text FROM transcript_versions").fetchone()[0] == original["transcript"]["original_text"]
    if original is None:
        response = client.post(f"/conversations/{PAGE}/analyses", json={"request_id": PAGE, "allow_paid": True})
        assert response.status_code == 404


def test_nested_transcript_children_are_paginated_in_order(native_api):
    client, responses, calls, _ = native_api
    responses[f"/v1/blocks/{ROOT}/children"] = block_list([paragraph(TEXT, "Parent", True)])
    responses[f"/v1/blocks/{TEXT}/children"] = block_list([paragraph(OTHER, "Nested first")], "nested-next")
    responses[f"/v1/blocks/{TEXT}/children?nested-next"] = block_list([paragraph("66666666-6666-4666-8666-666666666666", "Nested last")])
    result = post(client)
    assert result.status_code == 200
    assert result.json()["transcript"]["original_text"] == "Parent\nNested first\nNested last"
    assert any(r.url.params.get("start_cursor") == "nested-next" for r in calls)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_get_retries_then_succeeds_without_sensitive_errors(status, retry_waits):
    from app.services.notion_client import NotionClient
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "2"}, text="PRIVATE") if len(calls) == 1 else httpx.Response(200, json={"object": "page"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await NotionClient(http).get("https://api.notion.com/v1/pages/test")
    assert asyncio.run(run()) == {"object": "page"}
    assert len(calls) == 2 and retry_waits == [2]
    assert all(r.method == "GET" for r in calls)


@pytest.mark.parametrize("header", ["999", "11"])
def test_retry_after_exceeding_wait_budget_stops_without_shortening(header, retry_waits):
    from app.services.notion_client import NotionClient
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": header}, text="PRIVATE")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await NotionClient(http).get("https://api.notion.com/v1/pages/test")
    with pytest.raises(NotionImportError) as error:
        asyncio.run(run())
    assert error.value.code == "notion_rate_limited"
    assert len(calls) == 1 and not retry_waits


@pytest.mark.parametrize("header", [None, "invalid", "NaN", "-1"])
def test_rate_limit_exhaustion_is_bounded_with_invalid_or_missing_header(header, retry_waits):
    from app.services.notion_client import NotionClient
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={} if header is None else {"Retry-After": header}, text="PRIVATE")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await NotionClient(http).get("https://api.notion.com/v1/pages/test")
    with pytest.raises(NotionImportError):
        asyncio.run(run())
    assert len(calls) == 3 and len(retry_waits) == 2
    assert .5 <= retry_waits[0] <= .6 and 1 <= retry_waits[1] <= 1.1


def test_retry_budget_is_shared_across_pages(retry_waits):
    from app.services.notion_client import NotionClient
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "4"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            notion = NotionClient(http)
            for _ in range(2):
                with pytest.raises(NotionImportError):
                    await notion.get("https://api.notion.com/v1/pages/test")
            assert notion.wait_remaining == 2
    asyncio.run(run())
    assert retry_waits == [4, 4]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_auth_and_access_errors_are_not_retried(native_api, status, retry_waits):
    client, responses, calls, _ = native_api
    responses[f"/v1/pages/{PAGE}"] = httpx.Response(status, text="PRIVATE")
    assert post(client).status_code == status
    assert len(calls) == 1 and not retry_waits


def test_concurrent_imports_reuse_one_conversation_and_version(native_api):
    from app.services.notion_client import NotionClient
    from app.services.notion_import import import_native_transcript
    _, _, _, path = native_api
    def run(_):
        async def imported():
            # Fixture replaces this client's transport with mocked Notion responses.
            async with httpx.AsyncClient(base_url="https://api.notion.com/v1") as http:
                return await import_native_transcript(NotionClient(http), path, PAGE, "2026-03-11")
        return asyncio.run(imported())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(8)))
    assert len({r.conversation.id for r in results}) == 1
    assert len({r.transcript.id for r in results}) == 1
    assert sum(not r.reused for r in results) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM transcript_versions").fetchone()[0] == 1


def test_long_import_preserved_but_analysis_rejected_before_creation(native_api):
    from uuid import uuid4
    client, responses, _, path = native_api
    text = "Original source content. " * 800
    responses[f"/v1/blocks/{ROOT}/children"] = block_list([paragraph(TEXT, text)])
    saved = post(client).json()
    identifier = saved["conversation"]["id"]
    assert saved["transcript"]["original_text"] == text
    assert client.put(f"/conversations/{identifier}/context", json={"company": "Test", "relevant_needs": "Test workflow", "previous_interactions": "None", "objective": "Test import"}).status_code == 200
    response = client.post(f"/conversations/{identifier}/analyses", json={"request_id": str(uuid4()), "allow_paid": True})
    assert response.status_code == 422
    assert "16,000" in response.json()["detail"] and "complete transcript is saved" in response.json()["detail"]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT original_text FROM transcript_versions").fetchone()[0] == text
        assert db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0


def test_storage_failure_rolls_back_conversation_and_version(native_api):
    client, _, _, path = native_api
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER refuse_version BEFORE INSERT ON transcript_versions BEGIN SELECT RAISE(ABORT, 'PRIVATE'); END")
    response = post(client)
    assert response.status_code == 503
    assert "PRIVATE" not in response.text
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM transcript_versions").fetchone()[0] == 0


def test_pagination_limit_still_rejects_without_partial_save(native_api):
    client, responses, calls, path = native_api
    responses[f"/v1/blocks/{ROOT}/children"] = block_list([paragraph(TEXT, "Partial")], "cursor-1")
    for page in range(1, 100):
        responses[f"/v1/blocks/{ROOT}/children?cursor-{page}"] = block_list([], f"cursor-{page + 1}")
    response = post(client)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "source_too_large"
    assert sum(r.url.path == f"/v1/blocks/{ROOT}/children" for r in calls) == 100
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM transcript_versions").fetchone()[0] == 0


def test_same_source_url_and_uuid_reuse_same_version(native_api):
    client, _, _, _ = native_api
    first = post(client).json()
    second = client.post("/imports/notion", json={"page": f"https://app.notion.com/p/Meeting-{PAGE.replace('-', '')}?source=copy_link"}).json()
    assert second["reused"] is True
    assert second["conversation"]["id"] == first["conversation"]["id"]
    assert second["transcript"]["id"] == first["transcript"]["id"]


def test_retry_after_http_date_is_honored(retry_waits):
    from datetime import datetime, timezone, timedelta
    from email.utils import format_datetime
    from app.services.notion_client import NotionClient
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": format_datetime(datetime.now(timezone.utc) + timedelta(seconds=3), usegmt=True)}) if len(calls) == 1 else httpx.Response(200, json={"object": "page"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await NotionClient(http).get("https://api.notion.com/v1/pages/test")
    asyncio.run(run())
    assert len(calls) == 2 and 1.5 < retry_waits[0] <= 3


def test_global_retry_count_is_bounded_even_with_zero_retry_after(retry_waits):
    from app.services.notion_client import NotionClient
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            notion = NotionClient(http)
            for _ in range(4):
                with pytest.raises(NotionImportError):
                    await notion.get("https://api.notion.com/v1/pages/test")
    asyncio.run(run())
    assert len(retry_waits) == 5 and len(calls) == 9
