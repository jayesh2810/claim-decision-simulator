-- Claim Decision Simulator — SQLite schema
-- Open this file in DBeaver and run it against a new SQLite connection
-- pointing to backend/claims.db

PRAGMA foreign_keys = ON;

-- ── Claimants ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS claimants (
    claimant_id   TEXT PRIMARY KEY,
    claimant_name TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now'))
);

-- ── Policies ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS policies (
    policy_id          TEXT PRIMARY KEY,
    claimant_id        TEXT NOT NULL REFERENCES claimants(claimant_id),
    policy_type        TEXT NOT NULL,
    coverage_type      TEXT NOT NULL,
    policy_start_date  TEXT NOT NULL,
    policy_end_date    TEXT NOT NULL,
    deductible         REAL NOT NULL,
    policy_limit       REAL NOT NULL,
    coinsurance        REAL NOT NULL,
    exclusions         TEXT NOT NULL DEFAULT '[]',  -- JSON array
    jurisdiction       TEXT NOT NULL DEFAULT 'US',
    created_at         TEXT DEFAULT (datetime('now'))
);

-- ── Claims ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS claims (
    claim_id                 TEXT PRIMARY KEY,
    claimant_id              TEXT NOT NULL REFERENCES claimants(claimant_id),
    policy_id                TEXT NOT NULL REFERENCES policies(policy_id),
    incident_date            TEXT NOT NULL,
    claim_submission_date    TEXT NOT NULL,
    claim_line               TEXT NOT NULL,
    incident_type            TEXT NOT NULL,
    claimed_loss_amount      REAL NOT NULL,
    claim_narrative          TEXT,
    documents_provided       TEXT NOT NULL DEFAULT '[]',  -- JSON array
    third_party_liable       INTEGER NOT NULL DEFAULT 0,  -- 0/1 boolean
    insured_liability_percent REAL NOT NULL DEFAULT 0.0,
    jurisdiction             TEXT NOT NULL DEFAULT 'US',
    created_at               TEXT DEFAULT (datetime('now'))
);

-- ── Claim Decisions ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS claim_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id        TEXT NOT NULL REFERENCES claims(claim_id),
    final_decision  TEXT NOT NULL CHECK(final_decision IN ('APPROVE','DENY','HOLD_FOR_REVIEW')),
    payout_amount   REAL,
    fraud_risk_score INTEGER NOT NULL,
    audit_trail     TEXT NOT NULL,  -- full JSON
    summary         TEXT,
    decided_at      TEXT DEFAULT (datetime('now'))
);

-- ── Adjuster Reviews (for the review queue) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS adjuster_reviews (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id          TEXT NOT NULL REFERENCES claims(claim_id),
    original_decision TEXT NOT NULL,
    override_decision TEXT NOT NULL CHECK(override_decision IN ('APPROVE','DENY')),
    reason            TEXT,
    reviewed_at       TEXT DEFAULT (datetime('now'))
);

-- ── Useful views ──────────────────────────────────────────────────────────────

-- Latest decision per claim (handles re-simulations)
CREATE VIEW IF NOT EXISTS v_latest_decisions AS
SELECT
    cd.*,
    c.claimant_id,
    c.claim_line,
    c.incident_type,
    c.claimed_loss_amount,
    c.incident_date,
    c.claim_submission_date,
    cl.claimant_name
FROM claim_decisions cd
JOIN claims c ON c.claim_id = cd.claim_id
JOIN claimants cl ON cl.claimant_id = c.claimant_id
WHERE cd.id = (
    SELECT MAX(id) FROM claim_decisions WHERE claim_id = cd.claim_id
);

-- Adjuster queue: HOLD or DENY with no override yet
CREATE VIEW IF NOT EXISTS v_adjuster_queue AS
SELECT *
FROM v_latest_decisions
WHERE final_decision IN ('HOLD_FOR_REVIEW', 'DENY')
  AND claim_id NOT IN (SELECT claim_id FROM adjuster_reviews);
