"""Short SQLite queries; original transcript rows are never edited."""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.database import connect_database
from app.workflow_models import CustomerContext


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def transcript_record(row) -> dict:
    record = dict(row)
    for name in ("source_metadata", "turns", "warnings"):
        record[name] = json.loads(record[name])
    return record


def detail(path: Path, conversation_id: str) -> dict | None:
    with connect_database(path) as db:
        row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["customer_context"] = json.loads(record["customer_context"]) if record["customer_context"] else None
        transcript = db.execute("SELECT * FROM transcript_versions WHERE conversation_id=? ORDER BY imported_at DESC, rowid DESC LIMIT 1", (conversation_id,)).fetchone()
        record["transcript"] = transcript_record(transcript) if transcript else None
        from app.repositories.analyses import analysis_record
        record["analyses"] = [analysis_record(row) for row in db.execute("SELECT a.* FROM analyses a JOIN transcript_versions t ON t.id=a.transcript_version_id WHERE t.conversation_id=? ORDER BY a.created_at DESC, a.rowid DESC", (conversation_id,))]
        return record


def list_conversations(path: Path) -> list[dict]:
    with connect_database(path) as db:
        # Reports and private transcript text are not needed for a list response.
        rows = db.execute("""SELECT c.id,c.provider,c.source_id,c.title,c.created_at,
            (SELECT status FROM analyses a JOIN transcript_versions t ON t.id=a.transcript_version_id
             WHERE t.conversation_id=c.id ORDER BY a.created_at DESC,a.rowid DESC LIMIT 1) AS analysis_status
            FROM conversations c ORDER BY c.created_at DESC,c.rowid DESC""").fetchall()
    return [dict(row, analysis_status=row["analysis_status"] or "ready") for row in rows]


def save_context(path: Path, conversation_id: str, context: CustomerContext) -> bool:
    with connect_database(path) as db:
        return db.execute("UPDATE conversations SET customer_context=?,context_updated_at=? WHERE id=?", (context.model_dump_json(), now(), conversation_id)).rowcount == 1
