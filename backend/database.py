"""SQLite persistence layer for the Claim Decision Simulator."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from schemas import ClaimInput, SimulateResponse

DB_PATH = Path(__file__).resolve().parent / "claims.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with _conn() as con:
        con.executescript(sql)


# ── Writes ────────────────────────────────────────────────────────────────────

def save_claim(claim: ClaimInput) -> None:
    """Persist claimant, policy, and claim records (upsert)."""
    m, pol = claim.metadata, claim.policy_info
    with _conn() as con:
        con.execute(
            """
            INSERT INTO claimants (claimant_id, claimant_name)
            VALUES (?, ?)
            ON CONFLICT(claimant_id) DO UPDATE SET claimant_name = excluded.claimant_name
            """,
            (m.claimant_id, m.claimant_name),
        )
        con.execute(
            """
            INSERT INTO policies (
                policy_id, claimant_id, policy_type, coverage_type,
                policy_start_date, policy_end_date, deductible,
                policy_limit, coinsurance, exclusions, jurisdiction
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(policy_id) DO UPDATE SET
                policy_type       = excluded.policy_type,
                coverage_type     = excluded.coverage_type,
                policy_start_date = excluded.policy_start_date,
                policy_end_date   = excluded.policy_end_date,
                deductible        = excluded.deductible,
                policy_limit      = excluded.policy_limit,
                coinsurance       = excluded.coinsurance,
                exclusions        = excluded.exclusions,
                jurisdiction      = excluded.jurisdiction
            """,
            (
                pol.policy_id, pol.claimant_id, pol.policy_type, pol.coverage_type,
                pol.policy_start_date, pol.policy_end_date, pol.deductible,
                pol.policy_limit, pol.coinsurance,
                json.dumps(pol.exclusions), claim.jurisdiction,
            ),
        )
        con.execute(
            """
            INSERT INTO claims (
                claim_id, claimant_id, policy_id, incident_date,
                claim_submission_date, claim_line, incident_type,
                claimed_loss_amount, claim_narrative, documents_provided,
                third_party_liable, insured_liability_percent, jurisdiction
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(claim_id) DO NOTHING
            """,
            (
                m.claim_id, m.claimant_id, m.policy_id, m.incident_date,
                m.claim_submission_date, m.claim_line, m.incident_type,
                claim.claimed_loss_amount, claim.claim_narrative,
                json.dumps(claim.documents_provided),
                int(claim.third_party_liable), claim.insured_liability_percent,
                claim.jurisdiction,
            ),
        )


def save_decision(result: SimulateResponse) -> None:
    """Append a decision record (allows re-simulation history)."""
    with _conn() as con:
        con.execute(
            """
            INSERT INTO claim_decisions
                (claim_id, final_decision, payout_amount, fraud_risk_score, audit_trail, summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                result.claim_id, result.final_decision, result.payout_amount,
                result.fraud_risk_score,
                json.dumps([e.model_dump() for e in result.audit_trail]),
                result.summary,
            ),
        )


# ── Reads ─────────────────────────────────────────────────────────────────────

def get_prior_claims_count(claimant_id: str, claim_line: str, current_claim_id: str) -> int:
    """Count previous decisions for the same claimant + claim_line, excluding current claim."""
    with _conn() as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM claim_decisions cd
            JOIN claims c ON c.claim_id = cd.claim_id
            WHERE c.claimant_id = ?
              AND c.claim_line   = ?
              AND c.claim_id    != ?
            """,
            (claimant_id, claim_line, current_claim_id),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def get_adjuster_queue() -> list[dict[str, Any]]:
    """Return HOLD/DENY claims that haven't been reviewed yet."""
    with _conn() as con:
        rows = con.execute("SELECT * FROM v_adjuster_queue ORDER BY decided_at DESC").fetchall()
    return [dict(r) for r in rows]


def save_adjuster_review(
    claim_id: str,
    original_decision: str,
    override_decision: str,
    reason: str,
) -> None:
    with _conn() as con:
        con.execute(
            """
            INSERT INTO adjuster_reviews (claim_id, original_decision, override_decision, reason)
            VALUES (?, ?, ?, ?)
            """,
            (claim_id, original_decision, override_decision, reason),
        )


def get_all_decisions() -> list[dict[str, Any]]:
    """Return all latest decisions for the claims history view."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM v_latest_decisions ORDER BY decided_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]
