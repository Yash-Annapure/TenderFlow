# TenderFlow — System Design Document
**Date:** 2026-04-08  
**Challenge:** ISTARI @ Q-Hack 2026  
**Company:** Meridian Intelligence GmbH  
**Status:** Approved — ready for implementation planning

---

## 1. Problem Statement

Meridian Intelligence GmbH responds to EU institutional tenders (European Commission DGs, regulatory agencies: ENISA, EBA, JRC) that require assembling the same core content — CVs, methodology descriptions, past project references, pricing structures — in different combinations and framings for each submission.

The current process is manual: researchers locate relevant past applications, extract applicable sections, rewrite for the new tender's context, and assemble a draft. This takes days per tender. The content exists; the intelligence to reassemble it correctly does not.

**TenderFlow** automates this: ingest a new tender document, retrieve the most relevant institutional knowledge from a curated knowledge base, and generate a structured, editable first draft — complete with confidence signals, gap flags, and a readiness score — ready for human refinement.

**Winning criterion:** Not a perfect submission-ready document. A strong draft that correctly surfaces the right content, correctly identifies what is missing, and cuts drafting time dramatically. The human stays in the loop; the agent does the heavy lifting.

---

## 2. Architecture Overview

TenderFlow is a **section-aware agentic RAG pipeline** with three distinct phases: ingestion, runtime draft generation, and output.

```
═══════════════════════════════════════════════════════════════════
PHASE 1 — INGESTION (one-time, pre-demo)
═══════════════════════════════════════════════════════════════════

PDF / DOCX / MD / TXT Upload
          │
          ▼
    Document Parser
    (PyMuPDF + pdfplumber)
          │ raw text + tables
          ▼
    Paragraph-boundary Chunker
    (~600 tokens, preserves semantic units)
          │ raw chunks
          ▼
    ┌─────────────────────────────────────────┐
    │  Opus / Sonnet / Haiku Enrichment       │  ← model routed by doc type
    │  (structured metadata per schema)       │
    └─────────────────────────────────────────┘
          │ enriched chunks + metadata
          ▼
    ┌─────────────────────────────────────────┐
    │  INTEGRITY GUARD (5 layers)             │
    │  Haiku (structural) + Sonnet (semantic) │
    └──────────────┬──────────────────────────┘
                   │
       ┌───────────┴───────────┐
     PASS                 FLAGGED
       │                       │
       ▼                       ▼
  voyage-3-lite embed    pending_docs (Supabase)
       │                 → React review queue
       ▼
  Supabase pgvector + metadata columns
  Fact Registry + Canonical Vocabulary

═══════════════════════════════════════════════════════════════════
PHASE 2 — RUNTIME (demo)
═══════════════════════════════════════════════════════════════════

Tender PDF Upload
          │
          ▼
    Parser (PyMuPDF)
          │ raw tender text
          ▼
    ┌─────────────────────────────────────────┐
    │  Haiku: Tender Analyzer                 │
    │  - section extraction + requirements    │
    │  - compliance checklist                 │
    │  - dimension weights (W1–W5)            │
    │  - doc_types_needed per section         │
    └─────────────────────────────────────────┘
          │ structured tender profile (cached)
          ▼
    ┌─────────────────────────────────────────┐
    │  Primary Scoring Modules 1,2,4,5        │
    │  (SQL + embedding math — no LLM)        │
    │  Module 3: Haiku methodology fit        │
    └─────────────────────────────────────────┘
          │ primary scores + weights
          ▼
    ┌─────────────────────────────────────────┐
    │  Section-Aware Retriever                │
    │  For each tender section:               │
    │  → filter by doc_type + metadata        │
    │  → pgvector semantic search             │
    │  → top 3 enriched chunks returned       │
    └─────────────────────────────────────────┘
          │ per-section context packages
          ▼
    ┌─────────────────────────────────────────┐
    │  Sonnet: Section Draft Writer           │
    │  Input: section requirements            │
    │         + top 3 enriched chunks         │
    │         + score context                 │
    │  Output: 400–600 word section draft     │
    │          + confidence flag              │
    │          + gap flag (if applicable)     │
    └─────────────────────────────────────────┘
          │ per-section drafts
          ▼
    ┌─────────────────────────────────────────┐
    │  Haiku: Quality Scoring                 │
    │  - Compliance Coverage (Module 6)       │
    │  - Robustness Index (Module 7)          │
    └─────────────────────────────────────────┘
          │ quality scores + justifications
          ▼
    Draft Assembler
    (deterministic, no LLM)

═══════════════════════════════════════════════════════════════════
PHASE 3 — OUTPUT
═══════════════════════════════════════════════════════════════════

    Markdown Draft File
    drafts/YYYY-MM-DD_[tender-ref]_draft_v1.md
    │
    ├── Readiness Score Summary + Justifications
    ├── Action Item Checklist
    └── Sections (each with confidence + gap flags)
          │
          ▼
    Human edits in any markdown editor
          │
          ▼
    drafts/YYYY-MM-DD_[tender-ref]_draft_v2.md
    (git-versioned)
```

---

## 3. Technology Stack

