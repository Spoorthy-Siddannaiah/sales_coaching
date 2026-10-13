"""Read-only developer diagnostic. No providers, network, or production score changes."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "evaluation/kapibala-draft-reference.json"


def compare_scores(report: dict, reference: dict) -> dict:
    rows = {}
    differences = []
    for name, label in reference["dimensions"].items():
        predicted = report["dimensions"][name]["score"]
        draft = label["score"]
        if type(draft) is not int or not 1 <= draft <= 5:
            raise ValueError("Invalid draft score")
        if predicted is not None and (type(predicted) is not int or not 1 <= predicted <= 5):
            raise ValueError("Invalid saved score")
        difference = predicted - draft if predicted is not None else None
        rows[name] = {"ai_score": predicted, "draft_reference": draft, "difference": difference,
                      "large_discrepancy": difference is not None and abs(difference) >= 2}
        if difference is not None:
            differences.append(abs(difference))
    n = len(differences)
    return {"label_status": reference["status"], "confirmed_ground_truth": False,
            "scope": reference["scope"], "conversation_count": 1, "scored_dimensions": n,
            "dimensions": rows, "mean_absolute_error": sum(differences) / n if n else None,
            "exact_agreement": sum(d == 0 for d in differences) / n if n else None,
            "within_one_point_agreement": sum(d <= 1 for d in differences) / n if n else None}


def evaluate_saved(database: Path, reference: dict, analysis_id: str | None = None) -> dict:
    # URI mode=ro prevents even accidental migration or result persistence.
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("""SELECT a.id,a.report,t.original_text,c.source_id FROM analyses a
            JOIN transcript_versions t ON t.id=a.transcript_version_id
            JOIN conversations c ON c.id=t.conversation_id
            WHERE a.status='completed' AND c.source_id=? AND (? IS NULL OR a.id=?)
            ORDER BY a.created_at DESC LIMIT 1""", (reference["record_id"], analysis_id, analysis_id)).fetchone()
    if not row:
        raise ValueError("No matching saved successful analysis")
    if hashlib.sha256(row[2].encode()).hexdigest() != reference["transcript_sha256"]:
        raise ValueError("Reference labels belong to a different transcript snapshot")
    result = compare_scores(json.loads(row[1]), reference)
    result["analysis_id"] = row[0]
    result["factual_review"] = reference.get("factual_reviews", {}).get(row[0], {
        "status": "NOT_REVIEWED", "findings": ["Read the saved report against transcript facts; score metrics do not assess factual accuracy."]})
    result["reference_transcript_facts"] = reference["transcript_facts"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/coaching.sqlite3")
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--analysis-id")
    args = parser.parse_args()
    print(json.dumps(evaluate_saved(args.database, json.loads(args.reference.read_text()), args.analysis_id), indent=2))


if __name__ == "__main__":
    main()
