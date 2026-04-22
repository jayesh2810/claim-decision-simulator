# Backend setup (OCR + Groq)

## Prerequisites

1. **Python 3.10+** and dependencies from the repo root: `pip install -r requirements.txt`.
2. **Tesseract OCR** (required for image uploads and for scanned PDF pages with little or no text layer).
   - macOS: `brew install tesseract`
   - Ubuntu/Debian: `sudo apt install tesseract-ocr`
3. **Groq:** Create an API key at [Groq Console](https://console.groq.com/). Set `GROQ_API_KEY` in `backend/.env` (see `.env.example`). Optional: `GROQ_MODEL` (default `qwen/qwen3-32b`).

## Configuration

Copy `backend/.env.example` to `backend/.env` and set `GROQ_API_KEY`. Do not commit real keys.

Optional: set `DEBUG=true` to enable `GET /sample-claims` with bundled JSON fixtures for deterministic `POST /simulate` demos.

## Run the API

From the repo root (or from `backend/`):

```bash
cd backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Check readiness: `GET /health` reports Tesseract and Groq configuration status (`llm.provider` is always `groq`).

## Document flow

`POST /simulate/from-document` accepts `multipart/form-data` with field name **`file`**. Allowed types: PDF, PNG, JPEG, WebP, TIFF, JSON (UTF-8 claim payload as text for the LLM).

## Ground-truth test data (SQLite + JSON)

Run from `backend/`:

```bash
python3 seed_ground_truth.py
```

This **wipes** `claimants`, `policies`, `claims`, `claim_decisions`, and `adjuster_reviews`, then inserts a small fake book of business and writes matching FNOL JSON files to **`backend/seeds/fixtures/`**. Use those JSON files as **document uploads** in the UI; the text matches what is in `claims.db` for the same `claim_id` (use **`CLM-2026-GT-001_fnol.json`** for a clean auto baseline, and **`CLM-2026-GT-002_fnol_bob_with_prior_in_db.json`** to verify `/simulate` overrides prior claims using DB history).
