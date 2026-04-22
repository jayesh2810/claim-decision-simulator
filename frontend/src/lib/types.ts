export type StepStatus = 'pass' | 'fail' | 'warning' | 'info';

export type AuditEntry = {
  step: string;
  title: string;
  status: StepStatus;
  findings: Record<string, unknown>[];
  reasoning: string;
};

export type SimulateResponse = {
  claim_id: string;
  final_decision: 'APPROVE' | 'DENY' | 'HOLD_FOR_REVIEW';
  payout_amount: number | null;
  fraud_risk_score: number;
  audit_trail: AuditEntry[];
  summary: string;
};

export type ClaimRecord = Record<string, unknown>;
