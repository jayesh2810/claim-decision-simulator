# CLAUDE.md

Guidance for Claude Code, Cursor, and similar tools when working in this repository.

## Response style (optional)

- **Goal:** Minimize token usage where it helps.
- **No filler:** Skip “Sure, I can help” openers; start with the answer or change.
- **Direct:** Short bullets when listing steps; keep code production-ready (concise chat ≠ sloppy code).
- **Partial updates:** Prefer targeted edits; use `// ... existing code ...` in snippets when showing context.

---

## Commands

### Backend

```bash
# Install dependencies
pip install -r requirements.txt

# Run backend (from backend/ — required for local imports)
cd backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # dev server on :5173
npm run build      # production build
npm run check      # svelte-check + tsc
npm run lint       # eslint + prettier check
npm run format     # prettier write
```

## Environment

Copy `backend/.env.example` to `backend/.env` and set:

- `GROQ_API_KEY` — required for document upload path (get from console.groq.com)
- `GROQ_MODEL` — defaults to `qwen/qwen3-32b`
- `DEBUG=true` — enables `/sample-claims` endpoint and deterministic demo path
- `MAX_UPLOAD_BYTES`, `DOCUMENT_TEXT_MAX_CHARS`, `LLM_TIMEOUT_SECONDS` — optional tuning

System dep: **Tesseract** (`brew install tesseract` on macOS) for OCR on scanned PDFs/images.

## Architecture

Two simulation paths converge on the same `SimulateResponse` schema:

**Path 1 — Document upload** (`POST /simulate/from-document`):
File → `ingestion.py` (PyMuPDF text + Tesseract OCR fallback) → `llm_decision.py` (Groq API with structured JSON prompt) → `SimulateResponse`

**Path 2 — Structured JSON** (`POST /simulate`, DEBUG only):
`ClaimInput` JSON → deterministic 4-step pipeline in `main.py` → `SimulateResponse`

Both paths return an **audit trail**: an ordered list of `AuditEntry` objects (step, title, status, findings[], reasoning).

### Backend key files

- `main.py` — FastAPI app + deterministic pipeline: eligibility → fraud scoring (heuristic 0–100) → compliance (doc tags vs rules) → payout math (`min(max(0, loss - deductible) × coinsurance, policy_limit)`)
- `schemas.py` — All Pydantic models (`ClaimInput`, `SimulateResponse`, `AuditEntry`)
- `llm_decision.py` — Groq HTTP client; strips JSON fences, validates against `SimulateResponse`
- `ingestion.py` — PDF/image text extraction; missing Tesseract degrades gracefully
- `prompts/decision.txt` — System prompt instructing Groq to emit the exact audit JSON shape
- `settings.py` — Pydantic Settings reading `backend/.env`

### Frontend key files

- `src/routes/+page.svelte` — Entire UI (702 lines): file drag-drop, sample selector, Mermaid flowchart, animated step reveals (280ms stagger), decision badge + payout display, JSON download
- `src/lib/DecisionStep.svelte` — Collapsible audit step card with color-coded status badges
- `src/lib/types.ts` — TypeScript mirrors of backend Pydantic models

Vite dev proxy forwards `/health`, `/sample-claims`, `/simulate*` to `http://127.0.0.1:8000`.

### Key constants (main.py)

- `STATUTE_OF_LIMITATIONS_YEARS = 3`
- `FRAUD_HOLD_THRESHOLD = 70` — fraud score ≥ 70 triggers HOLD_FOR_REVIEW
