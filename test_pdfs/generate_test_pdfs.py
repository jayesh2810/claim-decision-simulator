#!/usr/bin/env python3
"""
Generate three synthetic FNOL-style PDFs for manual upload testing.
Run from project root:  python3 test_pdfs/generate_test_pdfs.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUT_DIR = Path(__file__).resolve().parent


def _build_pdf(path: Path, title: str, body_lines: list[str]) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    h = ParagraphStyle(
        "H",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=12,
    )
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=10, leading=14)
    story: list = [Paragraph(title, h), Spacer(1, 0.2 * inch)]
    for line in body_lines:
        if line.strip() == "":
            story.append(Spacer(1, 0.15 * inch))
        else:
            story.append(Paragraph(line.replace("&", "&amp;"), body))
    doc.build(story)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Matches backend/seeds/fixtures/CLM-2026-GT-001_fnol.json + claims.db seed for GT-001
    _build_pdf(
        OUT_DIR / "01_ground_truth_matches_db.pdf",
        "First Notice of Loss — Auto (ground truth, matches CLM-2026-GT-001 in DB)",
        [
            "Claim ID: <b>CLM-2026-GT-001</b>",
            "Claimant: Alice GroundTruth | Claimant ID: CLMT-GT-90001",
            "Policy ID: POL-GT-90001 | Line: auto_collision | Incident type: vehicle_collision",
            "Incident date: 2026-03-10 | Submitted: 2026-03-12 | Jurisdiction: US-CA",
            "Policy period: 2025-01-10 through 2028-01-10 | Type: auto / collision",
            "Deductible: $500.00 | Policy limit: $50,000.00 | Coinsurance: 100%",
            "Claimed loss: <b>$12,450.00</b> | Third party liable: yes | Insured fault %: 0",
            "",
            "<b>Statement of loss</b>",
            "Rear-end collision on Harbor Blvd while stopped at a traffic light. The other driver "
            "admitted fault; photos show bumper and tail lamp damage. Police report and written "
            "estimate from AllStar Collision attached.",
            "",
            "<b>Documents provided</b>",
            "police_report, repair_estimate, photos, insurance_card_copy",
        ],
    )

    # 2) Same insured/policy identity as DB but key fields differ (wrong dates, amount, id typo)
    _build_pdf(
        OUT_DIR / "02_partial_mismatch_from_db.pdf",
        "First Notice of Loss — Auto (partial mismatch vs seeded GT-001)",
        [
            "Claim ID: <b>CLM-2026-GT-001-B</b> (note: similar but not the seeded ID)",
            "Claimant: Alice GroundTruth | Claimant ID: CLMT-GT-90001",
            "Policy ID: POL-GT-90001 | Line: auto_collision | Incident type: vehicle_collision",
            "Incident date: <b>2026-04-02</b> (differs from DB) | Submitted: 2026-04-10 | Jurisdiction: US-CA",
            "Policy period: 2025-01-10 through 2028-01-10 | Type: auto / collision",
            "Deductible: $500.00 | Policy limit: $50,000.00 | Coinsurance: 100%",
            "Claimed loss: <b>$18,200.00</b> (differs from DB $12,450) | Third party liable: yes | Insured fault %: 0",
            "",
            "<b>Statement of loss</b>",
            "Rear-end collision on Harbor Blvd while stopped at a traffic light. The other driver "
            "admitted fault; additional damage to rear body panel was found on tear-down. "
            "Supplemental estimate from AllStar Collision is attached (higher than initial quote).",
            "",
            "<b>Documents provided</b>",
            "police_report, repair_estimate, photos, insurance_card_copy",
        ],
    )

    # 3) Unrelated to seeded DB rows (fictional marine liability style claim)
    _build_pdf(
        OUT_DIR / "03_completely_different_from_db.pdf",
        "First Notice of Loss — Fictional (no match to ground-truth seed data)",
        [
            "Claim ID: <b>MAR-2026-7007</b>",
            "Claimant: <b>Captain Morgan Vessel Co.</b> | Insured ID: WTR-UNRELATED-12",
            "Policy ID: <b>PLY-MAR-555</b> | Line: marine_cargo | Incident type: dock_loading_damage",
            "Incident date: 2026-01-20 | Submitted: 2026-01-22 | Jurisdiction: US-LA",
            "Policy period: 2024-06-01 through 2027-05-31 | Deductible: $2,500 | Limit: $500,000",
            "Claimed loss: <b>$87,450.00</b> (storm-damaged container stack during offloading; crane strike)",
            "",
            "<b>Statement of loss</b>",
            "During hurricane-season offload at Port of South Louisiana, a mobile crane contact caused "
            "structural damage to a refrigerated container. Surveyor report and stevedore logs are attached. "
            "This claim is entirely unrelated to the auto/homeowners test records in the Claim Decision Simulator DB.",
            "",
            "<b>Documents</b>: surveyor_report, port_incident_log, photos, bill_of_lading",
        ],
    )

    for p in sorted(OUT_DIR.glob("*.pdf")):
        print(p)


if __name__ == "__main__":
    main()
    print("Done. PDFs are in:", OUT_DIR)
