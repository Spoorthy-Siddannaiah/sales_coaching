"""Persistent pre-request reservations; money stored in millionths of a dollar.

Uncertain calls retain their entire reservation. No automatic refunds or resets.
This ledger cannot observe charges made outside this application.
"""

import math
import sqlite3
from decimal import Decimal

from app.config import Settings
from app.services.llm_provider import ProviderError


def cost_micro_usd(input_tokens: int, output_tokens: int) -> int:
    # Standard GPT-4.1 mini pricing: $0.40/M input, $1.60/M output.
    # Ignore cache discounts conservatively; round upward once per request.
    return math.ceil(Decimal(input_tokens) * Decimal("0.4") + Decimal(output_tokens) * Decimal("1.6"))


class SpendingLedger:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.spending_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS spending (
                call_id TEXT PRIMARY KEY, model TEXT NOT NULL,
                estimated_input_tokens INTEGER NOT NULL, max_output_tokens INTEGER NOT NULL,
                reserved_micro_usd INTEGER NOT NULL, charged_micro_usd INTEGER NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    def connect(self):
        return sqlite3.connect(self.settings.spending_ledger_path)

    def reserve(self, call_id: str, input_tokens: int, output_tokens: int) -> int:
        amount = cost_micro_usd(input_tokens, output_tokens)
        ceiling = int((Decimal(str(self.settings.budget_usd)) - Decimal(str(self.settings.budget_reserve_usd))) * 1000000)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM spending WHERE call_id=?", (call_id,)).fetchone():
                raise ProviderError("This paid call ID was already attempted; no additional request was sent.")
            spent = db.execute("SELECT COALESCE(SUM(charged_micro_usd),0) FROM spending").fetchone()[0]
            if spent + amount > ceiling:
                raise ProviderError("Local budget exhausted: the Stage 5 reserve must remain untouched.")
            db.execute("INSERT INTO spending (call_id,model,estimated_input_tokens,max_output_tokens,reserved_micro_usd,charged_micro_usd,status) VALUES (?,?,?,?,?,?,?)",
                       (call_id, self.settings.openai_model, input_tokens, output_tokens, amount, amount, "reserved_or_uncertain"))
        return amount

    def settle(self, call_id: str, input_tokens: int, output_tokens: int) -> int:
        amount = cost_micro_usd(input_tokens, output_tokens)
        with self.connect() as db:
            row = db.execute("SELECT status FROM spending WHERE call_id=?", (call_id,)).fetchone()
            if not row or row[0] != "reserved_or_uncertain":
                raise ProviderError("Budget reservation is missing or already settled.")
            db.execute("UPDATE spending SET input_tokens=?,output_tokens=?,charged_micro_usd=?,status='settled' WHERE call_id=?", (input_tokens, output_tokens, amount, call_id))
        return amount

    def summary(self) -> dict:
        with self.connect() as db:
            spent, calls = db.execute("SELECT COALESCE(SUM(charged_micro_usd),0),COUNT(*) FROM spending").fetchone()
        return {"tracked_cost_usd": spent / 1000000, "remaining_budget_usd": round(self.settings.budget_usd - spent / 1000000, 6),
                "available_before_reserve_usd": round(self.settings.budget_usd - self.settings.budget_reserve_usd - spent / 1000000, 6), "calls": calls}
