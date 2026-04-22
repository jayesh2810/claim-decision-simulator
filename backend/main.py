"""
Claim Decision Simulator — FastAPI backend.
13-step deterministic pipeline for structured JSON claims; OCR + LLM for document uploads.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from database import get_prior_claims_count, init_db, save_claim, save_decision
from ingestion import extract_document_text, save_upload_bytes, tesseract_available
from llm_decision import decide_from_document_text, llm_backend_ready
from schemas import AuditEntry, ClaimInput, SimulateResponse
from settings import Settings, get_settings

STATUTE_OF_LIMITATIONS_YEARS = 3
FRAUD_HOLD_THRESHOLD = 70
SUBROGATION_RECOVERY_RATE = 0.65
SUBROGATION_MIN_THRESHOLD = 2000.0
RESERVE_BUFFER_PCT = 0.15

KNOWN_POLICY_TYPES = {"auto", "homeowners", "health", "life", "commercial", "renters", "umbrella"}

COVERAGE_INCIDENT_MAP: dict[str, set[str]] = {
    "collision": {"vehicle_collision", "multi_vehicle_pileup", "single_vehicle_accident", "hit_and_run"},
    "comprehensive": {"theft", "vandalism", "weather_damage", "deer_strike", "hail_damage", "flood", "glass_damage", "fire"},
    "dwelling": {"fire", "hail_damage", "wind_damage", "water_pipe_burst", "kitchen_fire", "lightning", "vandalism"},
    "emergency": {"emergency_room_visit", "urgent_care", "ambulance"},
    "health": {"emergency_room_visit", "inpatient", "outpatient", "surgery", "urgent_care"},
    "uninsured_motorist": {"vehicle_collision", "hit_and_run", "pedestrian_strike"},
}

HARD_COVERAGE_EXCLUSIONS: dict[str, set[str]] = {
    "collision": {"flood", "earthquake", "mechanical_breakdown"},
    "dwelling": {"flood", "earthquake"},
}

UNIVERSAL_EXCLUSIONS = {"intentional_act", "nuclear", "war", "terrorism", "wear_and_tear"}

VAGUE_PHRASES = (
    "something happened", "not sure", "i think", "maybe",
    "dont know", "don't know", "unsure", "vague", "stuff", "thing",
)

CLAIM_ID_PATTERN = re.compile(r"^[A-Z]{2,8}-\d{4}-\d+$")


def _parse_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def _days_between(a: str, b: str) -> int:
    da, db = _parse_date(a), _parse_date(b)
    return (db - da).days


def _norm_docs(docs: list[str]) -> set[str]:
    return {d.strip().lower().replace(" ", "_") for d in docs if d}


def narrative_hint(c: ClaimInput) -> str:
    return (c.claim_narrative or "").lower()


def _load_sample_claims() -> list[dict[str, Any]]:
    p = Path(__file__).resolve().parent / "sample_claims.json"
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("sample_claims.json must be a JSON array")
    return data


# ── Step 1: Document Intake & Validation ──────────────────────────────────────

def _run_document_intake(c: ClaimInput) -> tuple[bool, AuditEntry]:
    findings: list[dict[str, Any]] = []
    ok = True

    claim_id_ok = bool(CLAIM_ID_PATTERN.match(c.metadata.claim_id))
    findings.append({
        "check": "Claim ID format valid (e.g. CLM-2026-001)",
        "result": claim_id_ok,
        "detail": c.metadata.claim_id,
    })

    narrative = (c.claim_narrative or "").strip()
    narrative_ok = len(narrative) >= 20
    findings.append({
        "check": "Narrative present and substantive (≥ 20 chars)",
        "result": narrative_ok,
        "detail": f"{len(narrative)} characters provided",
    })
    if not narrative_ok:
        ok = False

    doc_count = len([d for d in c.documents_provided if d.strip()])
    docs_ok = doc_count > 0
    findings.append({
        "check": "At least one supporting document referenced",
        "result": docs_ok,
        "detail": f"{doc_count} document(s) listed",
    })
    if not docs_ok:
        ok = False

    amount_ok = c.claimed_loss_amount > 0
    findings.append({
        "check": "Claimed loss amount is non-zero",
        "result": amount_ok,
        "detail": f"${c.claimed_loss_amount:,.2f}",
    })
    if not amount_ok:
        ok = False

    reasoning = (
        "Claim packet is complete; all intake checks passed."
        if ok
        else "Intake failed: claim packet is incomplete (missing narrative, documents, or valid amount)."
    )
    return ok, AuditEntry(
        step="document_intake",
        title="Document intake & validation",
        status="pass" if ok else "fail",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 2: Claimant Identity Verification ────────────────────────────────────

def _run_identity_check(c: ClaimInput) -> tuple[bool, AuditEntry]:
    m, pol = c.metadata, c.policy_info
    findings: list[dict[str, Any]] = []
    ok = True

    policy_match = m.policy_id == pol.policy_id
    findings.append({
        "check": "Policy ID consistent across metadata and policy record",
        "result": policy_match,
        "detail": f"Metadata: {m.policy_id} | Record: {pol.policy_id}",
    })
    if not policy_match:
        ok = False

    claimant_match = m.claimant_id == pol.claimant_id
    findings.append({
        "check": "Claimant ID consistent across metadata and policy record",
        "result": claimant_match,
        "detail": f"Metadata: {m.claimant_id} | Record: {pol.claimant_id}",
    })
    if not claimant_match:
        ok = False

    name_ok = bool((m.claimant_name or "").strip())
    findings.append({
        "check": "Claimant name provided",
        "result": name_ok,
        "detail": m.claimant_name or "(empty)",
    })
    if not name_ok:
        ok = False

    reasoning = (
        "Identity verified; claimant and policy IDs are consistent."
        if ok
        else "Identity mismatch: policy or claimant IDs do not align across metadata and policy record."
    )
    return ok, AuditEntry(
        step="identity_verification",
        title="Claimant identity verification",
        status="pass" if ok else "fail",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 3: Policy Lookup & Verification ─────────────────────────────────────

def _run_policy_verification(c: ClaimInput) -> tuple[bool, AuditEntry]:
    pol = c.policy_info
    findings: list[dict[str, Any]] = []
    ok = True

    type_ok = pol.policy_type.lower() in KNOWN_POLICY_TYPES
    findings.append({
        "check": "Policy type is recognized",
        "result": type_ok,
        "detail": f"Type: {pol.policy_type}",
    })
    if not type_ok:
        ok = False

    ded_ok = pol.deductible < pol.policy_limit
    findings.append({
        "check": "Deductible is less than policy limit",
        "result": ded_ok,
        "detail": f"Deductible ${pol.deductible:,.2f} | Limit ${pol.policy_limit:,.2f}",
    })
    if not ded_ok:
        ok = False

    coi_ok = 0 < pol.coinsurance <= 1.0
    findings.append({
        "check": "Coinsurance in valid range (0–100%)",
        "result": coi_ok,
        "detail": f"{pol.coinsurance * 100:.0f}%",
    })
    if not coi_ok:
        ok = False

    start = _parse_date(pol.policy_start_date)
    end = _parse_date(pol.policy_end_date)
    dates_ok = start < end
    findings.append({
        "check": "Policy start date precedes end date",
        "result": dates_ok,
        "detail": f"{pol.policy_start_date} → {pol.policy_end_date}",
    })
    if not dates_ok:
        ok = False

    reasoning = (
        "Policy record verified; type, financial parameters, and dates are consistent."
        if ok
        else "Policy record has inconsistencies that prevent claim processing."
    )
    return ok, AuditEntry(
        step="policy_verification",
        title="Policy lookup & verification",
        status="pass" if ok else "fail",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 4: Eligibility Check ────────────────────────────────────────────────

def _run_eligibility(c: ClaimInput) -> tuple[bool, AuditEntry]:
    m, pol = c.metadata, c.policy_info
    findings: list[dict[str, Any]] = []
    ok = True
    sub = _parse_date(m.claim_submission_date)
    inc = _parse_date(m.incident_date)
    start = _parse_date(pol.policy_start_date)
    end = _parse_date(pol.policy_end_date)

    policy_active = start <= sub <= end
    findings.append({
        "check": "Policy active on submission date",
        "result": policy_active,
        "detail": f"Submission {m.claim_submission_date} within [{pol.policy_start_date}, {pol.policy_end_date}]",
    })
    if not policy_active:
        ok = False

    incident_before_sub = inc <= sub
    findings.append({
        "check": "Incident date before or on submission",
        "result": incident_before_sub,
        "detail": f"Incident {m.incident_date}, submitted {m.claim_submission_date}",
    })
    if not incident_before_sub:
        ok = False

    sol_days = STATUTE_OF_LIMITATIONS_YEARS * 365
    days_filed = _days_between(m.incident_date, m.claim_submission_date)
    within_sol = 0 <= days_filed <= sol_days
    findings.append({
        "check": "Within statute of limitations ({0} years / {1} days)".format(
            STATUTE_OF_LIMITATIONS_YEARS, sol_days
        ),
        "result": within_sol,
        "detail": f"Days from incident to filing: {days_filed}",
    })
    if not within_sol:
        ok = False

    amount_ok = c.claimed_loss_amount > 0
    findings.append({
        "check": "Claimed loss amount is positive",
        "result": amount_ok,
        "detail": f"Claimed loss ${c.claimed_loss_amount:,.2f}",
    })
    if not amount_ok:
        ok = False

    reasoning = (
        "All eligibility checks passed."
        if ok
        else "One or more eligibility checks failed; claim cannot proceed to payment."
    )
    return ok, AuditEntry(
        step="eligibility",
        title="Eligibility check",
        status="pass" if ok else "fail",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 5: Coverage Scope Verification ──────────────────────────────────────

def _run_coverage_scope(c: ClaimInput) -> tuple[bool, AuditEntry]:
    pol = c.policy_info
    m = c.metadata
    findings: list[dict[str, Any]] = []
    ok = True

    cov = pol.coverage_type.lower()
    inc = m.incident_type.lower()

    compatible = COVERAGE_INCIDENT_MAP.get(cov)
    if compatible:
        scope_ok = inc in compatible
        findings.append({
            "check": f"Incident type '{inc}' recognized under '{cov}' coverage",
            "result": scope_ok,
            "detail": f"Covered incidents for {cov}: {', '.join(sorted(compatible))}",
        })
        if not scope_ok:
            ok = False
    else:
        findings.append({
            "check": "Coverage type scope check",
            "result": True,
            "detail": f"Coverage type '{cov}' not in predefined map; proceeds to manual review",
        })

    hard_excl = HARD_COVERAGE_EXCLUSIONS.get(cov, set())
    hard_triggered = [ex for ex in hard_excl if ex in inc]
    hard_ok = len(hard_triggered) == 0
    findings.append({
        "check": f"Hard exclusions for '{cov}' coverage not triggered",
        "result": hard_ok,
        "detail": f"Triggered: {hard_triggered}" if hard_triggered else "None triggered",
    })
    if not hard_ok:
        ok = False

    reasoning = (
        f"Coverage scope confirmed: '{inc}' is a covered peril under '{cov}' policy."
        if ok
        else f"Coverage scope mismatch: '{inc}' is not a covered peril under '{cov}' coverage."
    )
    return ok, AuditEntry(
        step="coverage_scope",
        title="Coverage scope verification",
        status="pass" if ok else "fail",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 6: Exclusion Screening ───────────────────────────────────────────────

def _run_exclusion_screening(c: ClaimInput) -> tuple[bool, AuditEntry]:
    pol = c.policy_info
    m = c.metadata
    narrative = narrative_hint(c)
    findings: list[dict[str, Any]] = []
    ok = True

    policy_violations = [
        ex for ex in pol.exclusions
        if ex.lower() in m.incident_type.lower() or ex.lower() in narrative
    ]
    policy_ok = len(policy_violations) == 0
    findings.append({
        "check": "Policy-specific exclusions not triggered",
        "result": policy_ok,
        "detail": f"Violations: {policy_violations}" if policy_violations else "None triggered",
    })
    if not policy_ok:
        ok = False

    universal_violations = [
        ux for ux in UNIVERSAL_EXCLUSIONS
        if ux in m.incident_type.lower() or ux in narrative
    ]
    universal_ok = len(universal_violations) == 0
    findings.append({
        "check": "Universal exclusions (intentional acts, war, nuclear, terrorism) not triggered",
        "result": universal_ok,
        "detail": f"Violations: {universal_violations}" if universal_violations else "None triggered",
    })
    if not universal_ok:
        ok = False

    findings.append({
        "check": "Registered policy exclusions on file",
        "result": True,
        "detail": pol.exclusions if pol.exclusions else ["None"],
    })

    reasoning = (
        "No exclusions apply to this claim."
        if ok
        else f"Exclusion(s) apply — policy: {policy_violations}, universal: {universal_violations}."
    )
    return ok, AuditEntry(
        step="exclusion_screening",
        title="Exclusion screening",
        status="pass" if ok else "fail",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 7: Duplicate & Prior Claims Detection ────────────────────────────────

def _run_duplicate_check(c: ClaimInput) -> tuple[bool, AuditEntry]:
    m = c.metadata
    findings: list[dict[str, Any]] = []
    ok = True
    warn = False

    days_to_file = _days_between(m.incident_date, m.claim_submission_date)
    rapid_filing = days_to_file == 0
    findings.append({
        "check": "Same-day filing flag",
        "result": not rapid_filing,
        "detail": f"Filed {days_to_file} day(s) after incident"
        + (" — same-day flag set" if rapid_filing else ""),
    })
    if rapid_filing:
        warn = True

    prior = c.prior_claims_same_type
    prior_ok = prior < 3
    findings.append({
        "check": "Prior claims count (same type) below escalation threshold (< 3)",
        "result": prior_ok,
        "detail": f"{prior} prior claim(s) of same type on record",
    })
    if not prior_ok:
        ok = False
    elif prior >= 1:
        warn = True

    if prior >= 3:
        findings.append({
            "check": "High-frequency claimant flag",
            "result": False,
            "detail": "4+ same-type claims detected; mandatory escalation triggered",
        })

    inc = _parse_date(m.incident_date)
    sub = _parse_date(m.claim_submission_date)
    future_ok = inc <= sub
    findings.append({
        "check": "Incident date not future-dated relative to submission",
        "result": future_ok,
        "detail": f"Incident {m.incident_date} | Submitted {m.claim_submission_date}",
    })
    if not future_ok:
        ok = False

    if not ok:
        status = "fail"
        reasoning = "High-frequency claim pattern or future-dated incident; escalation required."
    elif warn:
        status = "warning"
        reasoning = "Minor flags noted (rapid filing or repeat claims); documented for examiner."
    else:
        status = "pass"
        reasoning = "No duplicate or high-frequency concerns detected."

    return ok, AuditEntry(
        step="duplicate_check",
        title="Duplicate & prior claims detection",
        status=status,
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 8: Fraud Risk Scoring ────────────────────────────────────────────────

def _run_fraud(c: ClaimInput) -> tuple[int, list[str], AuditEntry]:
    narrative = (c.claim_narrative or "").lower()
    score = 0
    signals: list[str] = []

    vague_hits = [p for p in VAGUE_PHRASES if p in narrative]
    vpoints = min(20, len(vague_hits) * 5)
    if vpoints:
        score += vpoints
        signals.append(f"Vague or non-specific language ({len(vague_hits)} phrase(s)): +{vpoints}")

    if len(narrative.strip()) < 80:
        score += 15
        signals.append("Narrative under 80 characters: +15")

    amt = c.claimed_loss_amount
    line = c.metadata.claim_line.lower()
    if "auto" in line or "collision" in line or "comprehensive" in line:
        if amt > 95000:
            score += 28
            signals.append(f"Claimed loss ${amt:,.0f} very high vs typical auto repair range: +28")
        elif amt > 60000:
            score += 15
            signals.append(f"Claimed loss ${amt:,.0f} unusually high for auto: +15")
    elif "homeowners" in line or "dwelling" in line or "property" in line:
        if amt > 500000:
            score += 25
            signals.append(f"Dwelling/property claim ${amt:,.0f} exceeds typical band: +25")
    elif "health" in line or "inpatient" in line or "emergency" in line:
        if amt > 500000:
            score += 20
            signals.append(f"Health claim amount ${amt:,.0f} triggers high-amount review heuristic: +20")

    prior = c.prior_claims_same_type
    if prior == 1:
        score += 12
        signals.append("Second claim of same type in recent history: +12")
    elif prior == 2:
        score += 22
        signals.append("Third claim of same type in recent history: +22")
    elif prior >= 3:
        score += 35
        signals.append(f"Fourth+ claim of same type ({prior} prior): +35")

    score = min(100, score)

    findings: list[dict[str, Any]] = [
        {"label": "Risk score (0–100)", "value": score},
        {"label": "Scoring signals", "value": signals if signals else ["No fraud heuristics triggered"]},
        {"label": "Prior claims (same type)", "value": prior},
    ]

    if score >= FRAUD_HOLD_THRESHOLD:
        status = "warning"
        reasoning = (
            f"Score {score} meets escalation threshold ({FRAUD_HOLD_THRESHOLD}). "
            "Recommend specialist review before payment."
        )
    elif score >= 50:
        status = "warning"
        reasoning = f"Elevated score ({score}); within auto-adjudication band but documented for audit."
    else:
        status = "pass"
        reasoning = f"Fraud heuristics score {score}; no automatic escalation triggered."

    return score, signals, AuditEntry(
        step="fraud",
        title="Fraud detection (heuristic scoring)",
        status=status,
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 9: Third-Party Liability Assessment ──────────────────────────────────

def _run_third_party_liability(c: ClaimInput) -> AuditEntry:
    findings: list[dict[str, Any]] = []
    third_party = c.third_party_liable
    liability_pct = c.insured_liability_percent

    findings.append({
        "check": "Third party identified as liable",
        "result": third_party,
        "detail": "Yes — subrogation opportunity may exist" if third_party else "No — pure first-party claim",
    })

    if third_party:
        other_pct = 100.0 - liability_pct
        findings.append({"label": "Insured's liability share", "value": f"{liability_pct:.0f}%"})
        findings.append({"label": "Third party's liability share", "value": f"{other_pct:.0f}%"})
        if liability_pct > 0:
            findings.append({
                "check": "Comparative negligence recorded",
                "result": True,
                "detail": f"Insured {liability_pct:.0f}% at fault; factored into subrogation estimate",
            })
    else:
        findings.append({
            "check": "No third-party involvement",
            "result": True,
            "detail": "Full loss processed under insured's own coverage",
        })

    reasoning = (
        f"Third party bears {100 - liability_pct:.0f}% liability. Subrogation recovery possible post-payment."
        if third_party
        else "No third-party involvement; standard first-party processing applies."
    )
    return AuditEntry(
        step="third_party_liability",
        title="Third-party liability assessment",
        status="info",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 10: Subrogation Potential ────────────────────────────────────────────

def _run_subrogation(c: ClaimInput) -> AuditEntry:
    findings: list[dict[str, Any]] = []
    loss = c.claimed_loss_amount
    other_party_pct = (100.0 - c.insured_liability_percent) / 100.0
    recoverable = loss * other_party_pct

    viable = c.third_party_liable and recoverable >= SUBROGATION_MIN_THRESHOLD
    findings.append({
        "check": f"Subrogation viable (third-party liable + gross recovery ≥ ${SUBROGATION_MIN_THRESHOLD:,.0f})",
        "result": viable,
        "detail": "Threshold not met or no third party" if not viable else f"Gross recoverable ${recoverable:,.2f}",
    })

    if viable:
        est_recovery = round(recoverable * SUBROGATION_RECOVERY_RATE, 2)
        findings.append({"label": "Gross recoverable amount", "value": f"${recoverable:,.2f}"})
        findings.append({
            "label": f"Estimated net recovery ({SUBROGATION_RECOVERY_RATE * 100:.0f}% industry avg)",
            "value": f"${est_recovery:,.2f}",
        })
        findings.append({
            "check": "Subrogation file flagged for recovery unit",
            "result": True,
            "detail": "Recovery unit notified upon claim closure",
        })
        reasoning = f"Subrogation recommended. Estimated net recovery ${est_recovery:,.2f} from third party."
    else:
        reasoning = "No subrogation action recommended for this claim."

    return AuditEntry(
        step="subrogation",
        title="Subrogation potential",
        status="info",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 11: Compliance Check ─────────────────────────────────────────────────

def _compliance_rules(c: ClaimInput, docs: set[str]) -> tuple[bool, list[dict[str, Any]]]:
    violations: list[dict[str, Any]] = []
    m, pol = c.metadata, c.policy_info
    loss = c.claimed_loss_amount
    claim_line = m.claim_line.lower()
    cov = pol.coverage_type.lower()

    is_auto_collision = pol.policy_type == "auto" and (
        "collision" in claim_line or "auto_collision" == claim_line or cov == "collision"
    )
    if is_auto_collision and loss > 500 and "police_report" not in docs:
        violations.append({
            "rule": "Auto collision claims over $500 require a police report",
            "violated": True,
            "detail": f"Loss ${loss:,.2f}; document tag 'police_report' not in provided list",
        })

    if pol.policy_type == "homeowners" and ("dwelling" in claim_line or "dwelling" in cov):
        if loss > 1000:
            photo_ok = "photos" in docs or "site_photos" in docs or "photo_documentation" in docs
            if not photo_ok:
                violations.append({
                    "rule": "Homeowners dwelling claims over $1,000 require photo documentation",
                    "violated": True,
                    "detail": f"Loss ${loss:,.2f}; need 'photos', 'site_photos', or 'photo_documentation'",
                })

    if "uninsured_motorist" in claim_line or cov == "uninsured_motorist":
        if loss > 2500 and "witness_statement" not in docs:
            violations.append({
                "rule": "Uninsured motorist claims over $2,500 require witness statement",
                "violated": True,
                "detail": "Provide 'witness_statement' for regulatory file completeness",
            })

    return len(violations) == 0, violations


def _run_compliance(c: ClaimInput) -> tuple[bool, AuditEntry]:
    docs = _norm_docs(c.documents_provided)
    passed, violations = _compliance_rules(c, docs)

    findings: list[dict[str, Any]] = [
        {
            "check": "Required documents for claim type and amount",
            "result": passed,
            "violations": violations,
        },
        {
            "check": "Documents provided (normalized)",
            "result": True,
            "detail": sorted(docs) if docs else [],
        },
    ]

    reasoning = (
        "All applicable compliance rules satisfied."
        if passed
        else f"Compliance failures: {len(violations)} rule(s) violated."
    )
    return passed, AuditEntry(
        step="compliance",
        title="Compliance check",
        status="pass" if passed else "fail",
        findings=findings,
        reasoning=reasoning,
    )


# ── Step 12: Reserve Setting ──────────────────────────────────────────────────

def _run_reserve_setting(c: ClaimInput, estimated_payout: float) -> AuditEntry:
    pol = c.policy_info
    buffer = round(estimated_payout * RESERVE_BUFFER_PCT, 2)
    reserve = round(min(estimated_payout + buffer, pol.policy_limit), 2)

    findings: list[dict[str, Any]] = [
        {"label": "Base estimated payout", "value": f"${estimated_payout:,.2f}"},
        {"label": f"Contingency buffer ({RESERVE_BUFFER_PCT * 100:.0f}%)", "value": f"${buffer:,.2f}"},
        {"label": "Initial reserve (capped at policy limit)", "value": f"${reserve:,.2f}"},
        {"label": "Policy limit", "value": f"${pol.policy_limit:,.2f}"},
        {
            "check": "Reserve within policy limit",
            "result": reserve <= pol.policy_limit,
            "detail": f"${reserve:,.2f} ≤ ${pol.policy_limit:,.2f}",
        },
    ]

    return AuditEntry(
        step="reserve_setting",
        title="Reserve setting",
        status="info",
        findings=findings,
        reasoning=(
            f"Initial reserve set at ${reserve:,.2f} "
            f"(payout estimate + {RESERVE_BUFFER_PCT * 100:.0f}% contingency, capped at policy limit)."
        ),
    )


# ── Step 13: Payout Calculation ───────────────────────────────────────────────

def _calculate_payout(c: ClaimInput) -> tuple[float, AuditEntry]:
    pol = c.policy_info
    loss = c.claimed_loss_amount
    after_ded = max(0.0, loss - pol.deductible)
    gross = after_ded * pol.coinsurance
    payout = min(gross, pol.policy_limit)
    payout = round(payout, 2)

    findings: list[dict[str, Any]] = [
        {"label": "Claimed loss", "value": f"${loss:,.2f}"},
        {"label": "Deductible", "value": f"${pol.deductible:,.2f}"},
        {"label": "Loss after deductible", "value": f"${after_ded:,.2f}"},
        {"label": "Coinsurance", "value": f"{pol.coinsurance * 100:.0f}%"},
        {"label": "After coinsurance (before limit)", "value": f"${gross:,.2f}"},
        {"label": "Policy limit", "value": f"${pol.policy_limit:,.2f}"},
        {"label": "Final payout (capped)", "value": f"${payout:,.2f}"},
    ]

    return payout, AuditEntry(
        step="payout",
        title="Payout calculation",
        status="info",
        findings=findings,
        reasoning=(
            "Payout = min(max(0, claimed_loss − deductible) × coinsurance, policy_limit). "
            f"Result ${payout:,.2f}."
        ),
    )


# ── Decision Gate ─────────────────────────────────────────────────────────────

def _finalize(
    intake_ok: bool,
    identity_ok: bool,
    policy_ok: bool,
    elig_ok: bool,
    coverage_ok: bool,
    exclusion_ok: bool,
    duplicate_ok: bool,
    compliance_ok: bool,
    fraud_score: int,
    payout: float,
) -> tuple[str, float | None, str]:
    if not intake_ok:
        return "DENY", None, "Denied: claim packet incomplete (missing narrative or supporting documents)."
    if not identity_ok:
        return "DENY", None, "Denied: claimant identity mismatch between metadata and policy record."
    if not policy_ok:
        return "DENY", None, "Denied: policy record has inconsistencies that prevent processing."
    if not elig_ok:
        return "DENY", None, "Denied: failed eligibility (coverage window, statute of limitations, or amount)."
    if not coverage_ok:
        return "DENY", None, "Denied: incident type is not a covered peril under this policy's coverage type."
    if not exclusion_ok:
        return "DENY", None, "Denied: claim falls within a policy-specific or universal exclusion."
    if not duplicate_ok:
        return "HOLD_FOR_REVIEW", None, "Held: high-frequency claim pattern detected; mandatory examiner review."
    if not compliance_ok:
        return "DENY", None, "Denied: required documentation or compliance rules not satisfied."
    if fraud_score >= FRAUD_HOLD_THRESHOLD:
        return "HOLD_FOR_REVIEW", None, (
            f"Held for manual review: fraud heuristic score {fraud_score} exceeds threshold "
            f"{FRAUD_HOLD_THRESHOLD}. No automatic payment at this time."
        )
    return "APPROVE", payout, f"Approved: payout ${payout:,.2f} per policy terms."


# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="Claim Decision Simulator", version="2.0.0")


@app.on_event("startup")
def startup() -> None:
    init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    ocr_ok, ocr_detail = tesseract_available()
    llm_ok, llm_detail = llm_backend_ready(settings)
    return {
        "status": "ok",
        "ocr": {"available": ocr_ok, "detail": ocr_detail},
        "llm": {"provider": "groq", "ready": llm_ok, "detail": llm_detail},
        "debug": settings.debug,
    }


@app.get("/sample-claims")
def list_sample_claims(settings: Annotated[Settings, Depends(get_settings)]) -> list[dict[str, Any]]:
    if not settings.debug:
        raise HTTPException(status_code=404, detail="Not found")
    return _load_sample_claims()


@app.post("/simulate/from-document", response_model=SimulateResponse)
async def simulate_from_document(
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
) -> SimulateResponse:
    llm_ok, llm_detail = llm_backend_ready(settings)
    if not llm_ok:
        raise HTTPException(
            status_code=503,
            detail={"message": "LLM backend not configured or unreachable", "detail": llm_detail},
        )

    name = file.filename or "upload.bin"
    buf = bytearray()
    chunk_size = 1024 * 64
    while True:
        part = await file.read(chunk_size)
        if not part:
            break
        if len(buf) + len(part) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="File too large")
        buf.extend(part)
    data = bytes(buf)
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")

    path: Path | None = None
    try:
        path = save_upload_bytes(settings.upload_dir, data, name)
        text = extract_document_text(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail={"message": str(e)}) from e
    finally:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    try:
        return decide_from_document_text(text, settings)
    except ValueError as e:
        raise HTTPException(status_code=502, detail={"message": "LLM output invalid", "detail": str(e)}) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail={"message": str(e)}) from e


@app.post("/simulate", response_model=SimulateResponse)
def simulate(claim: ClaimInput) -> SimulateResponse:
    # Override self-reported prior claims with real count from DB
    real_prior = get_prior_claims_count(
        claim.metadata.claimant_id, claim.metadata.claim_line, claim.metadata.claim_id
    )
    if real_prior > claim.prior_claims_same_type:
        claim = claim.model_copy(update={"prior_claims_same_type": real_prior})

    intake_ok, intake_audit = _run_document_intake(claim)            # 1
    identity_ok, identity_audit = _run_identity_check(claim)         # 2
    policy_ok, policy_audit = _run_policy_verification(claim)        # 3
    elig_ok, elig_audit = _run_eligibility(claim)                     # 4
    coverage_ok, coverage_audit = _run_coverage_scope(claim)         # 5
    exclusion_ok, exclusion_audit = _run_exclusion_screening(claim)  # 6
    duplicate_ok, duplicate_audit = _run_duplicate_check(claim)      # 7
    fraud_score, _signals, fraud_audit = _run_fraud(claim)           # 8
    liability_audit = _run_third_party_liability(claim)              # 9
    subrogation_audit = _run_subrogation(claim)                      # 10
    compliance_ok, comp_audit = _run_compliance(claim)               # 11
    payout_val, payout_audit = _calculate_payout(claim)              # pre-calc for reserve
    reserve_audit = _run_reserve_setting(claim, payout_val)          # 12

    decision, payout_amt, summary = _finalize(
        intake_ok, identity_ok, policy_ok, elig_ok,
        coverage_ok, exclusion_ok, duplicate_ok, compliance_ok,
        fraud_score, payout_val,
    )

    if decision != "APPROVE":
        payout_audit = payout_audit.model_copy(
            update={
                "reasoning": payout_audit.reasoning
                + " Final decision may withhold payment; amount shown is hypothetical.",
            }
        )

    audit_trail = [
        intake_audit,      # 1
        identity_audit,    # 2
        policy_audit,      # 3
        elig_audit,        # 4
        coverage_audit,    # 5
        exclusion_audit,   # 6
        duplicate_audit,   # 7
        fraud_audit,       # 8
        liability_audit,   # 9
        subrogation_audit, # 10
        comp_audit,        # 11
        reserve_audit,     # 12
        payout_audit,      # 13
    ]

    response = SimulateResponse(
        claim_id=claim.metadata.claim_id,
        final_decision=decision,
        payout_amount=payout_amt,
        fraud_risk_score=fraud_score,
        audit_trail=audit_trail,
        summary=summary,
    )

    save_claim(claim)
    save_decision(response)

    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
