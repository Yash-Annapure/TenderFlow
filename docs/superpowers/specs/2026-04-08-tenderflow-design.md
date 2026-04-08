# TenderFlow — System Design Document
**Date:** 2026-04-08 | **Challenge:** ISTARI @ Q-Hack 2026 | **Company:** Meridian Intelligence GmbH

---

## 1. Problem Statement

Meridian Intelligence GmbH responds to EU institutional tenders requiring assembly of the same core content — CVs, methodology descriptions, past project references, pricing — in different combinations and framings per submission. The process is manual, takes days, and the content already exists.

**TenderFlow** ingests a tender document, retrieves relevant institutional knowledge from a curated KB, and generates a structured, scored, editable first draft ready for human refinement — with a HITL review loop baked into the agent graph.

**Winning criterion:** A strong draft that correctly surfaces the right content, correctly identifies gaps, and cuts drafting time dramatically. Human stays in the loop; agent does the heavy lifting.

---

## 2. Directory Structure

```
TenderFlow/
├── kb/                              # Seed KB documents (read-only for initial ingest)
│   ├── company/
│   ├── methodology/
│   ├── past_tenders/
│   ├── team_cvs/
│   └── sample_tender1_for_building.pdf
│
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── .env                         # gitignored
│   ├── main.py                      # FastAPI app entry point
│   │
│   ├── config/
│   │   └── settings.py              # Pydantic BaseSettings — all secrets from .env
│   │
│   ├── core/
│   │   ├── embeddings.py            # voyage-3-lite wrapper (voyageai SDK)
│   │   ├── supabase_client.py       # Singleton supabase-py client
│   │   ├── document_parser.py       # PyMuPDF + pdfplumber + python-docx + openpyxl
│   │   └── chunker.py               # RecursiveCharacterTextSplitter (600 tokens, 80 overlap)
│   │
│   ├── enrichment/
│   │   ├── model_router.py          # doc_type → Opus / Sonnet / Haiku
│   │   ├── schemas.py               # Enrichment JSON schemas per doc_type
│   │   └── guard.py                 # 3-layer integrity guard (structural, provenance, cross-doc)
│   │
│   ├── tools/
│   │   ├── ingest_tool.py           # Parse → chunk → enrich → guard → embed → upsert
│   │   ├── retrieval_tool.py        # pgvector cosine search with doc_type filter
│   │   └── output_tool.py           # Render TenderState → DOCX (python-docx)
│   │
│   ├── agents/
│   │   ├── state.py                 # TenderState TypedDict — spine of the system
│   │   ├── graph.py                 # StateGraph: nodes + edges + interrupt config
│   │   ├── nodes/
│   │   │   ├── analyse_tender.py    # Haiku: sections + checklist + dimension weights
│   │   │   ├── retrieve_context.py  # Retrieval + primary scoring (Modules 1–5)
│   │   │   ├── draft_sections.py    # Sonnet: draft per section + quality scoring (M6–7)
│   │   │   ├── human_review.py      # Named interrupt target node
│   │   │   └── finalise.py          # Apply edits, finishing touches, render DOCX
│   │   └── prompts/
│   │       ├── analyse_tender.txt
│   │       ├── draft_section.txt
│   │       └── finalise.txt
│   │
│   └── api/
│       ├── routers/
│       │   ├── ingest.py            # POST /ingest/document, POST /ingest/bulk, GET /ingest/status/{id}
│       │   ├── tender.py            # POST /tender/start, GET /tender/{id}/status, GET /tender/{id}/download
│       │   ├── hitl.py              # GET /tender/{id}/review, POST /tender/{id}/submit
│       │   └── kb.py                # GET /kb/documents, DELETE /kb/{doc_id}
│       └── schemas/                 # Pydantic request/response models
│
├── uploads/                         # Transient file landing zone (gitignored)
└── outputs/                         # Generated DOCX outputs (gitignored)
```

---

