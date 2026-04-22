#!/usr/bin/env python3
"""
Load deterministic fake data into claims.db and write JSON FNOL files that match
the DB (ground truth for document upload + /simulate prior-count tests).

Run from repo root or backend/:
  python3 seed_ground_truth.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from database import DB_PATH, init_db
from schemas import AuditEntry, ClaimInput, ClaimMetadata, PolicyInfo, SimulateResponse

# ── Single source of truth: these ClaimInput + decisions match what we store ─────────

CLAIM_GT_001 = ClaimInput(
    metadata=ClaimMetadata(
        claim_id="CLM-2026-GT-001",
        claimant_name="Alice GroundTruth",
        claimant_id="CLMT-GT-90001",
        policy_id="POL-GT-90001",
        incident_date="2026-03-10",
        claim_submission_date="2026-03-12",
        claim_line="auto_collision",
        incident_type="vehicle_collision",
    ),
    claimed_loss_amount=12450.0,
    claim_narrative=(
        "Rear-end collision on Harbor Blvd while stopped at a traffic light. The other driver "
        "admitted fault; photos show bumper and tail lamp damage. Police report and written "
        "estimate from AllStar Collision attached."
    ),
    documents_provided=["police_report", "repair_estimate", "photos", "insurance_card_copy"],
    prior_claims_same_type=0,
    jurisdiction="US-CA",
    third_party_liable=True,
    insured_liability_percent=0.0,
    policy_info=PolicyInfo(
        policy_id="POL-GT-90001",
        claimant_id="CLMT-GT-90001",
        policy_type="auto",
        coverage_type="collision",
        policy_start_date="2025-01-10",
        policy_end_date="2028-01-10",
        deductible=500.0,
        policy_limit=50000.0,
        coinsurance=1.0,
        exclusions=[],
    ),
)

# Bob: historical claim already decided (drives prior count for his next FNOL)
CLAIM_GT_P99 = ClaimInput(
    metadata=ClaimMetadata(
        claim_id="CLM-2025-GT-P99",
        claimant_name="Bob WithHistory",
        claimant_id="CLMT-GT-90002",
        policy_id="POL-GT-90002",
        incident_date="2025-08-20",
        claim_submission_date="2025-08-25",
        claim_line="auto_collision",
        incident_type="vehicle_collision",
    ),
    claimed_loss_amount=3200.0,
    claim_narrative="Parking lot sideswipe; single estimate attached; no injuries.",
    documents_provided=["photos", "repair_estimate"],
    prior_claims_same_type=0,
    jurisdiction="US-TX",
    third_party_liable=False,
    insured_liability_percent=0.0,
    policy_info=PolicyInfo(
        policy_id="POL-GT-90002",
        claimant_id="CLMT-GT-90002",
        policy_type="auto",
        coverage_type="collision",
        policy_start_date="2024-01-01",
        policy_end_date="2027-12-31",
        deductible=1000.0,
        policy_limit=25000.0,
        coinsurance=1.0,
        exclusions=[],
    ),
)

# New FNOL for Bob (not stored as a claim until first simulate) — DB has P99 with a decision, so prior=1
CLAIM_GT_002 = ClaimInput(
    metadata=ClaimMetadata(
        claim_id="CLM-2026-GT-002",
        claimant_name="Bob WithHistory",
        claimant_id="CLMT-GT-90002",
        policy_id="POL-GT-90002",
        incident_date="2026-04-01",
        claim_submission_date="2026-04-05",
        claim_line="auto_collision",
        incident_type="vehicle_collision",
    ),
    claimed_loss_amount=5100.0,
    claim_narrative=(
        "Another collision claim on this policy. Damage to left mirror and fender. Police report and "
        "shop estimate included."
    ),
    documents_provided=["police_report", "repair_estimate", "photos"],
    prior_claims_same_type=0,  # server overrides with DB
    jurisdiction="US-TX",
    third_party_liable=True,
    insured_liability_percent=0.0,
    policy_info=CLAIM_GT_P99.policy_info.model_copy(),
)

# Carol: HOLD in queue
CLAIM_GT_003 = ClaimInput(
    metadata=ClaimMetadata(
        claim_id="CLM-2026-GT-003",
        claimant_name="Carol Queued",
        claimant_id="CLMT-GT-90003",
        policy_id="POL-GT-90003",
        incident_date="2026-02-14",
        claim_submission_date="2026-02-20",
        claim_line="homeowners_dwelling",
        incident_type="kitchen_fire",
    ),
    claimed_loss_amount=18900.0,
    claim_narrative="Grease fire in kitchen. Smoke and cabinet damage. Fire dept report and photos attached.",
    documents_provided=["photos", "fire_department_report", "contractor_estimate"],
    prior_claims_same_type=0,
    jurisdiction="US-FL",
    third_party_liable=False,
    insured_liability_percent=0.0,
    policy_info=PolicyInfo(
        policy_id="POL-GT-90003",
        claimant_id="CLMT-GT-90003",
        policy_type="homeowners",
        coverage_type="dwelling",
        policy_start_date="2020-05-01",
        policy_end_date="2030-05-01",
        deductible=2000.0,
        policy_limit=350000.0,
        coinsurance=1.0,
        exclusions=[],
    ),
)


def _seed_responses() -> list[tuple[str, SimulateResponse]]:
    """(claim_id, response) to insert into claim_decisions."""
    return [
        (
            "CLM-2026-GT-001",
            SimulateResponse(
                claim_id="CLM-2026-GT-001",
                final_decision="APPROVE",
                payout_amount=11950.0,
                fraud_risk_score=5,
                audit_trail=[
                    AuditEntry(
                        step="eligibility",
                        title="Seeded",
                        status="pass",
                        findings=[],
                        reasoning="Seed data.",
                    )
                ],
                summary="Seeded approval for ground-truth claim GT-001.",
            ),
        ),
        (
            "CLM-2025-GT-P99",
            SimulateResponse(
                claim_id="CLM-2025-GT-P99",
                final_decision="APPROVE",
                payout_amount=2200.0,
                fraud_risk_score=10,
                audit_trail=[
                    AuditEntry(
                        step="eligibility",
                        title="Seeded",
                        status="pass",
                        findings=[],
                        reasoning="Seed data.",
                    )
                ],
                summary="Seeded past decision for prior-count tests.",
            ),
        ),
        (
            "CLM-2026-GT-003",
            SimulateResponse(
                claim_id="CLM-2026-GT-003",
                final_decision="HOLD_FOR_REVIEW",
                payout_amount=None,
                fraud_risk_score=55,
                audit_trail=[
                    AuditEntry(
                        step="fraud",
                        title="Seeded",
                        status="warning",
                        findings=[],
                        reasoning="Seed HOLD for queue UI.",
                    )
                ],
                summary="Seeded hold for adjuster queue testing.",
            ),
        ),
    ]


def _insert_claim(c: ClaimInput, con: sqlite3.Connection) -> None:
    m, pol = c.metadata, c.policy_info
    con.execute(
        """
        INSERT OR REPLACE INTO claimants (claimant_id, claimant_name) VALUES (?, ?)
        """,
        (m.claimant_id, m.claimant_name),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO policies (
            policy_id, claimant_id, policy_type, coverage_type,
            policy_start_date, policy_end_date, deductible,
            policy_limit, coinsurance, exclusions, jurisdiction
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pol.policy_id, pol.claimant_id, pol.policy_type, pol.coverage_type,
            pol.policy_start_date, pol.policy_end_date, pol.deductible,
            pol.policy_limit, pol.coinsurance,
            json.dumps(pol.exclusions), c.jurisdiction,
        ),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO claims (
            claim_id, claimant_id, policy_id, incident_date,
            claim_submission_date, claim_line, incident_type,
            claimed_loss_amount, claim_narrative, documents_provided,
            third_party_liable, insured_liability_percent, jurisdiction
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            m.claim_id, m.claimant_id, m.policy_id, m.incident_date,
            m.claim_submission_date, m.claim_line, m.incident_type,
            c.claimed_loss_amount, c.claim_narrative,
            json.dumps(c.documents_provided),
            int(c.third_party_liable), c.insured_liability_percent,
            c.jurisdiction,
        ),
    )


def _insert_decision(con: sqlite3.Connection, res: SimulateResponse) -> None:
    con.execute(
        """
        INSERT INTO claim_decisions
            (claim_id, final_decision, payout_amount, fraud_risk_score, audit_trail, summary)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            res.claim_id,
            res.final_decision,
            res.payout_amount,
            res.fraud_risk_score,
            json.dumps([e.model_dump() for e in res.audit_trail]),
            res.summary,
        ),
    )