| Layer | Technology | Reason |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Team strength; async support |
| Frontend | React + TypeScript | Simple upload UI, review queue, KB health dashboard |
| PDF parsing | PyMuPDF (text) + pdfplumber (tables) | Best coverage across PDF types |
| DOCX / MD | python-docx, native text | Meridian's KB includes both |
| Chunking | LangChain RecursiveCharacterTextSplitter | Paragraph-boundary aware |
| Embeddings | voyage-3-lite (Anthropic recommended) | Fast, cheap, semantically dense |
| Vector store | Supabase pgvector | Single DB for vectors + relational + storage |
| File storage | Supabase Storage | Raw PDFs accessible for provenance |
| LLMs | claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5-20251001 (model-routed) | Full Anthropic stack |
| Output | Markdown (.md) | Human-editable, git-versionable, convertible to DOCX/PDF |

---

## 4. Knowledge Base Structure

### 4.1 Document Types

| doc_type | Files | Description |
|---|---|---|
| `past_tender` | tender_response_EBA_2024_*.pdf, ENISA_2023_*.pdf, JRC_2024_*.pdf | Historical winning proposals — primary nuance source |
| `cv` | cv_anna_becker.md, cv_marcus_weber.md, cv_sofia_chen.md, cv_thomas_vogel.md | Team profiles |
| `methodology` | webmap_methodology.docx, data_quality_procedures.txt | Core technical methodology |
| `company_profile` | company_profile.docx, capabilities_overview.pdf, credentials_projects.xlsx | Firm credentials, references, financials |
| `tender` | sample_tender1_for_building.pdf | Input tender documents (not KB — runtime input) |

### 4.2 Supabase Schema

```sql
-- Raw document registry
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    TEXT NOT NULL,
    doc_type    TEXT NOT NULL CHECK (doc_type IN (
                    'past_tender','cv','methodology','company_profile')),
    uploaded_at TIMESTAMPTZ DEFAULT now(),
    file_path   TEXT,           -- Supabase Storage path
    raw_text    TEXT,           -- stored for provenance checks
    status      TEXT DEFAULT 'pending' CHECK (status IN (
                    'pending','guard_pass','guard_flagged','committed'))
);

-- Enriched chunks with embeddings
CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID REFERENCES documents(id),
    chunk_text      TEXT NOT NULL,
    embedding       VECTOR(512),        -- voyage-3-lite dimension
    page_num        INTEGER,
    chunk_index     INTEGER,
    -- Denormalized enrichment fields for fast filtering
    doc_type        TEXT,
    tender_type_tags TEXT[],
    sector_tags      TEXT[],
    authority_type   TEXT,
    regulatory_frameworks TEXT[],
    doc_types_needed TEXT[],            -- for methodology/cv: what tender types need this
    novelty_score   FLOAT,
    enriched_at     TIMESTAMPTZ DEFAULT now()
);

-- Full enrichment JSON per document
CREATE TABLE enrichments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id),
    schema      JSONB NOT NULL,         -- full enrichment per doc type
    model_used  TEXT,                   -- opus/sonnet/haiku
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Ground truth fact registry (for cross-doc consistency)
CREATE TABLE kb_facts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_type   TEXT NOT NULL,          -- 'person_day_rate','project_value',
                                        --   'performance_metric','team_size'
    entity_ref  TEXT NOT NULL,          -- 'Dr. Anna Becker','EBA/2024/OP/0003'
    field_name  TEXT NOT NULL,
    value       TEXT NOT NULL,
    source_doc  UUID REFERENCES documents(id),
    committed_at TIMESTAMPTZ DEFAULT now()
);

-- Canonical vocabulary (drift prevention)
CREATE TABLE canonical_vocabulary (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_name      TEXT NOT NULL,
    canonical_value TEXT NOT NULL,
    aliases         TEXT[],
    added_by        TEXT DEFAULT 'system',
    added_at        TIMESTAMPTZ DEFAULT now(),
    UNIQUE(field_name, canonical_value)
);

-- Guard pending review queue
CREATE TABLE pending_reviews (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id),
    flags       JSONB NOT NULL,         -- [{layer, severity, message, field}]
    created_at  TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT
);

-- KB health log
CREATE TABLE kb_health_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report      JSONB NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT now()
);

-- Tender analysis cache
CREATE TABLE tender_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_hash     TEXT UNIQUE NOT NULL,
    analysis        JSONB NOT NULL,     -- sections, checklist, weights
    cached_at       TIMESTAMPTZ DEFAULT now()
);

-- Draft section cache
CREATE TABLE draft_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_id       UUID REFERENCES tender_cache(id),
    section_id      TEXT NOT NULL,
    section_hash    TEXT NOT NULL,
    draft_text      TEXT NOT NULL,
    confidence      TEXT CHECK (confidence IN ('HIGH','MEDIUM','LOW')),
    gap_flag        TEXT,
    approved_by_human BOOLEAN DEFAULT false,
    generated_at    TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON chunks (doc_type);
CREATE INDEX ON chunks (document_id);
CREATE INDEX ON kb_facts (entity_ref, fact_type, field_name);
CREATE INDEX ON canonical_vocabulary (field_name);
```

---

## 5. Enrichment Schemas

### 5.1 Model Routing

| doc_type | Model | Rationale |
|---|---|---|
| `past_tender` | **Opus** | Strategic nuance, positioning patterns, cross-section reasoning |
| `cv` | **Sonnet** | Structured, predictable — no deep nuance required |
| `methodology` | **Sonnet** | Technical but well-structured internal docs |
| `company_profile` | **Haiku** | Fact sheets: names, numbers, dates, references |

All models use **structured output (tool use)** — JSON schema enforced, no narrative output. Reduces output tokens by ~35%.