## 3. Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Async; team strength |
| Agent framework | LangGraph (StateGraph) | HITL interrupt + Supabase checkpointing |
| LLMs | claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5-20251001 | Model-routed by task |
| Embeddings | voyage-3-lite via `voyageai` SDK | 512-dim; separate VOYAGE_API_KEY |
| Vector store + DB | Supabase (pgvector + PostgreSQL) | Vectors + relational + storage + checkpoints |
| PDF parsing | PyMuPDF (text) + pdfplumber (tables) | Layered for accuracy |
| DOCX/MD/XLSX | python-docx, native text, openpyxl | Meridian's KB has all formats |
| Chunking | LangChain RecursiveCharacterTextSplitter | Paragraph-boundary aware |
| Output | python-docx → DOCX | Editable by non-technical users |
| Checkpointing | langgraph-checkpoint-postgres | Supabase as Postgres backend |
| Frontend | React + TypeScript | Upload, review queue, KB health |

---

## 4. Dependencies

```bash
uv add fastapi "uvicorn[standard]" anthropic voyageai \
       langchain langgraph "langchain-anthropic" "langchain-community" \
       langgraph-checkpoint-postgres "psycopg[binary]" \
       supabase pydantic "pydantic-settings" python-dotenv \
       pymupdf pdfplumber python-docx openpyxl \
       jinja2 python-multipart aiofiles
```

**Note:** `weasyprint` removed — python-docx handles DOCX output without system-level dependencies that break on Windows. PDF export can be added post-hackathon.

---

## 5. Environment Variables

```bash
# .env.example
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=pa-...                      # voyageai.com — separate from Anthropic

SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...           # Admin ingest only
SUPABASE_DB_URL=postgresql://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres

APP_ENV=development
RETRIEVAL_TOP_K=3
RETRIEVAL_THRESHOLD=0.72
MAX_HITL_ITERATIONS=3
DEFAULT_OUTPUT_FORMAT=docx
ADMIN_KEY=change-me-before-demo
```

All secrets via `config/settings.py` (Pydantic BaseSettings) — never hardcoded, never logged.

---

## 6. Supabase Schema

