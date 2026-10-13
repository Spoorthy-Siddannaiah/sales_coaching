import copy
import json
import sqlite3

import pytest

from app.offline_score_review import REFERENCE, compare_scores, evaluate_saved


def reference(): return json.loads(REFERENCE.read_text())
def report(scores): return {"dimensions": {name: {"score": score} for name, score in zip(reference()["dimensions"], scores)}}


def test_five_maximum_scores_against_draft_are_diagnostic_not_ground_truth():
    result = compare_scores(report([5] * 5), reference())
    assert [r["difference"] for r in result["dimensions"].values()] == [2, 3, 2, 0, 1]
    assert result["mean_absolute_error"] == 1.6
    assert result["exact_agreement"] == .2
    assert result["within_one_point_agreement"] == .4
    assert result["dimensions"]["discovery_questions"]["large_discrepancy"] is True
    assert result["confirmed_ground_truth"] is False and result["conversation_count"] == 1
    assert "pearson" not in str(result).lower() and "kappa" not in str(result).lower()


def test_null_scores_are_not_converted_to_zero_and_input_is_unchanged():
    data = report([None, 2, 3, 5, 4]); before = copy.deepcopy(data)
    result = compare_scores(data, reference())
    assert result["scored_dimensions"] == 4 and result["mean_absolute_error"] == 0
    assert data == before


def test_read_only_review_rejects_wrong_snapshot(tmp_path):
    path = tmp_path / "review.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE analyses(id,report,transcript_version_id,status,created_at); CREATE TABLE transcript_versions(id,original_text,conversation_id); CREATE TABLE conversations(id,source_id);")
        db.execute("INSERT INTO conversations VALUES ('c',?)", (reference()["record_id"],))
        db.execute("INSERT INTO transcript_versions VALUES ('t','wrong text','c')")
        db.execute("INSERT INTO analyses VALUES ('a',?,'t','completed','2026')", (json.dumps(report([5]*5)),))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="different transcript"):
        evaluate_saved(path, reference())
    assert path.read_bytes() == before