### 5.2 Past Tender Enrichment Schema (Opus)

```json
{
  "tender_reference": "EBA/2024/OP/0003",
  "contracting_authority": "European Banking Authority (EBA)",
  "authority_type": "EU_regulatory_agency",
  "tender_sector": "fintech / digital finance / regulatory compliance",
  "regulatory_frameworks_invoked": ["DORA", "Article 29 DORA", "CTPP designation"],
  "contract_value_eur": 290062,
  "contract_duration_months": 10,
  "submission_year": 2024,
  "relationship_type": "new_client",

  "core_problem_stated": "ICT providers to financial entities are not a self-identifying population",
  "problem_type": "population_identification_gap",
  "unique_challenge_for_this_tender": "concentration risk analysis + CTPP likelihood scoring",

  "section_structure": ["exec_summary","problem_framing","entity_typology","methodology","deliverables","team","price"],
  "lead_section_type": "regulatory_typology",
  "lead_section_rationale": "EBA as regulator cares about definitional precision before methodology",
  "section_emphasis_signal": "typology_before_method",

  "our_positioning": "evidence-based entity identification + DORA-aligned typology + concentration analysis",
  "value_proposition_one_line": "empirically grounded ICT supply chain picture for supervisory use",
  "differentiation_claim": "identifies relevance through observable evidence not self-classification",
  "lead_with": "methodology_credibility",
  "tone": "technical-regulatory, evidence-led, deferential to client regulatory authority",
  "key_phrases_used": ["evidence-based","empirically grounded","population problem","hard evidence","observable evidence"],

  "methodology_name": "WebMap + evidence classification",
  "methodology_key_claims": ["false-positive rate <3%","target precision ≥97%","5% random manual audit"],
  "data_sources_used": ["company registries NACE J58–J63","Meridian web index","procurement records","job postings"],
  "technical_innovation_for_this_tender": "CTPP likelihood score (0–100) — advisory ranking for supervisory prioritisation",
  "graceful_limitation_stated": "CTPP score is advisory — formal designation is EBA/JOC decision",

  "credentials_highlighted": ["ENISA/2023/OP/0008","JRC/2024/OP/0019"],
  "similarity_angle": "same EU regulatory agency client type, web-based methodology proven at comparable scale",
  "scale_proof_point": "14,200+ entities (ENISA), 6,400+ (this proposal)",

  "risk_framing": "addressed non-self-identifying population complexity; DORA alignment of typology",
  "quality_commitments_quantified": ["<3% false-positive rate","≥97% precision"],
  "compliance_mapped_explicitly": true,
  "subcontracting_used": ["legal/regulatory review — €12,000"],

  "project_lead": "Sofia Chen",
  "senior_advisor": "Dr. Anna Becker",
  "team_allocation": {
    "Sofia Chen": {"role": "Project Lead — regulatory scoping + policy outputs", "days": 70},
    "Anna Becker": {"role": "Senior Advisor — methodology + QA", "days": 25},
    "Thomas Vogel": {"role": "Technical Lead — data pipeline", "days": 85},
    "Marcus Weber": {"role": "Data Scientist — classification + scoring model", "days": 75},
    "Julia Schneider": {"role": "Research Analyst — verification + writing", "days": 55}
  },
  "lead_selection_rationale": "regulatory tender → policy lead front-facing, not technical lead",

  "price_total_eur": 290062,
  "price_breakdown": {
    "staff_costs": 228250,
    "infrastructure": 28000,
    "subcontract_legal": 12000,
    "travel": 8000,
    "contingency_pct": 5
  },
  "day_rate_range_eur": {"min": 850, "max": 1450},

  "deliverables": [
    {"code": "D1", "name": "Inception Report", "month": "M1-M2"},
    {"code": "D2", "name": "Entity Dataset 6,400+ records", "month": "M7"},
    {"code": "D3", "name": "Concentration Analysis", "month": "M9"},
    {"code": "D4", "name": "CTPP Shortlist with likelihood scores", "month": "M10"},
    {"code": "D5", "name": "Policy Brief", "month": "M10"}
  ],
  "inception_report_included": true,
  "output_formats": ["JSON","CSV","structured dataset","policy brief"],
  "key_output_metric": "6,400+ verified entities",

  "win_signals": [
    "prior EU regulatory agency track record (ENISA, JRC)",
    "DORA-specific entity typology showed regulatory intent understanding",
    "quantified false-positive commitment — not vague quality claims",
    "CTPP scoring anticipates client next operational need",
    "explicit graceful degradation = regulatory credibility"
  ],
  "inferred_win_reason": "regulatory precision + proven scale + quantified QA over competitors using database filtering",

  "tender_type_tags": ["market_mapping","entity_identification","regulatory_compliance","EU_institutional","data_delivery","concentration_analysis"],
  "sector_tags": ["fintech","ICT","financial_regulation","DORA","systemic_risk"],
  "applicable_for_new_tenders_with": ["DORA references","regulatory registry building","ICT provider mapping","financial sector","concentration risk"]
}
```

### 5.3 CV Enrichment Schema (Sonnet)

