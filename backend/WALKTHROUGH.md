# TenderFlow — Backend Walkthrough

End-to-end guide: setup → seed KB → run a tender → HITL loop → download DOCX.

---

## 1. Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | ≥ 3.11 | Runtime |
| uv | latest | Virtual env + dependency management |
| Supabase project | any | Vector DB + checkpointing |
| Anthropic API key | — | claude-sonnet-4-6, haiku, opus |
| Voyage AI API key | — | voyage-3-lite embeddings |

Get a Voyage AI key at https://dash.voyageai.com (free tier is enough for the demo).

---

## 2. Project Setup

```bash
# From repo root
cd backend

# Create virtual environment and install all dependencies
uv sync

# Copy environment template
cp .env.example .env
# → Fill in all values in .env (see Section 3)

# Create runtime directories
mkdir -p uploads outputs
```

---

## 3. Environment Variables

Edit `backend/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=pa-...

SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# CRITICAL: Must be the transaction-mode pooler URL (port 6543)
# Supabase Dashboard → Settings → Database → Connection string → Transaction mode
SUPABASE_DB_URL=postgresql://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres

ADMIN_KEY=demo-admin-key-2026
```

---

## 4. Supabase Schema Setup

Run the migration **once** in the Supabase SQL Editor:

```
Supabase Dashboard → SQL Editor → New query
→ Paste contents of: backend/db/migrations/001_initial_schema.sql
→ Run
```

This creates:
- `kb_documents`, `kb_chunks`, `kb_enrichments` — knowledge base storage
- `kb_facts`, `kb_vocabulary`, `kb_pending_reviews` — integrity guard support
- `tender_jobs` — agent job tracking
- `match_kb_chunks` RPC — pgvector similarity search function
- IVFFlat index on `kb_chunks.embedding`

---

## 5. Start the Server

```bash
cd backend
uv run uvicorn main:app --reload --port 8000
```

On startup, the app:
1. Creates `uploads/` and `outputs/` directories
2. Compiles the LangGraph StateGraph
3. Runs `checkpointer.setup()` — creates LangGraph checkpoint tables in Supabase (idempotent)

API docs available at: http://localhost:8000/docs

---

## 6. Seed the Knowledge Base

Run the bulk ingest to load all 13 documents from `Knowledge Base/kb/`:

```bash
curl -X POST http://localhost:8000/ingest/bulk \
  -H "X-Admin-Key: demo-admin-key-2026"
```

Response:
```json
{
  "total": 13,
  "committed": 11,
  "guard_blocked": 0,
  "guard_flagged": 2,
  "errors": 0,
  "results": [...]
}
```

What happens per document:
1. **Parse** — PyMuPDF (PDF), python-docx (DOCX), UTF-8 (MD/TXT), openpyxl (XLSX)
2. **Enrich** — Claude extracts structured JSON metadata (Opus/Sonnet/Haiku by doc_type)
3. **Guard** — 3-layer integrity check (structural → provenance → cross-doc consistency)
4. **Chunk** — RecursiveCharacterTextSplitter (600 chars, 80 overlap)
5. **Embed** — voyage-3-lite → 512-dim vectors
6. **Upsert** — `kb_documents` + `kb_chunks` + `kb_enrichments` rows in Supabase

Documents in `guard_flagged` are committed but flagged for review.  
Check them at: `GET /kb/pending-reviews` (requires X-Admin-Key).

---

## 7. Add a Single Document

```bash
curl -X POST http://localhost:8000/ingest/document \
  -F "file=@path/to/new_cv.md" \
  -F "doc_type=cv" \
  -F "source_name=New Team Member CV" \
  -F "uploaded_by=project_manager"
```

Returns `task_id`. Poll status:

```bash
curl http://localhost:8000/ingest/status/<task_id>
```

---

## 8. Run a Tender

### Step 1 — Upload the tender document and start the agent

```bash
curl -X POST http://localhost:8000/tender/start \
  -F "file=@path/to/tender.pdf"
```

Returns: `{"tender_id": "abc123...", "status": "pending"}`

### Step 2 — Poll until awaiting_review

```bash
curl http://localhost:8000/tender/abc123.../status
```

