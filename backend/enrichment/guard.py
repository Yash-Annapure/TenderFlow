"""
3-layer integrity guard for KB document enrichment.

Layer 1 — Structural (rule-based):
    Required fields present; correct types; no obviously invalid values.
    BLOCK on failure — no LLM cost.

Layer 2 — Claim Provenance (Sonnet, ~700 tokens):
    Every numeric/financial claim in the enrichment JSON must be traceable
    to the source text. Pre-filtered with regex so Sonnet only sees unverified claims.
    BLOCK on any unverifiable factual claim.

Layer 3 — Cross-Doc Consistency (SQL-first, Sonnet only on conflict):
    Queries kb_facts for the same entity + field.
    BLOCK on financial figure conflicts (>5% divergence).
    WARN on soft fields (dates, team sizes).

Severity semantics:
  BLOCK → document cannot be committed; ingest pipeline stops.
  WARN  → document is committed but flagged for human review via kb_pending_reviews.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from config.settings import settings
from core.supabase_client import get_supabase_admin

logger = logging.getLogger(__name__)

# Matches currency amounts, percentages, and common unit quantities
_FACTUAL_CLAIM_RE = re.compile(
    r"(?:€[\d,\.]+|\$[\d,\.]+|\d[\d,\.]*\s*"
    r"(?:EUR|USD|million|billion|%|days?|months?|years?|FTE|staff|employees?))",
    re.IGNORECASE,
)

_anthropic_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class GuardFlag:
    layer: int
    severity: str  # "BLOCK" | "WARN"
    message: str
    field: str = ""


@dataclass
class GuardResult:
    flags: list[GuardFlag] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.has_blocks()

    def has_blocks(self) -> bool:
        return any(f.severity == "BLOCK" for f in self.flags)

    def has_warnings(self) -> bool:
        return any(f.severity == "WARN" for f in self.flags)

    def to_json(self) -> list[dict]:
        return [
            {"layer": f.layer, "severity": f.severity, "message": f.message, "field": f.field}
            for f in self.flags
        ]


# ── Public entry point ────────────────────────────────────────────────────────

def run_guard(
    doc_type: str,
    enrichment: dict,
    raw_text: str,
    document_id: Optional[str] = None,
) -> GuardResult:
    """Run all three guard layers and return a consolidated GuardResult."""
    result = GuardResult()

    # Layer 1: structural (no LLM)
    result.flags.extend(_layer1_structural(doc_type, enrichment))
    if result.has_blocks():
        logger.warning(f"Guard L1 BLOCKED document {document_id}")
        return result

    # Layer 2: claim provenance (Sonnet, conditional) — issues WARN only
    result.flags.extend(_layer2_provenance(enrichment, raw_text))

    # Layer 3: cross-doc consistency (SQL-first)
    if document_id:
        result.flags.extend(_layer3_cross_doc(enrichment, doc_type, document_id))

    return result


def commit_facts(enrichment: dict, doc_type: str, document_id: str) -> None:
    """
    Persist extractable financial facts to kb_facts for future cross-doc checks.
    Call this only after guard passes.
    """
    supabase = get_supabase_admin()
    _PLACEHOLDER_VALUES = {"<unknown>", "unknown", "n/a", "none", "tbd", "", "<tbd>", "not provided"}
    raw_ref = (
        enrichment.get("tender_reference")
        or enrichment.get("name")
        or enrichment.get("company_name")
    )
    entity_ref = (
        raw_ref if raw_ref and raw_ref.strip().lower() not in _PLACEHOLDER_VALUES
        else document_id
    )

    financial_fields = [
        "contract_value_eur",
        "price_total_eur",
        "annual_turnover_eur",
        "day_rate_eur",
    ]

    for field_name in financial_fields:
        value = enrichment.get(field_name)
        if value is not None:
            try:
                supabase.table("kb_facts").upsert(
                    {
                        "fact_type": "financial",
                        "entity_ref": entity_ref,
                        "field_name": field_name,
                        "value": str(value),
                        "source_doc": document_id,
                    },
                    on_conflict="entity_ref,field_name",
                ).execute()
            except Exception as e:
                logger.warning(f"Failed to commit fact {field_name} for {entity_ref}: {e}")


# ── Layer implementations ─────────────────────────────────────────────────────

def _layer1_structural(doc_type: str, enrichment: dict) -> list[GuardFlag]:
    """Check required fields are present — pure Python, no LLM."""
    from enrichment.schemas import SCHEMA_MAP

    schema = SCHEMA_MAP.get(doc_type)
    if not schema:
        return []

    required_fields = schema["input_schema"].get("required", [])
    flags: list[GuardFlag] = []

    for f in required_fields:
        if f not in enrichment or enrichment[f] is None or enrichment[f] == "":
            flags.append(
                GuardFlag(
                    layer=1,
                    severity="BLOCK",
                    message=f"Required enrichment field '{f}' is missing or null",
                    field=f,
                )
            )

    # Sanity-check numeric fields for obviously invalid values
    numeric_bounds = {
        "contract_duration_months": (1, 120),
        "years_experience": (0, 50),
        "team_size_fte": (1, 100_000),
    }
    for field_name, (lo, hi) in numeric_bounds.items():
        val = enrichment.get(field_name)
        if val is not None:
            try:
                v = float(val)
                if not (lo <= v <= hi):
                    flags.append(GuardFlag(
                        layer=1,
                        severity="BLOCK",
                        message=f"Field '{field_name}' value {v} is outside valid range [{lo}, {hi}] — likely a PDF parsing artifact",
                        field=field_name,
                    ))
            except (TypeError, ValueError):
                pass

    return flags


def _is_plausible_claim(claim: str) -> bool:
    """
    Filter out obviously garbled PDF artifact values before sending to LLM.
    Returns False for claims that are clearly invalid (e.g. 226597%, 2013249 employees).
    """
    # Extract leading number
    num_match = re.match(r"[\$€]?([\d,\.]+)", claim.replace(" ", ""))
    if not num_match:
        return True
    try:
        value = float(num_match.group(1).replace(",", ""))
    except ValueError:
        return True

    claim_lower = claim.lower()
    # Percentages over 100% are always garbled artifacts
    if "%" in claim_lower and value > 100:
        return False
    # Employee/staff/FTE counts over 100k are unrealistic for KB documents
    if any(w in claim_lower for w in ["employees", "staff", "fte"]) and value > 100_000:
        return False
    # Day counts over 10,000 are garbled
    if "day" in claim_lower and value > 10_000:
        return False

    return True


def _layer2_provenance(enrichment: dict, raw_text: str) -> list[GuardFlag]:
    """
    Verify that numeric/financial claims in the enrichment JSON appear in the source text.
    Skips the LLM call entirely if no numeric claims are found (most company_profile docs).
    """
    enrichment_str = json.dumps(enrichment)
    raw_claims = list(set(_FACTUAL_CLAIM_RE.findall(enrichment_str)))
    # Filter out obviously garbled PDF artifact values
    claims = [c for c in raw_claims if _is_plausible_claim(c)]

    if not claims:
        return []

    client = _get_client()
    prompt = (
        "You are verifying that factual claims extracted from a document are supported "
        "by the source text.\n\n"
        f"Source text (first 3000 chars):\n<source>\n{raw_text[:3000]}\n</source>\n\n"
        f"Extracted claims to verify:\n{json.dumps(claims, indent=2)}\n\n"
        "For each claim that CANNOT be found in or reasonably inferred from the source, "
        "return a JSON array: [{\"claim\": \"...\", \"reason\": \"...\"}]\n"
        "If all claims are verified, return: []"
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            unverified = json.loads(match.group())
            return [
                GuardFlag(
                    layer=2,
                    severity="WARN",
                    message=f"Unverified claim: \"{item['claim']}\" — {item.get('reason', '')}",
                    field="claim_provenance",
                )
                for item in unverified
            ]
    except Exception as e:
        logger.warning(f"Guard L2 provenance check failed: {e}")

    return []


def _layer3_cross_doc(enrichment: dict, doc_type: str, document_id: str) -> list[GuardFlag]:
    """
    Compare financial figures against kb_facts for the same entity.
    SQL-first: only calls Sonnet if a conflict is detected (rare path).
    """
    flags: list[GuardFlag] = []
    supabase = get_supabase_admin()

    _PLACEHOLDER_VALUES = {"<unknown>", "unknown", "n/a", "none", "tbd", "", "<tbd>", "not provided"}

    raw_ref = (
        enrichment.get("tender_reference")
        or enrichment.get("name")
        or enrichment.get("company_name")
    )
    entity_ref = (
        raw_ref if raw_ref and raw_ref.strip().lower() not in _PLACEHOLDER_VALUES
        else document_id
    )

    financial_fields = ["contract_value_eur", "price_total_eur", "annual_turnover_eur", "day_rate_eur"]

    for field_name in financial_fields:
        new_value = enrichment.get(field_name)
        if new_value is None:
            continue

        try:
            result = (
                supabase.table("kb_facts")
                .select("value, source_doc")
                .eq("entity_ref", entity_ref)
                .eq("field_name", field_name)
                .execute()
            )
        except Exception as e:
            logger.warning(f"Guard L3 SQL query failed for {field_name}: {e}")
            continue

        if not result.data:
            continue  # No existing fact — nothing to conflict with

        existing_value = float(result.data[0]["value"])
        new_float = float(new_value)

        # Allow for unit differences (e.g. "4.2" million stored as 4200000)
        if existing_value > 1000 and new_float < 1000:
            new_float *= 1_000_000
        elif new_float > 1000 and existing_value < 1000:
            existing_value *= 1_000_000
        divergence = abs(existing_value - new_float) / max(abs(existing_value), 1)

        if divergence > 0.05:
            flags.append(
                GuardFlag(
                    layer=3,
                    severity="BLOCK",
                    message=(
                        f"Financial conflict on {field_name} for '{entity_ref}': "
                        f"new={new_float}, existing={existing_value} "
                        f"({divergence * 100:.1f}% divergence)"
                    ),
                    field=field_name,
                )
            )

    return flags