```json
{
  "name": "Dr. Anna Becker",
  "title": "Managing Director & Principal Researcher",
  "seniority_level": "director",
  "years_experience": 14,
  "day_rate_eur": 1450,

  "primary_expertise": ["market intelligence","EU institutional consulting","empirical economic research"],
  "sector_expertise": ["EU regulatory agencies","European Commission directorates","public research institutes"],
  "eu_clients_direct": ["DG CNECT","JRC","ENISA","EBA"],
  "regulatory_frameworks_known": ["NIS2","DORA","AI Act","CRA","Data Governance Act","Digital Single Market"],
  "technical_skills": [],

  "academic_credentials": [
    "PhD Economics — Humboldt-Universität zu Berlin (2011)",
    "MSc European Economic Studies — College of Europe, Bruges (2007)"
  ],
  "publications": [
    "Becker & Vogel 2023 — web-derived indicators for SME mapping",
    "Becker 2019 — niche market actors in fragmented EU industries"
  ],

  "typical_role_new_client_tender": "Project Director (45+ days) — leads steering committee, signs all deliverables",
  "typical_role_repeat_client_tender": "Senior Advisor (25 days) — methodology oversight and QA",
  "typical_role_regulatory_tender": "Senior Advisor (25 days) — Sofia Chen as Project Lead",
  "never_assigned_role": "Technical Lead, Data Scientist",

  "key_projects": [
    "ENISA/2023/OP/0008 — Cybersecurity SME Landscape (Project Director, 36 days)",
    "JRC/2024/OP/0019 — Data Economy Monitoring Tool Phase III (Project Director, 45 days)",
    "EBA/2024/OP/0003 — FinTech DORA Analysis (Senior Advisor, 25 days)"
  ],

  "strongest_credential_one_liner": "14 years leading EU institutional market intelligence with direct accounts at DG CNECT, JRC, ENISA, and EBA",
  "positioning_angle_for_proposals": "methodological credibility + senior EU institutional relationships",

  "languages": ["German (native)","English (fluent)","French (professional)"],
  "language_advantage_for": ["pan-EU tenders","Franco-German client contacts","multilingual deliverables"],

  "use_for_tenders_about": ["policy research","EU regulatory agency","market sizing","web-based methodology","any EU institutional"],
  "tender_type_tags": ["market_mapping","regulatory_compliance","EU_institutional","policy_research"],
  "sector_tags": ["cybersecurity","data_economy","fintech","AI_ecosystem","industrial_deep_tech","media"]
}
```

### 5.4 Methodology Enrichment Schema (Sonnet)

```json
{
  "methodology_name": "WebMap",
  "internal_ref": "MIG-QA-001 v3.2",
  "last_updated": "2025-02",

  "problem_solved": "Identifying organisations relevant to a market scope when they do not self-classify in standard registries",
  "failure_mode_of_alternatives": "NACE code filtering and commercial databases miss the long tail — niche SMEs, cross-border actors, non-self-classifying providers",

  "pipeline_stages": [
    {"stage": 1, "name": "Seed universe", "detail": "Tier 1 company registries + Tier 2 web index (~12M European orgs) + Tier 3 sector-specific registries"},
    {"stage": 2, "name": "Web crawl", "detail": "Primary domain; About/Products/Services pages; timestamped archive; Scrapy + Playwright"},
    {"stage": 3, "name": "Evidence classification", "detail": "NLP-based; hard evidence required; reject rate 85–95% of seed universe"},
    {"stage": 4, "name": "Verification & profiling", "detail": "5% manual spot-check; derive structured indicator profiles"},
    {"stage": 5, "name": "Delivery", "detail": "JSON/CSV/Parquet + change log + data dictionary + REST API on request"}
  ],

  "evidence_types_accepted": [
    {"type": "explicit_product_service_description_on_own_website", "weight": "high"},
    {"type": "procurement_record_as_supplier_or_contractor", "weight": "high"},
    {"type": "job_posting_sector_specific_within_18_months", "weight": "medium"},
    {"type": "technical_certification_in_relevant_area", "weight": "medium"},
    {"type": "sector_trade_association_membership", "weight": "low"}
  ],
  "evidence_types_rejected": ["generic keywords: 'digital solutions','innovation','technology' in isolation"],

  "source_tiers": {
    "tier_1_canonical": ["national company registers","EU VAT databases","Eurostat FAME","OpenCorporates API"],
    "tier_2_capability": ["organisational primary web domain — About/Products pages"],
    "tier_3_signal": ["LinkedIn","Crunchbase","news articles","BSI","CREST","Common Criteria","FIRST"]
  },

  "performance_commitments": {
    "false_positive_rate": "<3%",
    "audit_mechanism": "5% random sample manual review",
    "coverage_large_250plus": ">95%",
    "coverage_medium_50_249": ">85%",
    "coverage_small_10_49": ">70%"
  },
  "entity_resolution": {
    "duplicate_rate": "<1.5% (from 12%)",
    "protocol": ["exact VAT/registration match","Jaro-Winkler fuzzy name (threshold 0.92)","primary domain match"]
  },
  "scale_proven": "30M+ organisational web pages indexed; EU-27 coverage",

  "tech_stack": {
    "crawling": ["Scrapy","Playwright","boto3/S3"],
    "nlp": ["spaCy","scikit-learn","sentence-transformers","fine-tuned BERT"],
    "entity_resolution": ["dedupe library","Jaro-Winkler"],
    "orchestration": ["Apache Airflow"],
    "storage": ["PostgreSQL","Elasticsearch","S3"],
    "delivery": ["JSON","CSV","Parquet","REST API"]
  },

  "update_capability": "rolling quarterly cycle; automated re-crawl + change detection + new entrant sweep",
  "api_delivery": true,
  "inception_report_pattern": "all projects include D1 Inception Report (M1-M2) for methodology approval before data collection",

  "key_differentiating_phrases": [
    "evidence-based classification",
    "population problem",
    "long tail of actors",
    "hard evidence required",
    "non-self-identifying population",
    "observable verifiable evidence"
  ],
  "key_claims_for_proposals": [
    "identifies actors invisible to commercial databases",
    "evidence-based not self-reported",
    "proven at EU-27 scale across multiple projects",
    "quarterly update capability",
    "false-positive rate <3% verified by random audit"
  ],
  "regulatory_alignment_capability": ["NIS2","DORA","AI Act","CRA","Data Governance Act","Digital Single Market"],
  "best_fit_tender_types": ["market_mapping","ecosystem_monitoring","entity_identification","landscape_study","registry_building"],
  "sector_tags": ["cybersecurity","data_economy","fintech","AI_ecosystem","industrial_deep_tech","media"]
}
```

