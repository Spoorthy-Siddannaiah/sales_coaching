import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import PROJECT_ROOT, Settings
from app.database import connect_database, initialize_database
from app.main import create_app


def test_startup_initializes_database_and_health(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "test.sqlite3"
    settings = Settings(_env_file=None, database_path=path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}
    with connect_database(path) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert tables == {"conversations", "transcript_versions", "analyses"}


def test_health_returns_useful_database_failure(tmp_path: Path) -> None:
    path = tmp_path / "test.sqlite3"
    with TestClient(create_app(Settings(_env_file=None, database_path=path))) as client:
        with connect_database(path) as connection:
            connection.execute("DROP TABLE conversations")
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable. Check local storage."}


def test_schema_preserves_data_on_restart_and_prevents_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    values = ("c1", "notion", "page1", "Demo", "2026-10-09T10:00:00Z")
    query = "INSERT INTO conversations (id, provider, source_id, title, created_at) VALUES (?, ?, ?, ?, ?)"
    with connect_database(path) as connection:
        connection.execute(query, values)
    initialize_database(path)
    with connect_database(path) as connection:
        assert connection.execute("SELECT title FROM conversations").fetchone()[0] == "Demo"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(query, ("c2", *values[1:]))


def test_foreign_keys_and_transcript_version_uniqueness(tmp_path: Path) -> None:
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    query = "INSERT INTO transcript_versions (id, conversation_id, content_hash, original_text, imported_at) VALUES (?, ?, ?, ?, ?)"
    with connect_database(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(query, ("t1", "missing", "hash1", "Hello", "now"))
        connection.execute("INSERT INTO conversations (id, provider, source_id, title, source_url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                           ("c1", "notion", "page1", "Demo", None, "now"))
        connection.execute(query, ("t1", "c1", "hash1", "Hello", "now"))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(query, ("t2", "c1", "hash1", "Hello", "now"))
        connection.execute(query, ("t3", "c1", "hash2", "Changed", "now"))


def test_settings_environment_and_secret_masking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", "data/custom.sqlite3")
    monkeypatch.setenv("NOTION_API_TOKEN", "test-secret-not-real")
    settings = Settings(_env_file=None)
    assert settings.database_path == PROJECT_ROOT / "data/custom.sqlite3"
    assert settings.notion_api_token is not None
    assert settings.notion_api_token.get_secret_value() == "test-secret-not-real"
    assert "test-secret-not-real" not in repr(settings)


def test_invalid_database_path_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_path=None)


def test_analysis_is_separate_and_rejects_false_success(tmp_path: Path) -> None:
    path = tmp_path / "test.sqlite3"
    initialize_database(path)
    with connect_database(path) as connection:
        connection.execute("INSERT INTO conversations (id, provider, source_id, title, source_url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                           ("c1", "notion", "page1", "Demo", None, "now"))
        connection.execute(
            "INSERT INTO transcript_versions (id, conversation_id, content_hash, original_text, imported_at) VALUES (?, ?, ?, ?, ?)",
            ("t1", "c1", "hash1", "Sales: Hello", "now"),
        )
        query = """INSERT INTO analyses
            (id, transcript_version_id, customer_context, objective, salesperson,
             status, model, report, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(query, ("a1", "t1", "{}", "Learn needs", "Sales",
                                       "completed", "test-model", None, "now"))
        connection.execute(query, ("a1", "t1", "{}", "Learn needs", "Sales",
                                   "completed", "test-model", '{"test": true}', "now"))
    initialize_database(path)
    with connect_database(path) as connection:
        assert connection.execute("SELECT original_text FROM transcript_versions").fetchone()[0] == "Sales: Hello"
        assert connection.execute("SELECT report FROM analyses").fetchone()[0] == '{"test": true}'
