"""Persist immutable analysis inputs and explicit processing states."""

import json
from pathlib import Path

from app.database import connect_database
from app.repositories.conversations import now


def analysis_record(row) -> dict:
    record = dict(row)
    for field in ("customer_context", "report", "provider_metadata"):
        record[field] = json.loads(record[field]) if record[field] else None
    return record


def get_analysis(path: Path, analysis_id: str) -> dict | None:
    with connect_database(path) as db:
        row = db.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    return analysis_record(row) if row else None


def by_request(path: Path, request_id: str) -> dict | None:
    with connect_database(path) as db:
        row = db.execute("SELECT * FROM analyses WHERE request_id=?", (request_id,)).fetchone()
    return analysis_record(row) if row else None


def create_analysis(path: Path, identifier: str, transcript_id: str, context: dict, provider: str, model: str) -> None:
    with connect_database(path) as db:
        db.execute("""INSERT INTO analyses
            (id,request_id,transcript_version_id,customer_context,objective,salesperson,status,provider,model,created_at)
            VALUES (?,?,?,?,?,NULL,'pending',?,?,?)""",
            (identifier, identifier, transcript_id, json.dumps(context), context["objective"], provider, model, now()))


def start(path: Path, identifier: str) -> None:
    with connect_database(path) as db:
        db.execute("UPDATE analyses SET status='analyzing',started_at=? WHERE id=? AND status='pending'", (now(), identifier))


def finish(path: Path, identifier: str, *, report: dict | None, error: str | None, metadata: dict, latency: float) -> None:
    with connect_database(path) as db:
        db.execute("""UPDATE analyses SET status=?,report=?,error_message=?,finished_at=?,provider_metadata=?,latency_seconds=?
            WHERE id=? AND status IN ('pending','analyzing')""",
            ("completed" if report is not None else "failed", json.dumps(report) if report is not None else None,
             error, now(), json.dumps(metadata), latency, identifier))


def interrupt_stale(path: Path) -> None:
    with connect_database(path) as db:
        db.execute("""UPDATE analyses SET status='failed',error_message=?,finished_at=?
            WHERE status IN ('pending','analyzing')""",
            ("Analysis was interrupted by application shutdown. No automatic retry was made; an uncertain provider charge may remain reserved.", now()))