### 5.5 Company Profile Enrichment Schema (Haiku)

```json
{
  "company_name": "Meridian Intelligence GmbH",
  "legal_form": "GmbH",
  "registration": "HRB 192847 B, Berlin",
  "vat_number": "DE298473610",
  "eu_pic": "887 432 156",
  "iso_certification": "ISO 9001 — DQS GmbH, valid to Dec 2026",
  "cpv_codes": ["79300000","72316000","73200000"],

  "annual_turnover_eur": {"2022": 3100000, "2023": 3800000, "2024": 4200000},
  "team_size_fte": 35,
  "headquarters": "Berlin, Germany",

  "selected_references": [
    {"ref": "ENISA/2023/OP/0008", "client": "ENISA", "value_eur": 480000, "year": "2023-24", "topic": "EU Cybersecurity SME Mapping"},
    {"ref": "JRC/2024/OP/0019", "client": "JRC", "value_eur": 620000, "year": "2024-26", "topic": "EU Data Economy Monitoring Tool Ph.III"},
    {"ref": "EBA/2024/OP/0003", "client": "EBA", "value_eur": 290000, "year": "2024-25", "topic": "FinTech & DORA ICT Provider Analysis"},
    {"ref": "DG GROW/2022/OP/0011", "client": "DG GROW", "value_eur": 410000, "year": "2022-24", "topic": "EU Industrial Deep Tech Ecosystem"},
    {"ref": "DG CNECT/2023/OP/0021", "client": "DG CNECT", "value_eur": 350000, "year": "2023-24", "topic": "EU Media Market Monitoring"},
    {"ref": "BMWi/2021/FF/0047", "client": "BMWK", "value_eur": 180000, "year": "2021-22", "topic": "German AI Startup Landscape"}
  ],

  "client_types": ["EU_regulatory_agency","European_Commission_DG","national_ministry","research_institute"],
  "total_eu_contract_value_eur": 2330000,
  "primary_contact": "Dr. Anna Becker — a.becker@meridian-intelligence.eu — +49 30 884 2210"
}
```

---

## 6. Ingestion Pipeline

### 6.1 Document Parser

```python
def parse_document(file_path: str, doc_type: str) -> ParsedDocument:
    if file_path.endswith('.pdf'):
        # Layer 1: PyMuPDF for text
        text = extract_with_pymupdf(file_path)
        # Layer 2: pdfplumber for tables
        tables = extract_tables_with_pdfplumber(file_path)
        raw = merge_text_and_tables(text, tables)
    elif file_path.endswith('.docx'):
        raw = extract_with_python_docx(file_path)
    elif file_path.endswith(('.md', '.txt')):
        raw = open(file_path).read()
    elif file_path.endswith('.xlsx'):
        raw = extract_xlsx_as_text(file_path)

    return ParsedDocument(raw_text=raw, doc_type=doc_type)
```

### 6.2 Chunker

Paragraph-boundary chunking — preserves semantic units. A methodology paragraph stays together; a CV bullet-point block stays together. Sub-splits only when a paragraph exceeds 800 tokens.

```python
splitter = RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", ". ", " "],
    chunk_size=600,
    chunk_overlap=60,
    length_function=token_count
)
```

### 6.3 Enrichment (model-routed)

```python
MODEL_ROUTING = {
    "past_tender":     "claude-opus-4-6",
    "cv":              "claude-sonnet-4-6",
    "methodology":     "claude-sonnet-4-6",
    "company_profile": "claude-haiku-4-5-20251001"
}

def enrich_document(doc: ParsedDocument) -> EnrichedDocument:
    model = MODEL_ROUTING[doc.doc_type]
    schema = ENRICHMENT_SCHEMAS[doc.doc_type]

    # Structured output via tool use — no narrative, JSON only
    result = claude_client.messages.create(
        model=model,
        tools=[{"name": "enrich_document", "input_schema": schema}],
        tool_choice={"type": "tool", "name": "enrich_document"},
        messages=[{
            "role": "user",
            "content": f"Extract enrichment from this {doc.doc_type}:\n\n{doc.raw_text}"
        }]
    )
    return result.content[0].input
```

---

## 7. Integrity Guard

### 7.1 Severity Tiering

| Severity | Behaviour | Typical trigger |
|---|---|---|
| `BLOCK` | Cannot commit — human must resolve | Hallucinated fact, cross-doc contradiction on financial figures |
| `WARN` | Commits after human approval | New vocabulary value, soft contradiction |
| `INFO` | Auto-commits, logged silently | KB distribution imbalance, redundancy note |