Status progression: `pending → analysing → retrieving → drafting → awaiting_review`

Each status maps to a LangGraph node:
- `analysing`       → `analyse_tender` (Haiku extracts sections + compliance checklist)
- `retrieving`      → `retrieve_context` (pgvector search per section, Primary Score M1-M5)
- `drafting`        → `draft_sections` (Sonnet drafts each section, Quality Score M6-M7)
- `awaiting_review` → graph paused before `human_review` interrupt

When `status == "awaiting_review"`, `sections` and `score_json` are populated in the response.

### Step 3 — Fetch the draft for review

```bash
curl http://localhost:8000/tender/abc123.../review
```

Returns:
```json
{
  "tender_id": "abc123...",
  "hitl_iteration": 0,
  "final_score": 73.4,
  "sections": [
    {
      "section_id": "company_background",
      "section_name": "Company Background",
      "draft_text": "Meridian Intelligence GmbH...",
      "confidence": "HIGH",
      "gap_flag": null,
      "sources_used": ["Company Profile Docx", "Capabilities Overview Pdf"]
    },
    {
      "section_id": "technical_approach",
      "section_name": "Technical Approach",
      "draft_text": "...",
      "confidence": "HIGH",
      "gap_flag": null
    },
    {
      "section_id": "team_composition",
      "section_name": "Team Composition",
      "draft_text": "[INSUFFICIENT CONTEXT] ...",
      "confidence": "LOW",
      "gap_flag": "No relevant cv content found in KB"
    }
  ],
  "score_justifications": {
    "Final Score": "73.4/100 — Primary (60%) + Quality (40%) weighted composite. Band: MODERATE"
  }
}
```

### Step 4 — Submit user edits

The frontend presents each `draft_text` in an editable textarea. The user edits, adds overall feedback, then submits:

```bash
curl -X POST http://localhost:8000/tender/abc123.../submit \
  -H "Content-Type: application/json" \
  -d '{
    "sections": [
      {"section_id": "company_background", "user_edits": "...edited text..."},
      {"section_id": "technical_approach", "user_edits": ""},
      {"section_id": "team_composition", "user_edits": ""}
    ],
    "feedback": "Make the tone more assertive. Reduce passive voice.",
    "request_another_round": false
  }'
```

Rules:
- `user_edits = ""`      → section kept as AI draft (no Sonnet polish applied)
- `user_edits = "..."`   → Sonnet applies finishing touches using `feedback`
- `request_another_round: true` → after finalise, loops back to `awaiting_review` (max 3 rounds)

### Step 5 — Wait for finalise

Poll `/tender/abc123.../status` until `status == "done"`.

What happens:
1. `finalise` node runs — Sonnet polishes each edited section
2. `output_tool` renders the DOCX with:
   - Cover page (score + band)
   - Readiness Assessment table
   - Action Items checklist (gap flags)
   - All sections with confidence indicators and source citations
3. DOCX saved to `outputs/{tender_id}.docx`

### Step 6 — Download the DOCX

```bash
curl -O http://localhost:8000/tender/abc123.../download
```

Returns the `.docx` file directly.

---

## 9. HITL Loop (Multiple Rounds)

If `request_another_round: true` was submitted, after `finalise` runs the graph
routes back to the `human_review` interrupt. Status returns to `awaiting_review`.
The sections now contain `finalised_content` from round 1 as the new draft base.

The loop is capped at `MAX_HITL_ITERATIONS=3` (configurable in `.env`).

```
Round 1:  draft_text      → user edits → finalised_content (v1)
Round 2:  finalised_content (v1) → user edits → finalised_content (v2)
Round 3:  finalised_content (v2) → user edits → finalised_content (v3) → DOCX
```

---

## 10. Knowledge Base Management

```bash
# List all documents
curl http://localhost:8000/kb/documents

# Get document + enrichment detail
curl http://localhost:8000/kb/documents/<doc_id>

# Soft-delete a document (excludes it from future retrievals)
curl -X DELETE http://localhost:8000/kb/<doc_id> \
  -H "X-Admin-Key: demo-admin-key-2026"

# Review guard-flagged documents
curl http://localhost:8000/kb/pending-reviews \
  -H "X-Admin-Key: demo-admin-key-2026"
```