```sql
-- ── KB TABLES ──────────────────────────────────────────────────────

CREATE TABLE kb_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        TEXT NOT NULL,
    doc_type        TEXT NOT NULL CHECK (doc_type IN (
                        'past_tender','cv','methodology','company_profile')),
    source_name     TEXT,
    is_active       BOOLEAN DEFAULT true,          -- soft delete
    file_path       TEXT,                          -- Supabase Storage
    raw_text        TEXT,                          -- stored for guard provenance check
    status          TEXT DEFAULT 'pending' CHECK (status IN (
                        'pending','guard_pass','guard_flagged','committed')),
    uploaded_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE kb_chunks (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id           UUID REFERENCES kb_documents(id),
    chunk_text            TEXT NOT NULL,
    embedding             VECTOR(512),             -- voyage-3-lite
    page_num              INTEGER,
    chunk_index           INTEGER,
    -- denormalized enrichment fields for fast metadata filtering
    doc_type              TEXT,
    tender_type_tags      TEXT[],
    sector_tags           TEXT[],
    authority_type        TEXT,
    regulatory_frameworks TEXT[],
    doc_types_needed      TEXT[],
    novelty_score         FLOAT,
    enriched_at           TIMESTAMPTZ DEFAULT now()
);

-- Full enrichment JSON per document
CREATE TABLE kb_enrichments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES kb_documents(id),
    schema_json JSONB NOT NULL,
    model_used  TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Ground truth fact registry (cross-doc consistency)
CREATE TABLE kb_facts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_type    TEXT NOT NULL,   -- 'person_day_rate','project_value','performance_metric'
    entity_ref   TEXT NOT NULL,   -- 'Dr. Anna Becker', 'EBA/2024/OP/0003'
    field_name   TEXT NOT NULL,
    value        TEXT NOT NULL,
    source_doc   UUID REFERENCES kb_documents(id),
    committed_at TIMESTAMPTZ DEFAULT now()
);

-- Canonical vocabulary (vocabulary drift prevention)
CREATE TABLE kb_vocabulary (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_name      TEXT NOT NULL,
    canonical_value TEXT NOT NULL,
    aliases         TEXT[],
    added_by        TEXT DEFAULT 'system',
    added_at        TIMESTAMPTZ DEFAULT now(),
    UNIQUE(field_name, canonical_value)
);

-- Guard pending review queue
CREATE TABLE kb_pending_reviews (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES kb_documents(id),
    flags       JSONB NOT NULL,   -- [{layer, severity, message, field}]
    created_at  TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT
);

-- ── TENDER JOB TABLES ───────────────────────────────────────────────

CREATE TABLE tender_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_filename TEXT,
    status          TEXT DEFAULT 'pending' CHECK (status IN (
                        'pending','analysing','retrieving','drafting',
                        'awaiting_review','finalising','done','error')),
    sections_json   JSONB,                         -- draft sections for frontend polling
    score_json      JSONB,                         -- readiness scores + justifications
    output_path     TEXT,
    hitl_iteration  INTEGER DEFAULT 0,
    error_msg       TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ── INDEXES ─────────────────────────────────────────────────────────

CREATE INDEX ON kb_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON kb_chunks (doc_type);
CREATE INDEX ON kb_chunks (document_id);
CREATE INDEX ON kb_facts (entity_ref, fact_type, field_name);
CREATE INDEX ON kb_vocabulary (field_name);

-- ── pgvector RPC (match_kb_chunks) ──────────────────────────────────

CREATE OR REPLACE FUNCTION match_kb_chunks(
    query_embedding VECTOR(512),
    filter_doc_types TEXT[],
    filter_sector_tags TEXT[],
    match_threshold FLOAT,
    match_count INT
)
RETURNS TABLE (
    id UUID, document_id UUID, chunk_text TEXT,
    doc_type TEXT, sector_tags TEXT[], regulatory_frameworks TEXT[],
    similarity FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT id, document_id, chunk_text, doc_type, sector_tags, regulatory_frameworks,
           1 - (embedding <=> query_embedding) AS similarity
    FROM kb_chunks
    WHERE doc_type = ANY(filter_doc_types)
      AND (filter_sector_tags = '{}' OR sector_tags && filter_sector_tags)
      AND 1 - (embedding <=> query_embedding) > match_threshold
      AND document_id IN (SELECT id FROM kb_documents WHERE is_active = true)
    ORDER BY similarity DESC
    LIMIT match_count;
$$;
```

### Supabase Checkpointing

LangGraph checkpoints go to Supabase via `langgraph-checkpoint-postgres`. The `setup()` call creates the required checkpoint tables automatically.

```python
# agents/graph.py
from langgraph.checkpoint.postgres import PostgresSaver
from config.settings import settings

checkpointer = PostgresSaver.from_conn_string(settings.supabase_db_url)
checkpointer.setup()   # idempotent — safe to call on every startup
```

`tender_id` is used as the LangGraph `thread_id` — every resume picks up from the exact interrupt point.

---

## 7. LangGraph Agent Graph

```
START
  │
  ▼
[analyse_tender]
  │  Haiku: parse RFP → extract sections + requirements
  │  + build compliance checklist
  │  + set dimension weights W1–W5 from tender emphasis
  │  + identify doc_types_needed per section
  │
  ▼
[retrieve_context]
  │  Per section: metadata-filtered pgvector search → top 3 enriched chunks
  │  + compute Primary Score (Modules 1–5, mostly SQL/embedding — no LLM)
  │  + Haiku: methodology fit (Module 3, ~400 tokens)
  │  + set context_sufficient = False if all scores < RETRIEVAL_THRESHOLD
  │
  ▼
[draft_sections]
  │  Sonnet: draft each section (400–600 words, structured output)
  │  If context_sufficient → full draft
  │  If NOT → "[INSUFFICIENT CONTEXT: {gap description}]" placeholder
  │  + Haiku: compliance coverage score (Module 6, ~900 tokens)
  │  + Haiku: robustness index (Module 7, ~700 tokens)
  │  + assemble Final Score + justifications
  │  status = "awaiting_review"
  │
  ▼
[human_review]   ← INTERRUPT  (interrupt_before=["human_review"])
  │  Graph pauses. API returns draft + score to frontend.
  │  User edits sections + writes feedback → POST /tender/{id}/submit
  │  graph.update_state() injects edits → graph.invoke(None, config) resumes
  │
  ▼
[finalise]
  │  Sonnet: apply finishing touches per edited section
  │  (tone consistency, grammar, apply user feedback)
  │  output_tool renders DOCX → uploads to Supabase Storage
  │  status = "done"
  │
  ▼
  END
  (if request_another_round=true and hitl_iteration < MAX_HITL_ITERATIONS
   → loop back to human_review)
```

