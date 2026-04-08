"""
Anthropic tool-use schemas for document enrichment.

Each schema is passed as a tool definition to Claude.
Using tool_choice={"type":"tool","name":...} forces structured JSON output
with ~35% fewer output tokens than asking for JSON in prose.

Schema keys match the denormalised columns on kb_chunks for fast metadata filtering.
"""

# ── Past Tender (Opus) ────────────────────────────────────────────────────────

PAST_TENDER_SCHEMA: dict = {
    "name": "enrich_past_tender",
    "description": "Extract structured metadata from a past tender response document",
    "input_schema": {
        "type": "object",
        "properties": {
            "tender_reference": {"type": "string", "description": "Official tender reference / call number"},
            "authority_type": {
                "type": "string",
                "enum": ["EU_COMMISSION", "EU_AGENCY", "NATIONAL_AUTHORITY", "PRIVATE", "UNKNOWN"],
            },
            "regulatory_frameworks_invoked": {
                "type": "array", "items": {"type": "string"},
                "description": "e.g. DORA, GDPR, NIS2, AI Act",
            },
            "contract_value_eur": {"type": "number", "description": "Only if explicitly stated as a clean number in the document. Do not extract garbled, corrupted, or inferred values."},
            "contract_duration_months": {"type": "integer", "description": "Only if explicitly stated. Must be a reasonable value between 1 and 120."},
            "our_positioning": {"type": "string", "description": "How Meridian positioned itself"},
            "value_proposition_one_line": {"type": "string"},
            "differentiation_claim": {"type": "string"},
            "methodology_key_claims": {"type": "array", "items": {"type": "string"}},
            "data_sources_used": {"type": "array", "items": {"type": "string"}},
            "credentials_highlighted": {"type": "array", "items": {"type": "string"}},
            "team_allocation": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                        "days": {"type": "number"},
                    },
                },
            },
            "price_total_eur": {"type": "number", "description": "Only if explicitly stated as a clean number. Do not extract garbled or corrupted values."},
            "day_rate_range_eur": {
                "type": "object",
                "description": "Only if day rates are explicitly stated as clean numbers.",
                "properties": {"min": {"type": "number"}, "max": {"type": "number"}},
            },
            "deliverables": {"type": "array", "items": {"type": "string"}},
            "win_signals": {"type": "array", "items": {"type": "string"}},
            "tender_type_tags": {
                "type": "array", "items": {"type": "string"},
                "description": "e.g. research_study, technical_assistance, framework_contract",
            },
            "sector_tags": {
                "type": "array", "items": {"type": "string"},
                "description": "e.g. fintech, cybersecurity, data_economy, AI_regulation",
            },
        },
        "required": [
            "tender_reference", "authority_type", "our_positioning",
            "tender_type_tags", "sector_tags",
        ],
    },
}

# ── CV (Sonnet) ───────────────────────────────────────────────────────────────

CV_SCHEMA: dict = {
    "name": "enrich_cv",
    "description": "Extract structured metadata from a team member CV",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "title": {"type": "string"},
            "seniority_level": {
                "type": "string",
                "enum": ["junior", "mid", "senior", "principal", "partner"],
            },
            "years_experience": {"type": "integer", "description": "Only if explicitly stated. Must be between 0 and 50."},
            "day_rate_eur": {"type": "number", "description": "Only if explicitly stated as a clean number. Do not estimate."},
            "primary_expertise": {"type": "array", "items": {"type": "string"}},
            "eu_clients_direct": {"type": "array", "items": {"type": "string"}},
            "regulatory_frameworks_known": {"type": "array", "items": {"type": "string"}},
            "technical_skills": {"type": "array", "items": {"type": "string"}},
            "key_projects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "client": {"type": "string"},
                        "role": {"type": "string"},
                    },
                },
            },
            "typical_role_new_client_tender": {"type": "string"},
            "typical_role_regulatory_tender": {"type": "string"},
            "strongest_credential_one_liner": {"type": "string"},
            "languages": {"type": "array", "items": {"type": "string"}},
            "tender_type_tags": {"type": "array", "items": {"type": "string"}},
            "sector_tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "title", "primary_expertise", "tender_type_tags", "sector_tags"],
    },
}

# ── Methodology (Sonnet) ──────────────────────────────────────────────────────

METHODOLOGY_SCHEMA: dict = {
    "name": "enrich_methodology",
    "description": "Extract structured metadata from a methodology document",
    "input_schema": {
        "type": "object",
        "properties": {
            "methodology_name": {"type": "string"},
            "problem_solved": {"type": "string"},
            "pipeline_stages": {"type": "array", "items": {"type": "string"}},
            "evidence_types_accepted": {"type": "array", "items": {"type": "string"}},
            "performance_commitments": {"type": "array", "items": {"type": "string"}},
            "tech_stack": {"type": "array", "items": {"type": "string"}},
            "key_claims_for_proposals": {"type": "array", "items": {"type": "string"}},
            "regulatory_alignment_capability": {"type": "array", "items": {"type": "string"}},
            "best_fit_tender_types": {"type": "array", "items": {"type": "string"}},
            "sector_tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "methodology_name", "problem_solved",
            "key_claims_for_proposals", "sector_tags",
        ],
    },
}

# ── Company Profile (Haiku) ───────────────────────────────────────────────────

COMPANY_PROFILE_SCHEMA: dict = {
    "name": "enrich_company_profile",
    "description": "Extract structured metadata from a company profile document",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_name": {"type": "string"},
            "legal_form": {"type": "string"},
            "vat_number": {"type": "string"},
            "eu_pic": {"type": "string", "description": "EU Participant Identification Code"},
            "iso_certifications": {"type": "array", "items": {"type": "string"}},
            "annual_turnover_eur": {"type": "number", "description": "Only if explicitly stated as a clean number. Do not estimate or infer."},
            "team_size_fte": {"type": "integer", "description": "Only if explicitly stated. Must be between 1 and 100000."},
            "selected_references": {"type": "array", "items": {"type": "string"}},
            "client_types": {"type": "array", "items": {"type": "string"}},
            "primary_contact": {"type": "string"},
            "sector_tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["company_name"],
    },
}

# ── Lookup map ────────────────────────────────────────────────────────────────

SCHEMA_MAP: dict[str, dict] = {
    "past_tender": PAST_TENDER_SCHEMA,
    "cv": CV_SCHEMA,
    "methodology": METHODOLOGY_SCHEMA,
    "company_profile": COMPANY_PROFILE_SCHEMA,
}
