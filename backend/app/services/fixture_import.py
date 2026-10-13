"""An allowlisted public synthetic fixture, never a Notion connection."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.database import connect_database
from app.external_evaluation import FIXTURE, external_input
from app.repositories.conversations import detail, now
from app.workflow_models import CustomerContext


def import_fixture(path: Path, name: str) -> dict:
    if name != "kapibala":
        raise HTTPException(422, detail="Only the allowlisted Kapibala demo fixture is supported.")
    source = external_input()
    source_id = json.loads(FIXTURE.read_text())["id"]
    digest = hashlib.sha256(source.transcript.encode()).hexdigest()
    context = CustomerContext(company="Fictional ecommerce support team",
        relevant_needs="Automate order tracking and returns before holiday rush; integrate Shopify/Zendesk; security review required.",
        previous_interactions="None known before this synthetic conversation.", objective=source.objective)
    metadata = {"source_kind": "offline_fixture", "synthetic": True, "content_status": "complete",
        "dataset": "Thomasgudan/kapibala-sales-dialogues", "license": "CC BY 4.0", "record_id": source_id,
        "attribution_url": "https://huggingface.co/datasets/Thomasgudan/kapibala-sales-dialogues",
        "role_verification": "Publisher explicitly defines a=salesperson and b=customer."}
    with connect_database(path) as db:
        db.execute("""INSERT INTO conversations (id,provider,source_id,title,source_url,created_at,customer_context,context_updated_at)
            VALUES (?,'offline_fixture',?,?,?,?,?,?) ON CONFLICT(provider,source_id) DO NOTHING""",
            (str(uuid4()), source_id, "Offline synthetic sales demo: OmniSupport AI", metadata["attribution_url"], now(), context.model_dump_json(), now()))
        identifier = db.execute("SELECT id FROM conversations WHERE provider='offline_fixture' AND source_id=?", (source_id,)).fetchone()[0]
        reused = db.execute("SELECT 1 FROM transcript_versions WHERE conversation_id=? AND content_hash=?", (identifier, digest)).fetchone() is not None
        if not reused:
            db.execute("""INSERT INTO transcript_versions (id,conversation_id,content_hash,original_text,source_metadata,turns,warnings,imported_at)
                VALUES (?,?,?,?,?,?,?,?)""", (str(uuid4()), identifier, digest, source.transcript, json.dumps(metadata),
                json.dumps([turn.model_dump() for turn in source.verified_turns]),
                json.dumps(["Offline, fully synthetic licensed fixture; not a connected Notion meeting or recorded customer call."]), now()))
    return {"conversation": detail(path, identifier), "reused": reused}