### TenderState

```python
# agents/state.py
from typing import TypedDict, Optional

class SectionDraft(TypedDict):
    section_id: str
    section_name: str
    requirements: list[str]
    doc_types_needed: list[str]
    draft_text: str
    confidence: str          # "HIGH" | "MEDIUM" | "LOW"
    gap_flag: Optional[str]
    user_edits: Optional[str]
    sources_used: list[str]

class TenderState(TypedDict):
    # Input
    tender_id: str
    tender_text: str
    output_format: str       # "docx"

    # Tender Analysis
    sections: list[SectionDraft]
    compliance_checklist: list[dict]
    dimension_weights: dict[str, float]

    # Retrieval
    retrieved_chunks: dict[str, list[dict]]   # section_id → chunks

    # Scoring
    primary_scores: dict[str, float]          # module_name → score
    primary_score_total: float
    compliance_score: float
    robustness_score: float
    quality_score_total: float
    final_score: float
    score_justifications: dict[str, str]

    # HITL
    user_feedback: str
    request_another_round: bool
    hitl_iteration: int

    # Output
    output_path: Optional[str]
    status: str
```

---

## 8. Enrichment Pipeline (ingest_tool.py)

Runs at ingestion time, one-time, pre-demo. Invisible at runtime.

### Model Routing

| doc_type | Model | Rationale |
|---|---|---|
| `past_tender` | claude-opus-4-6 | Strategic nuance, positioning patterns |
| `cv` | claude-sonnet-4-6 | Structured, predictable |
| `methodology` | claude-sonnet-4-6 | Technical but well-structured |
| `company_profile` | claude-haiku-4-5-20251001 | Fact sheet — names, numbers, dates |

All use **structured output (tool use)** — Claude fills JSON schema directly, no narrative. ~35% output token reduction.

### Enrichment Schemas (key fields per doc_type)

**past_tender (Opus):** `tender_reference`, `authority_type`, `regulatory_frameworks_invoked`, `contract_value_eur`, `contract_duration_months`, `section_structure`, `lead_section_type`, `lead_section_rationale`, `our_positioning`, `value_proposition_one_line`, `differentiation_claim`, `tone`, `key_phrases_used`, `methodology_key_claims`, `data_sources_used`, `technical_innovation_for_this_tender`, `graceful_limitation_stated`, `credentials_highlighted`, `similarity_angle`, `scale_proof_point`, `quality_commitments_quantified`, `team_allocation`, `lead_selection_rationale`, `price_total_eur`, `price_breakdown`, `day_rate_range_eur`, `deliverables`, `win_signals`, `inferred_win_reason`, `tender_type_tags`, `sector_tags`, `applicable_for_new_tenders_with`

**cv (Sonnet):** `name`, `title`, `seniority_level`, `years_experience`, `day_rate_eur`, `primary_expertise`, `eu_clients_direct`, `regulatory_frameworks_known`, `technical_skills`, `academic_credentials`, `key_projects`, `typical_role_new_client_tender`, `typical_role_regulatory_tender`, `never_assigned_role`, `strongest_credential_one_liner`, `languages`, `tender_type_tags`, `sector_tags`

**methodology (Sonnet):** `methodology_name`, `problem_solved`, `pipeline_stages`, `evidence_types_accepted`, `source_tiers`, `performance_commitments`, `tech_stack`, `update_capability`, `key_differentiating_phrases`, `key_claims_for_proposals`, `regulatory_alignment_capability`, `best_fit_tender_types`, `sector_tags`

