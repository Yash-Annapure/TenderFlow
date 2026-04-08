-- TenderFlow — Supabase initial schema
-- Run this once in the Supabase SQL Editor before starting the backend.
-- All tables use UUIDs as primary keys. Soft deletes via is_active flag.

-- ── Extensions ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;


-- ── KB TABLES ─────────────────────────────────────────────────────────────────

-- One row per uploaded document
CREATE TABLE IF NOT EXISTS kb_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        TEXT NOT NULL,
    doc_type        TEXT NOT NULL CHECK (doc_type IN (
                        'past_tender', 'cv', 'methodology', 'company_profile')),
    source_name     TEXT,
    is_active       BOOLEAN DEFAULT true,
    file_path       TEXT,
    raw_text        TEXT,                          -- stored for guard provenance checks
    status          TEXT DEFAULT 'pending' CHECK (status IN (
                        'pending', 'guard_pass', 'guard_flagged', 'committed')),
    chunk_count     INTEGER DEFAULT 0,
    uploaded_by     TEXT DEFAULT 'system',
    uploaded_at     TIMESTAMPTZ DEFAULT now()
);

-- One row per text chunk with 512-dim voyage-3-lite embedding
CREATE TABLE IF NOT EXISTS kb_chunks (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id           UUID REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_text            TEXT NOT NULL,
    embedding             VECTOR(512),
    page_num              INTEGER,
    chunk_index           INTEGER,
    -- Denormalised enrichment fields for fast metadata filtering
    doc_type              TEXT,
    source_name           TEXT,
    tender_type_tags      TEXT[],
    sector_tags           TEXT[],
    authority_type        TEXT,
    regulatory_frameworks TEXT[],
    token_count           INTEGER,
    enriched_at           TIMESTAMPTZ DEFAULT now()
);

-- Full enrichment JSON per document
CREATE TABLE IF NOT EXISTS kb_enrichments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES kb_documents(id) ON DELETE CASCADE,
    schema_json JSONB NOT NULL,
    model_used  TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Ground truth fact registry for cross-doc consistency checks (Guard Layer 3)
CREATE TABLE IF NOT EXISTS kb_facts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_type    TEXT NOT NULL,    -- 'financial' | 'person_day_rate' | 'performance_metric'
    entity_ref   TEXT NOT NULL,    -- e.g. 'EBA/2024/OP/0003', 'Dr. Anna Becker'
    field_name   TEXT NOT NULL,
    value        TEXT NOT NULL,
    source_doc   UUID REFERENCES kb_documents(id),
    committed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(entity_ref, field_name)
);

-- Vocabulary registry for normalisation
CREATE TABLE IF NOT EXISTS kb_vocabulary (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    field_name      TEXT NOT NULL,
    canonical_value TEXT NOT NULL,
    aliases         TEXT[],
    added_by        TEXT DEFAULT 'system',
    added_at        TIMESTAMPTZ DEFAULT now(),
    UNIQUE(field_name, canonical_value)
);

-- Guard pending review queue
CREATE TABLE IF NOT EXISTS kb_pending_reviews (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES kb_documents(id) ON DELETE CASCADE,
    flags       JSONB NOT NULL,    -- [{layer, severity, message, field}]
    created_at  TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT
);


-- ── TENDER JOB TABLES ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tender_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tender_filename TEXT,
    status          TEXT DEFAULT 'pending' CHECK (status IN (
                        'pending', 'analysing', 'retrieving', 'drafting',
                        'awaiting_review', 'finalising', 'done', 'error')),
    output_format   TEXT DEFAULT 'docx',
    sections_json   JSONB,         -- serialised draft sections for frontend polling
    score_json      JSONB,         -- readiness scores + justifications
    output_path     TEXT,
    hitl_iteration  INTEGER DEFAULT 0,
    error_msg       TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);


-- ── INDEXES ───────────────────────────────────────────────────────────────────

-- pgvector IVFFlat index — 100 lists appropriate for < 100k chunks
CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding
    ON kb_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc_type   ON kb_chunks (doc_type);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document_id ON kb_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_kb_facts_entity       ON kb_facts (entity_ref, fact_type, field_name);
CREATE INDEX IF NOT EXISTS idx_kb_vocab_field        ON kb_vocabulary (field_name);
CREATE INDEX IF NOT EXISTS idx_tender_jobs_status    ON tender_jobs (status);


-- ── pgvector RPC ──────────────────────────────────────────────────────────────
-- Called by tools/retrieval_tool.py

CREATE OR REPLACE FUNCTION match_kb_chunks(
    query_embedding     VECTOR(512),
    filter_doc_types    TEXT[],
    filter_sector_tags  TEXT[],
    match_threshold     FLOAT,
    match_count         INT
)
RETURNS TABLE (
    id                    UUID,
    document_id           UUID,
    chunk_text            TEXT,
    doc_type              TEXT,
    source_name           TEXT,
    sector_tags           TEXT[],
    regulatory_frameworks TEXT[],
    similarity            FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT
        kc.id,
        kc.document_id,
        kc.chunk_text,
        kc.doc_type,
        kc.source_name,
        kc.sector_tags,
        kc.regulatory_frameworks,
        1 - (kc.embedding <=> query_embedding) AS similarity
    FROM kb_chunks kc
    JOIN kb_documents kd ON kc.document_id = kd.id
    WHERE
        kd.is_active = true
        AND kc.doc_type = ANY(filter_doc_types)
        AND (
            filter_sector_tags = '{}'
            OR kc.sector_tags && filter_sector_tags
        )
        AND 1 - (kc.embedding <=> query_embedding) > match_threshold
    ORDER BY kc.embedding <=> query_embedding
    LIMIT match_count;
$$;
