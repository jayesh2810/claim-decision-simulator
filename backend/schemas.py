"""Shared Pydantic models for API requests and responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ClaimMetadata(BaseModel):
    claim_id: str
    claimant_name: str
    claimant_id: str
    policy_id: str
    incident_date: str
    claim_submission_date: str
    claim_line: str
    incident_type: str


class PolicyInfo(BaseModel):
    policy_id: str
    claimant_id: str
    policy_type: str
    coverage_type: str
    policy_start_date: str
    policy_end_date: str
    deductible: float = Field(ge=0)
    policy_limit: float = Field(gt=0)
    coinsurance: float = Field(ge=0, le=1)
    exclusions: list[str] = Field(default_factory=list)


class ClaimInput(BaseModel):
    metadata: ClaimMetadata
    claimed_loss_amount: float = Field(ge=0)
    claim_narrative: str
    documents_provided: list[str]
    prior_claims_same_type: int = Field(ge=0)
    policy_info: PolicyInfo
    jurisdiction: str = "US"
    third_party_liable: bool = False
    insured_liability_percent: float = Field(default=0.0, ge=0, le=100)


class AuditEntry(BaseModel):
    step: str
    title: str
    status: str  # pass | fail | warning | info
    findings: list[dict[str, Any]]
    reasoning: str


class SimulateResponse(BaseModel):
    claim_id: str
    final_decision: Literal["APPROVE", "DENY", "HOLD_FOR_REVIEW"]
    payout_amount: float | None
    fraud_risk_score: int = Field(ge=0, le=100)
    audit_trail: list[AuditEntry]
    summary: str

    @field_validator("fraud_risk_score", mode="before")
    @classmethod
    def coerce_fraud_int(cls, v: object) -> int:
        if isinstance(v, bool):
            raise ValueError("invalid fraud score")
        return int(round(float(v)))

    @field_validator("payout_amount", mode="before")
    @classmethod
    def coerce_payout(cls, v: object) -> float | None:
        if v is None or v == "null":
            return None
        return float(v)