**company_profile (Haiku):** `company_name`, `legal_form`, `vat_number`, `eu_pic`, `iso_certification`, `annual_turnover_eur`, `team_size_fte`, `selected_references`, `client_types`, `primary_contact`

### Integrity Guard (3 layers for hackathon)

Runs inside `ingest_tool.py` after enrichment. Severity: `BLOCK` → cannot commit. `WARN` → commits after human approval via React review queue.

**Layer 1 — Structural (Haiku, ~500 tokens):** Required fields present, correct types, dates sane. BLOCK on failure.

**Layer 2 — Claim Provenance (Sonnet, ~700 tokens):** Every factual claim (numbers, currency, project refs, percentages) traceable to source text. Pre-filter with regex first — Sonnet only sees unverified claims. BLOCK on any unverified factual claim.

**Layer 3 — Cross-Doc Consistency (SQL-first, Sonnet only on conflict):** Query `kb_facts` for same entity + field. Zero LLM cost for clean ingestions. BLOCK on financial figure conflicts, WARN on soft fields.

**Vocabulary normalization** runs before Layer 1 — pure embedding similarity against `kb_vocabulary`, no LLM. Maps `"FinTech"` → `"fintech"`, `"digital finance"` → `"fintech"`. Flags genuinely new values as WARN for human approval.

---

## 9. Scoring System

Scoring is split across two graph nodes — no new infrastructure required.

### Primary Modules (inside `retrieve_context` node)

Computed from Supabase metadata — mostly SQL and embedding math, minimal LLM cost.

| # | Module | Method | Max |
|---|---|---|---|
| 1 | Track Record | SQL: sector match + authority type + scale proximity to tender budget | 100 |
| 2 | Expertise Depth | Embedding: % of tender's regulatory frameworks + domains covered in KB | 100 |
| 3 | Methodology Fit | Haiku (~400 tokens): direct / adapted / stretch fit assessment | 100 |
| 4 | Delivery Credibility | SQL: past project timeline range + monitoring capability + team capacity | 100 |
| 5 | Pricing Competitiveness | SQL: estimated bid vs tender budget ratio | 100 |

```
Primary Score = Σ(module_score_i × weight_i) / Σ(weight_i)
```
Weights W1–W5 set dynamically by `analyse_tender` node based on tender emphasis.

### Quality Modules (inside `draft_sections` node, post-generation)

| # | Module | Method | Tokens |
|---|---|---|---|
| 6 | Compliance Coverage | Haiku: draft vs compliance checklist; mandatory reqs weighted 70% | ~900 |
| 7 | Robustness Index | Haiku: count quantified claims, named refs, unsupported assertions | ~700 |

```
Quality Score  = Compliance × 0.55 + Robustness × 0.45
Final Score    = Primary × 0.60 + Quality × 0.40

Bands: 90–100 EXCELLENT | 75–89 STRONG | 60–74 MODERATE | <60 WEAK
```

### Score Output in DOCX

Each generated document opens with a **Readiness Assessment** table (scores + justifications) followed by an **Action Items** checklist. Each section header includes confidence level and any gap flags inline.

---

## 10. API Endpoints

| Route | Purpose |
|---|---|
| `POST /ingest/document` | Upload file (multipart), starts background ingest task |
| `GET /ingest/status/{task_id}` | Poll ingest progress |
| `POST /ingest/bulk` | Seed KB from `kb/` directory (admin, requires ADMIN_KEY) |
| `POST /tender/start` | Upload tender PDF, start new job, returns `tender_id` |
| `GET /tender/{id}/status` | Poll status + sections JSON |
| `GET /tender/{id}/review` | Fetch draft sections for HITL editor |
| `POST /tender/{id}/submit` | Submit user edits + feedback, resumes graph |
| `GET /tender/{id}/download` | Stream final DOCX |
| `GET /kb/documents` | List active KB documents |
| `DELETE /kb/{doc_id}` | Soft-delete a document |

---

## 11. HITL Flow Detail