---

## 11. Architecture at a Glance

```
backend/
├── config/
│   └── settings.py          ← All secrets from .env via Pydantic BaseSettings
│
├── core/                    ← Pure utilities, no business logic
│   ├── embeddings.py        ← voyage-3-lite wrapper (512-dim)
│   ├── supabase_client.py   ← Singleton anon + admin clients
│   ├── document_parser.py   ← PDF / DOCX / MD / XLSX → plain text
│   └── chunker.py           ← RecursiveCharacterTextSplitter (600/80)
│
├── enrichment/              ← One-time KB quality layer (runs at ingest time)
│   ├── schemas.py           ← Anthropic tool-use schemas per doc_type
│   ├── model_router.py      ← doc_type → Opus / Sonnet / Haiku
│   └── guard.py             ← 3-layer integrity guard (structural → provenance → cross-doc)
│
├── tools/                   ← Composable pipeline functions
│   ├── ingest_tool.py       ← Full ingest pipeline (parse→enrich→guard→chunk→embed→upsert)
│   ├── retrieval_tool.py    ← pgvector cosine search with doc_type filter
│   └── output_tool.py       ← TenderState → formatted DOCX
│
├── agents/                  ← LangGraph StateGraph
│   ├── state.py             ← TenderState TypedDict (spine of the system)
│   ├── graph.py             ← StateGraph wiring + PostgresSaver checkpointer
│   ├── nodes/
│   │   ├── analyse_tender.py   ← Haiku: sections + checklist + dimension weights
│   │   ├── retrieve_context.py ← pgvector per section + Primary Score (M1-M5)
│   │   ├── draft_sections.py   ← Sonnet: draft + Quality Score (M6-M7)
│   │   ├── human_review.py     ← Named interrupt target (no-op pass-through)
│   │   └── finalise.py         ← Sonnet: polish edits → render DOCX
│   └── prompts/
│       ├── analyse_tender.txt
│       ├── draft_section.txt
│       └── finalise.txt
│
├── api/
│   ├── routers/
│   │   ├── ingest.py  ← POST /ingest/document, /ingest/bulk, GET /ingest/status
│   │   ├── tender.py  ← POST /tender/start, GET /tender/{id}/status + /download
│   │   ├── hitl.py    ← GET /tender/{id}/review, POST /tender/{id}/submit
│   │   └── kb.py      ← GET /kb/documents, DELETE /kb/{doc_id}
│   └── schemas/       ← Pydantic request/response models
│
├── db/migrations/
│   └── 001_initial_schema.sql  ← Run once in Supabase SQL Editor
│
├── main.py              ← FastAPI app + CORS + lifespan startup
└── WALKTHROUGH.md       ← This file
```

---

## 12. Scoring Quick Reference

```
Primary Score  = Σ(module_score_i × weight_i) / Σ(weight_i)   [M1-M5, computed in retrieve_context]
Quality Score  = Compliance × 0.55 + Robustness × 0.45        [M6-M7, computed in draft_sections]
Final Score    = Primary × 0.60 + Quality × 0.40

Bands:  90-100 EXCELLENT  |  75-89 STRONG  |  60-74 MODERATE  |  <60 WEAK
```

The DOCX opens with a Readiness Assessment table showing all four dimensions,
justification text, and an Action Items checklist of gap flags.

---

## 13. Common Issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `SUPABASE_DB_URL` connection error | Wrong URL format | Use transaction-mode pooler (port 6543), not direct (5432) |
| `voyageai` API key error | VOYAGE_API_KEY not set | Add to .env; create account at dash.voyageai.com |
| Bulk ingest returns 0 committed | KB path wrong | Confirm `KB_SEED_DIR` points to `../Knowledge Base/kb` |
| Guard blocks all docs | Enrichment returning wrong values | Check Opus/Sonnet models are available on your Anthropic plan |
| Graph never reaches `awaiting_review` | `interrupt_before` not firing | Confirm `langgraph>=0.2` installed; check `get_graph()` has `interrupt_before=["human_review"]` |
| Download returns 404 | Output path not set | Check `outputs/` dir exists and is writable |