def _wipe_user_data(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        DELETE FROM adjuster_reviews;
        DELETE FROM claim_decisions;
        DELETE FROM claims;
        DELETE FROM policies;
        DELETE FROM claimants;
        """
    )


def main() -> None:
    init_db()
    claims_to_store = [CLAIM_GT_001, CLAIM_GT_P99, CLAIM_GT_003]
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        _wipe_user_data(con)
        for c in claims_to_store:
            _insert_claim(c, con)
        for _cid, res in _seed_responses():
            _insert_decision(con, res)
        con.commit()
    finally:
        con.close()

    out_dir = Path(__file__).resolve().parent / "seeds" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Uploadable / simulate payloads: must match DB rows for same claim_ids
    (out_dir / "CLM-2026-GT-001_fnol.json").write_text(
        json.dumps(CLAIM_GT_001.model_dump(), indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "CLM-2025-GT-P99_fnol.json").write_text(
        json.dumps(CLAIM_GT_P99.model_dump(), indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "CLM-2026-GT-002_fnol_bob_with_prior_in_db.json").write_text(
        json.dumps(CLAIM_GT_002.model_dump(), indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "CLM-2026-GT-003_fnol.json").write_text(
        json.dumps(CLAIM_GT_003.model_dump(), indent=2) + "\n", encoding="utf-8"
    )

    print(f"Seeded {DB_PATH} with {len(claims_to_store)} claims and decisions.")
    print(f"Wrote JSON fixtures to {out_dir}:")
    for p in sorted(out_dir.glob("*.json")):
        print(f"  - {p.name}")


if __name__ == "__main__":
    main()