1. Frontend polls `GET /tender/{id}/status` → sees `awaiting_review`
2. Fetches `GET /tender/{id}/review` → gets `sections_json` with `draft_text` pre-filled in editor
3. User edits inline + writes overall feedback → clicks Submit
4. `POST /tender/{id}/submit` body: `{ sections: [{section_id, user_edits}], feedback, request_another_round }`
5. API calls `graph.update_state()` to inject edits into `TenderState`, then `graph.invoke(None, config)` to resume from interrupt
6. `finalise` node: Sonnet applies finishing touches per section using `user_edits` + `feedback`
7. `output_tool` renders DOCX → uploads to Supabase Storage → status becomes `done`
8. Client downloads via `GET /tender/{id}/download`

Loop: if `request_another_round=true` and `hitl_iteration < MAX_HITL_ITERATIONS(3)` → graph routes back to `human_review` interrupt.

---

## 12. Token Budget

### Ingestion (15-doc KB, one-time)

| Stage | Model | Tokens |
|---|---|---|
| Opus enrichment (3 past tenders) | Opus | ~15,000 |
| Sonnet enrichment (4 CVs + 2 methodology) | Sonnet | ~22,000 |
| Haiku enrichment (3 company docs) | Haiku | ~3,000 |
| Guard L1 structural (×15) | Haiku | ~7,500 |
| Guard L2 provenance (×15, pre-filtered) | Sonnet | ~10,500 |
| Guard L3 cross-doc (conflicts only, ~2 est.) | Sonnet | ~2,000 |
| Vocabulary normalization | None | 0 |
| **Total ingestion** | | **~60,000** |

### Runtime (per tender run)

| Stage | Model | Tokens |
|---|---|---|
| Tender analysis: sections + checklist + weights | Haiku | ~1,600 |
| Module 3: methodology fit | Haiku | ~400 |
| Draft generation (8 sections × ~2,100) | Sonnet | ~16,800 |
| Module 6: compliance check | Haiku | ~900 |
| Module 7: robustness index | Haiku | ~700 |
| Finalise (8 sections × ~800, edited only) | Sonnet | ~6,400 |
| **Total per run** | | **~26,800** |

Sections approved by human are skipped on finalise — real cost lower. Tender analysis result is cached in `tender_jobs` after first run.

---

## 13. Build Order (Hackathon-Optimised)

1. `config/settings.py` + `core/supabase_client.py` + Supabase migrations → verify DB connection and pgvector extension
2. `core/document_parser.py` + `core/chunker.py` + `enrichment/model_router.py` + `enrichment/schemas.py` → test enrich one CV
3. `enrichment/guard.py` + `tools/ingest_tool.py` → test full ingest pipeline on one past tender
4. `core/embeddings.py` + `tools/retrieval_tool.py` + `match_kb_chunks` RPC → test semantic query returns relevant chunks
5. `POST /ingest/bulk` → seed full KB from `kb/` directory; verify all 15 docs committed
6. `agents/state.py` + `agents/graph.py` + all 5 node files → test graph runs to interrupt point with sample tender
7. `api/` routes + `tools/output_tool.py` → test full end-to-end: ingest → start → poll → review → submit → download
8. React frontend: upload views + review editor + score display

---

## 14. Open Questions

1. **Pricing section:** No reference projects at €3.2M+ scale in current KB. Add larger reference or acknowledge scale gap explicitly in draft.
2. **AI Act expertise:** Sofia Chen's AI Act policy brief is mentioned in her CV but not in KB. Add before demo for better score on EC-CNECT tender.
3. **Julia Schneider:** Referenced in past tender team allocations but no CV in KB. Exclude from team assembly logic or add CV.
4. **Voyage API key:** Separate account needed at voyageai.com. Confirm team has access before build starts.
5. **Supabase DB URL:** Direct connection URL (pooled) needed for LangGraph checkpointing — get from Supabase Dashboard → Settings → Database → Connection string (Transaction mode).
6. **credentials_projects.xlsx:** Project values may differ from figures in tender PDFs. Guard Layer 3 will surface this on ingest — resolve before demo.