### 7.2 Layer 1 — Structural Validation (Haiku)

Checks all required schema fields are present, correctly typed, and temporally sane. Severity: `BLOCK` on any failure. ~500 tokens.

### 7.3 Layer 2 — Vocabulary Normalization (No LLM)

```python
def normalize_value(value: str, field: str) -> NormalizationResult:
    # Step 1: exact match
    if canonical := db.exact_match(value, field):
        return Normalized(canonical)

    # Step 2: embedding similarity against canonical values
    scores = cosine_similarity(embed(value), embed_all(field))
    if max(scores) > 0.88:
        return Normalized(canonical_values[argmax(scores)])

    # Step 3: flag as new — no LLM call
    return Flag(WARN, f"New vocabulary: '{value}' in field '{field}'")
```

Zero LLM calls for known vocabulary. Only flags genuinely novel values.

### 7.4 Layer 3 — Claim Provenance (Sonnet)

**Most critical layer.** Verifies every factual claim in enrichment is present in the source document. Catches Opus hallucinations before they enter the KB.

```python
def check_provenance(enriched: dict, raw_text: str) -> ProvenanceResult:
    # Step 1: extract verifiable claims with regex — no LLM
    claims = extract_numeric_claims(enriched)   # currency, %, counts, dates, refs

    # Step 2: attempt string match against raw text
    unverified = [c for c in claims if not fuzzy_match(c.value, raw_text)]

    if not unverified:
        return Pass()

    # Step 3: only send unverified claims to Sonnet — not full documents
    return sonnet_verify(unverified, relevant_spans(unverified, raw_text))
    # ~700 tokens, targeted
```

Severity: `BLOCK` on any unverified factual claim.

### 7.5 Layer 4 — Cross-Document Consistency (SQL-first, Sonnet on conflict)

```python
def check_cross_doc(new_facts: list[Fact]) -> ConsistencyResult:
    # SQL query — no LLM for clean ingestions
    conflicts = db.query("""
        SELECT * FROM kb_facts
        WHERE entity_ref = ANY($1) AND field_name = ANY($2) AND value != $3
    """, [f.entity_ref for f in new_facts], ...)

    if not conflicts:
        return Pass()  # Zero LLM tokens — most documents

    # Only call Sonnet when a real conflict exists
    return sonnet_resolve(conflicts, new_facts)  # ~1,000 tokens
```

Financial figures and performance metrics: `BLOCK`. Soft fields (role descriptions): `WARN`.

### 7.6 Layer 5 — Semantic Health (SQL + on-demand Haiku)

```sql
-- Distribution check — pure SQL, no LLM
SELECT field_value, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM kb_metadata WHERE field_name = 'authority_type'
GROUP BY field_value;
```

Haiku generates a natural-language health summary (~300 tokens) only when the dashboard is opened or a threshold is crossed. Never per-ingestion.

### 7.7 Canonical Vocabulary Seed

Pre-populated at system init. Grows via human-approved WARN flags.

```python
CANONICAL_VOCABULARY = {
    "authority_type": ["EU_regulatory_agency","European_Commission_DG","national_ministry","research_institute","private_sector"],
    "tender_type_tags": ["market_mapping","entity_identification","regulatory_compliance","EU_institutional","data_delivery","ecosystem_monitoring","landscape_study","registry_building","concentration_analysis","policy_research"],
    "sector_tags": ["cybersecurity","data_economy","fintech","AI_ecosystem","industrial_deep_tech","media","healthcare","employment"],
    "regulatory_frameworks": ["DORA","NIS2","AI Act","CRA","Data Governance Act","Digital Single Market","GDPR","ECSMAF"],
    "relationship_type": ["new_client","repeat_client","framework_extension"],
    "lead_section_type": ["regulatory_typology","methodology","problem_framing","credentials","team","pricing"],
    "section_emphasis_signal": ["typology_before_method","method_before_typology","progression_narrative","credentials_first"]
}
```

---

## 8. Runtime Pipeline

### 8.1 Tender Analyzer (Haiku, cached)

On new tender upload, Haiku performs three tasks in one call (~1,600 tokens total, result cached by `hash(tender_text)`):

**Task A — Section extraction:**
```json
{
  "sections": [
    {
      "id": "S01",
      "name": "Understanding of Objectives",
      "requirements": ["explain population identification challenge","reference relevant legislation","demonstrate prior similar scope"],
      "doc_types_needed": ["past_tender","methodology"],
      "sector_focus": ["AI_ecosystem","regulatory_compliance"]
    }
  ]
}
```

**Task B — Compliance checklist:**
```json
{
  "compliance_checklist": [
    {"id": "C01", "requirement": "Methodology goes beyond commercial databases", "mandatory": true, "section": "S02"},
    {"id": "C02", "requirement": "Evidence-based classification described", "mandatory": true, "section": "S02"},
    {"id": "C03", "requirement": "False-positive rejection procedure explained", "mandatory": true, "section": "S02"},
    {"id": "C04", "requirement": "Quarterly update capability demonstrated", "mandatory": false, "section": "S03"},
    {"id": "C05", "requirement": "Capacity building plan included", "mandatory": false, "section": "S06"}
  ]
}
```

