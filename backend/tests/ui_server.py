"""Isolated browser-acceptance server: all Notion and LLM calls are mocked.

Launch with PYTHONPATH=backend:backend/tests; never use this module as the app.
"""

import tempfile
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app, get_notion_client
from app.services.notion_client import NotionClient
from test_notion_import import MEETING, PAGE, ROOT, TEXT, block_list, paragraph
from test_workflow import MockProvider

# A new process gets clean storage without touching the real project databases.
storage = tempfile.TemporaryDirectory(prefix="intellegam-ui-test-")
settings = Settings(
    _env_file=None,
    llm_provider="ollama",
    database_path=Path(storage.name) / "coaching.sqlite3",
    spending_ledger_path=Path(storage.name) / "spending.sqlite3",
)
app = create_app(settings, provider_factory=lambda *args, **kwargs: MockProvider())
responses = {
    f"/pages/{PAGE}": {"object": "page", "id": PAGE},
    f"/blocks/{PAGE}/children": block_list([{
        "object": "block", "id": MEETING, "type": "meeting_notes", "has_children": True,
        "meeting_notes": {
            "title": [{"plain_text": "Mocked native meeting - UI acceptance test"}],
            "status": "notes_ready", "children": {"transcript_block_id": ROOT},
        },
    }]),
    f"/blocks/{ROOT}": paragraph(ROOT, "", True),
    f"/blocks/{ROOT}/children": block_list([paragraph(TEXT,
        "We need to reduce support ticket delays before peak season. Security review "
        "is a prerequisite, and next-step ownership needs clarification.")]),
}


async def mocked_notion():
    async with httpx.AsyncClient(base_url="https://mock.notion.test/", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=responses[request.url.path])
    )) as client:
        yield NotionClient(client)


app.dependency_overrides[get_notion_client] = mocked_notion
