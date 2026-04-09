# TenderFlow

<img width="1912" height="867" alt="landingpage" src="https://github.com/user-attachments/assets/8a5a4647-ce86-40bb-8c4d-be842c74fb5d" />

---

**AI-powered tender response agent** built for Meridian Intelligence GmbH.  
Cuts tender drafting time from days to hours by auto-assembling company knowledge base content into a structured, human-reviewed first draft.

---

## What It Does

TenderFlow ingests an incoming tender document (PDF/DOCX), analyses its requirements, retrieves the most relevant content from Meridian's knowledge base, drafts each section of the response, and hands off to a human reviewer — all via a single upload. The reviewer edits sections in a web UI and submits feedback; the agent incorporates changes and finalises the polished DOCX output.

---

## Agent Architecture

<img width="400" height="530" alt="mermaid-diagram" src="https://github.com/user-attachments/assets/6ecb53e7-356b-4935-bcb4-2e393cc4f483" />

---

Every tool node also writes a **checkpoint** to Supabase (PostgresSaver) — the HITL interrupt/resume cycle survives process restarts.

---

## How It Works

### 1. Knowledge Base Ingestion

Before a tender is processed, Meridian's internal documents are ingested via a 6-step pipeline:

| Step | What Happens |
|------|-------------|
| **Parse** | Text extracted from PDF / DOCX / MD / XLSX |
| **Enrich** | Claude (model-routed) extracts structured JSON metadata via tool-use |
| **Guard** | 3-layer integrity check flags or blocks suspicious content |
| **Chunk** | Recursive text splitter creates ~512-token chunks |
| **Embed** | Voyage AI `voyage-3-lite` produces 512-dim vectors |
| **Upsert** | Chunks + embeddings stored in Supabase `kb_chunks` (pgvector) |

**Model routing during enrichment:**

| Document Type | Model | Reason |
|---------------|-------|--------|
| `past_tender` | Claude Opus 4.6 | Strategic nuance, positioning pattern recognition |
| `cv` | Claude Sonnet 4.6 | Structured and predictable |
| `methodology` | Claude Sonnet 4.6 | Technical but well-structured |
| `company_profile` | Claude Haiku 4.5 | Plain fact sheet — names, numbers, certifications |

KB directory layout:
```
kb/
  company/        → company_profile
  methodology/    → methodology
  past_tenders/   → past_tender
  team_cvs/       → cv
```

### 2. Tender Analysis (`analyse_tender`)

- Parses full tender text with Claude Opus
- Extracts `SectionDraft` objects (section name, requirements, doc types needed, word count target)
- Builds a compliance checklist `[{item, mandatory, category}]`
- Assigns dimension weights `W1_track_record … W5_pricing` (sum = 1.0)

### 3. Context Retrieval (`retrieve_context`)

- For each section, runs a pgvector similarity search filtered by `doc_type`, `sector_tags`, and `tender_type_tags`
- Assigns `confidence` (HIGH / MEDIUM / LOW) and a `gap_flag` if context is insufficient

### 4. Draft Generation (`draft_sections`)

- Assembles each section draft from retrieved KB chunks
- Records `sources_used` for traceability
- Scores the draft across 7 quality modules:
  - **M1–M5** (primary): track record, methodology, team, compliance, pricing — weighted sum → `primary_score_total`
  - **M6** compliance score (Haiku)
  - **M7** robustness score (Haiku)
  - **Final**: `primary × 0.60 + quality × 0.40`

### 5. Human-in-the-Loop Review (HITL)

LangGraph pauses the graph at `human_review` using `interrupt_before`. The frontend displays each draft section with its confidence, gap flags, and score. The reviewer can:

- Edit any section in-place
- Write free-text feedback
- Request another round (up to 3 iterations)

The API resumes the graph via:
```python
graph.update_state(config, {user_edits, user_feedback, hitl_iteration})
graph.invoke(None, config)
```

### 6. Finalise & Export (`finalise`)

- Polishes human-edited sections with Claude Sonnet
- Generates a `.docx` output file via `python-docx`
- Stores the output path in `TenderState.output_path`

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent framework | LangGraph `StateGraph` |
| LLM | Anthropic Claude — Opus 4.6 / Sonnet 4.6 / Haiku 4.5 (model-routed) |
| Embeddings | Voyage AI `voyage-3-lite` (512 dim) |
| Vector store | Supabase pgvector |
| Checkpointing | `langgraph-checkpoint-postgres` → Supabase PostgreSQL |
| Backend | Python 3.11, FastAPI, `uv` |
| Frontend | React 18, Vite |
| Document output | `python-docx` |

---

## Project Structure

```
TenderFlow/
├── backend/
│   ├── agents/
│   │   ├── graph.py          # StateGraph topology + PostgresSaver checkpointer
│   │   ├── state.py          # TenderState + SectionDraft TypedDicts
│   │   └── nodes/            # analyse_tender, retrieve_context, draft_sections,
│   │                         #   human_review, finalise
│   ├── tools/
│   │   ├── ingest_tool.py    # parse→enrich→guard→chunk→embed→upsert pipeline
│   │   ├── retrieval_tool.py # pgvector search helper
│   │   └── output_tool.py    # DOCX generation
│   ├── enrichment/
│   │   ├── model_router.py   # doc_type → Claude model mapping
│   │   ├── schemas.py        # Tool-use schemas per doc_type
│   │   └── guard.py          # 3-layer integrity checks
│   ├── core/
│   │   ├── document_parser.py
│   │   ├── chunker.py
│   │   ├── embeddings.py     # Voyage AI client
│   │   └── supabase_client.py
│   ├── api/
│   │   └── routers/
│   │       └── hitl.py       # HITL resume endpoint (update_state + invoke)
│   ├── config/settings.py
│   └── main.py               # FastAPI app + lifespan (graph initialisation)
├── frontend/
│   └── src/
│       └── App.jsx           # React UI — upload, review, chat, export
├── Knowledge Base/
│   └── kb/                   # Seed documents (company, methodology, past_tenders, team_cvs)
└── README.md
```

---

## State Machine

The `TenderState` TypedDict is the spine of the system — every node reads from and writes to it, and it is fully checkpointed to Supabase after every transition.

```
SectionDraft lifecycle:
  analyse_tender   → section_id, section_name, requirements, doc_types_needed
  retrieve_context → confidence, gap_flag
  draft_sections   → draft_text, sources_used
  [HITL interrupt] → user_edits (injected via API)
  finalise         → finalised_content
```

Status constants tracked throughout: `pending → analysing → retrieving → drafting → awaiting_review → finalising → done`

---

## Setup

### Backend

```bash
cd backend
uv sync
cp .env.example .env   # fill in ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_DB_URL, VOYAGE_API_KEY
uv run uvicorn main:app --reload
```

Run the Supabase migration once:
```sql
-- paste contents of backend/db/migrations/001_initial_schema.sql into Supabase SQL Editor
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Seed the Knowledge Base

```python
from tools.ingest_tool import bulk_ingest_kb_directory
bulk_ingest_kb_directory("../Knowledge Base/kb")
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `VOYAGE_API_KEY` | Voyage AI API key |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anon key |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (admin writes) |
| `SUPABASE_DB_URL` | PostgreSQL connection string (transaction-mode pooler) |
| `MAX_HITL_ITERATIONS` | Max human review rounds (default: 3) |