**Task C — Dimension weights:**
```json
{
  "dimension_weights": {
    "track_record": 0.20,
    "expertise_depth": 0.25,
    "methodology_fit": 0.25,
    "delivery_credibility": 0.15,
    "pricing_competitiveness": 0.15
  },
  "weight_rationale": "Tender leads with methodology section (3 pages) and emphasises evidence-based classification as mandatory criterion — methodology and expertise weighted highest"
}
```

### 8.2 Section-Aware Retriever

For each tender section, retrieval is metadata-filtered then semantically ranked:

```python
def retrieve_for_section(section: TenderSection) -> list[Chunk]:
    return db.query("""
        SELECT c.*, 1 - (c.embedding <=> $1) AS similarity
        FROM chunks c
        WHERE c.doc_type = ANY($2)           -- metadata filter first
        AND c.sector_tags && $3              -- sector overlap
        ORDER BY similarity DESC
        LIMIT 3
    """,
        embed(section.requirements_text),    # query embedding
        section.doc_types_needed,
        section.sector_focus
    )
```

Top 3 chunks per section. pgvector with metadata pre-filtering is precise enough that rank 4+ is typically noise.

### 8.3 Draft Writer (Sonnet)

One call per section. Receives: section requirements + top 3 enriched chunks + primary score context. Max 600 tokens output.

```python
DRAFT_PROMPT = """
You are drafting one section of a tender response for Meridian Intelligence GmbH.

SECTION: {section_name}
REQUIREMENTS: {section_requirements}

RETRIEVED KNOWLEDGE:
{chunk_1_enriched}
{chunk_2_enriched}
{chunk_3_enriched}

SCORE CONTEXT:
- Track record score: {track_record_score}/100 ({track_record_justification})
- Methodology fit: {methodology_score}/100

INSTRUCTIONS:
- Write 400–600 words maximum
- Use specific project references, numbers, and regulatory citations from the retrieved knowledge
- If a requirement cannot be addressed from the retrieved knowledge, state clearly what is missing rather than inventing content
- Match tone: technical-regulatory, evidence-led, deferential to the contracting authority
- End with a confidence flag: CONFIDENCE: HIGH / MEDIUM / LOW
- If any gap: GAP: [description of missing content]
"""
```

Sections marked as `approved_by_human = true` in `draft_cache` are skipped on regeneration — zero tokens.

---

## 9. Scoring System

### 9.1 Primary Modules (KB Coverage — Computed Pre/During Retrieval)

| Module | Method | Max Score |
|---|---|---|
| Track Record | SQL: sector match + authority match + scale proximity | 100 |
| Expertise Depth | Embedding: regulatory framework coverage + domain overlap | 100 |
| Methodology Fit | Haiku (~400 tokens): direct/adapted/stretch assessment | 100 |
| Delivery Credibility | SQL: timeline range + monitoring capability + capacity | 100 |
| Pricing Competitiveness | SQL: bid estimate vs tender budget ratio | 100 |

**Primary Score:**
```
Primary Score = Σ(module_score_i × weight_i) / Σ(weight_i)
```
Weights W1–W5 set dynamically by Haiku tender analysis (Task C above).

### 9.2 Quality Modules (Draft Evaluation — Post-Generation Haiku)

**Module 6 — Compliance Coverage (~900 tokens):**

Haiku checks the completed draft against the compliance checklist. Mandatory requirements weighted 70%, optional 30%.

```
Compliance Score = (mandatory_addressed / mandatory_total × 70)
                 + (optional_addressed / optional_total × 30)
```

**Module 7 — Robustness Index (~700 tokens):**

Haiku counts and scores evidential strength across the draft:
- Quantified claims (numbers, percentages, entity counts, F1 scores)
- Named project references (specific contract IDs, not "past projects")
- Regulatory framework citations (named regulations, specific articles)
- Single-source claims (flagged as fragile)
- Unsupported assertions (flagged for human addition)

### 9.3 Final Score Formula

```
Quality Score  = Compliance Score × 0.55 + Robustness Index × 0.45
Final Score    = Primary Score × 0.60 + Quality Score × 0.40

Readiness Band:
  90–100: EXCELLENT — submit with minor human review
  75–89:  STRONG    — targeted edits required
  60–74:  MODERATE  — significant gaps to address
  <60:    WEAK      — major KB gaps or tender mismatch
```

---

## 10. Output Format

**File path:** `drafts/YYYY-MM-DD_[tender-ref]_draft_v[n].md`  
**Versioning:** each human edit or regeneration creates a new version. Git tracks diffs.

