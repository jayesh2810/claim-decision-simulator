# Claim Decision Simulator

Insurance-style claim workflow demo. **Primary path:** upload a claim PDF or image → local text extraction (with OCR when needed) → **structured LLM decision via Groq** with an audit-shaped JSON response. **Secondary path:** deterministic `POST /simulate` over structured JSON when `DEBUG=true` (bundled fixtures via `GET /sample-claims`).

Stack: FastAPI backend, SvelteKit frontend.

## Local development

- **Backend (OCR + Groq):** See [backend/SETUP.md](backend/SETUP.md) and [backend/.env.example](backend/.env.example). Set `GROQ_API_KEY`. Install Python deps from [requirements.txt](requirements.txt); run `uvicorn main:app` from `backend/`.
- **Frontend:** `cd frontend && npm install && npm run dev` (proxies API calls to `http://127.0.0.1:8000` in dev).

## License

This repository is for evaluation and development unless otherwise specified.