```markdown
# Tender Response Draft
**Tender:** EC-CNECT/2025/OP/0034 — European AI Ecosystem Mapping
**Contracting Authority:** European Commission, DG CNECT
**Generated:** 2026-04-08 | **TenderFlow v1** | **Draft v1**

---

## Readiness Assessment

| Module | Score | Weight | Contribution |
|--------|-------|--------|-------------|
| Track Record | 75/100 | 20% | 15.0 |
| Expertise Depth | 80/100 | 25% | 20.0 |
| Methodology Fit | 87/100 | 25% | 21.8 |
| Delivery Credibility | 90/100 | 15% | 13.5 |
| Pricing Competitiveness | 65/100 | 15% | 9.8 |
| **Primary Score** | | | **80.1 / 100** |
| Compliance Coverage | 92/100 | 55% | 50.6 |
| Robustness Index | 71/100 | 45% | 31.9 |
| **Quality Score** | | | **82.6 / 100** |
| **FINAL SCORE** | **81.1 / 100 — STRONG** | | |

### Score Justifications
**Track Record (75):** 3 past projects with direct relevance retrieved (ENISA cybersecurity SME
mapping, JRC data economy monitoring, EBA DORA). No prior AI Act-specific work in KB — gap
flagged in Section 3.

**Expertise Depth (80):** Team covers NLP classification, regulatory scoping (NIS2, DORA, DGA),
and EU institutional delivery. AI Act taxonomy expertise not evidenced — Sofia Chen policy brief
on operationalising the AI Act is the closest reference but not in KB.

**Methodology Fit (87):** WebMap applies directly. Adaptation needed for AI Act risk category
classification — no prior NACE-to-AI-Act mapping in methodology docs. Flagged inline in Section 3.

**Pricing (65):** Tender estimated at €3.2M over 36 months. Largest comparable project was €674K
(JRC, 24 months). Scale gap significant — pricing section requires senior review before submission.

**Compliance (92):** 12/13 mandatory requirements addressed. Missing: Section 3.4 Capacity
Building — no methodology training materials or workshop facilitation evidence in KB.

**Robustness (71):** 11 quantified claims in draft. Sections 2 and 5 rely on single-source
evidence. 3 unsupported assertions identified (marked ⚠️ inline). Recommend corroborating
references for Sections 2 and 5.

---

## Action Items Before Submission
- [ ] **HIGH** Pricing: validate budget at €3.2M scale — historical basis insufficient
- [ ] **HIGH** Section 3.4: add capacity building evidence or acknowledge gap explicitly
- [ ] **MEDIUM** Sections 2, 5: corroborate single-source claims with additional references
- [ ] **LOW** Add AI Act taxonomy expertise evidence if available in updated KB

---

## 1. Executive Summary
> **Confidence:** HIGH | **Sources:** EBA-2024, ENISA-2023, company_profile

[Draft content...]

---

## 2. Understanding of Objectives
> **Confidence:** HIGH | **Sources:** JRC-2024, webmap_methodology
> ⚠️ Single-source: population identification framing drawn only from ENISA-2023

[Draft content...]

---

## 3. Proposed Methodology
> **Confidence:** MEDIUM | **Sources:** webmap_methodology, data_quality_procedures
> ⚠️ GAP: No AI Act risk category classification in KB. Recommend: explicitly frame WebMap
> adaptation to AI Act taxonomy — do not leave implied. Add specific AI Act article references.

[Draft content...]
```

---

## 11. Token Budget

### Ingestion (15-document KB, one-time)

| Stage | Model | Tokens | Notes |
|---|---|---|---|
| Opus enrichment (3 past tenders) | Opus | ~15,000 | Structured output, no narrative |
| Sonnet enrichment (4 CVs + 2 methodology) | Sonnet | ~22,000 | |
| Haiku enrichment (3 company docs) | Haiku | ~3,000 | |
| Guard L1 structural (×15) | Haiku | ~7,500 | |
| Guard L2 vocabulary | None | 0 | Embedding-based |
| Guard L3 provenance (×15) | Sonnet | ~10,500 | Pre-filtered claims only |
| Guard L4 cross-doc (conflicts only) | Sonnet | ~2,000 | SQL-first; estimate 2 conflicts |
| Guard L5 health (on-demand) | Haiku | ~300 | Not per-ingestion |
| **Ingestion total** | | **~60,300** | |

### Runtime (per tender run)

| Stage | Model | Tokens | Notes |
|---|---|---|---|
| Tender analysis: sections + checklist + weights | Haiku | ~1,600 | Cached after first run |
| Primary Module 3: methodology fit | Haiku | ~400 | |
| Draft generation (8 sections × ~2,100) | Sonnet | ~16,800 | Cached if section approved |
| Quality Module 6: compliance check | Haiku | ~900 | |
| Quality Module 7: robustness index | Haiku | ~700 | |
| **Runtime total per run** | | **~20,400** | |

---

## 12. Frontend — React UI

Three views, minimal complexity:

**Upload View**
- Drag-and-drop document upload with doc_type selector
- Guard result display: pass / flagged items with severity and resolution options
- KB health panel: distribution bar charts from SQL stats

**Tender View**
- Upload tender PDF
- Progress indicator per pipeline stage
- Score summary card (updates as sections complete)
- Link to generated markdown draft

**Review Queue**
- List of flagged documents pending human resolution
- Per-flag detail: severity, field, expected vs found, source span
- One-click approve / reject / edit before commit

---

## 13. Out of Scope for v1

- Multi-tenant / multi-company support
- User authentication beyond basic session
- Automated submission to EU procurement portals
- Live web scraping of new KB sources
- Multi-language tender support (French, German)
- Real-time collaboration on draft editing

---

## 14. Open Questions for Human Review

1. **Pricing section:** No pricing model for tenders at €3.2M scale. Does Meridian want to add larger reference projects to the KB before demo?
2. **AI Act expertise:** Sofia Chen's policy brief on operationalising the AI Act is referenced in her CV but not in the KB. Should it be added?
3. **Julia Schneider:** Referenced in past tender team allocations but no CV in KB. Add a CV or exclude from team assembly?
4. **Credentials spreadsheet (credentials_projects.xlsx):** Contains project references that may differ from values in tender PDFs — cross-doc consistency check will surface this. Resolve before ingestion.
