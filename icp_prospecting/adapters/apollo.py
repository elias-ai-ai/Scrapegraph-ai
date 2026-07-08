"""
Apollo.io -> BusinessRecord mapping.

Apollo is the one live discovery/enrichment source in the current environment
(Amy AI's own Apollo account, via the MCP tools). The MCP calls themselves are
orchestrated by the agent, not from inside this module — this file is the pure
mapping layer that turns Apollo's JSON into the Section 4 schema, plus the FX
and estimation glue Apollo needs.

KNOWN GAPS vs the brief (flag these — Section 8):
  * Apollo has no Google review count or rating -> the review-based customer
    estimate (Phase 3) can't run; we fall back to a scale proxy (low conf).
  * Apollo has no ABN -> dedup falls back to domain; ABN column stays blank
    unless cross-referenced against ABN Lookup separately.
  * Apollo revenue is annual USD and is often unknown for very small local
    SMEs, which is exactly this ICP's size band -> expect thin coverage.
"""

from __future__ import annotations

from ..schema import BusinessRecord
from ..verticals import BY_KEY, multiplier_for
from ..pipeline import estimate_customers, estimate_customers_from_scale

# Set from the run config / a live FX lookup at run time. 0.66 USD per AUD is a
# placeholder — the agent should refresh it before a real run.
USD_TO_AUD = 1.0 / 0.66


def _domain_of(org: dict) -> str:
    return (org.get("primary_domain") or org.get("website_url") or "").lower() \
        .replace("https://", "").replace("http://", "").replace("www.", "").strip("/")


def apollo_org_to_record(
    org: dict,
    vertical_key: str,
    current_year: int,
    decision_maker: dict | None = None,
    google_review_count: int | None = None,
    google_rating: float | None = None,
) -> BusinessRecord:
    """Map one Apollo organization (+ optional enriched decision-maker person,
    + optional Places review data) to a BusinessRecord.

    `org` is the Apollo organization object; `decision_maker` is an enriched
    person object (from people_match / people_bulk_match) if available.
    """
    founded = org.get("founded_year")
    years = (current_year - founded) if founded else None

    annual_rev_usd = org.get("annual_revenue") or org.get("organization_revenue")
    annual_rev_aud = float(annual_rev_usd) * USD_TO_AUD if annual_rev_usd else None
    monthly_rev_aud = (annual_rev_aud / 12) if annual_rev_aud else None

    # Customer base: prefer review-based (brief's method) if Places gave us a
    # count; otherwise scale proxy.
    if google_review_count:
        est_customers, cust_note = estimate_customers(
            google_review_count, vertical_key, years)
    else:
        est_customers, cust_note = estimate_customers_from_scale(
            annual_rev_aud, vertical_key)

    rev_band = _band(monthly_rev_aud)

    dm = decision_maker or {}
    rec = BusinessRecord(
        business_legal_name=org.get("name", ""),
        trading_name=org.get("name", ""),
        abn="",  # not in Apollo; fill from ABN Lookup cross-ref if run
        industry_vertical=vertical_key,
        sub_category=org.get("industry", ""),
        website=org.get("website_url", ""),
        phone_primary=(org.get("primary_phone") or {}).get("number", "")
        if isinstance(org.get("primary_phone"), dict) else (org.get("phone") or ""),
        phone_direct_owner_manager=dm.get("phone", ""),
        email_business=org.get("email", ""),
        email_direct_decision_maker=dm.get("email", ""),
        decision_maker_name=dm.get("name", ""),
        decision_maker_role=dm.get("title", ""),
        linkedin_company_url=org.get("linkedin_url", ""),
        linkedin_personal_url=dm.get("linkedin_url", ""),
        physical_address=org.get("raw_address", "") or org.get("street_address", ""),
        suburb=org.get("city", ""),
        state=org.get("state", ""),
        postcode=org.get("postal_code", ""),
        years_in_business=years,
        business_founded_year=founded,
        estimated_customer_base=est_customers,
        estimated_monthly_revenue_band=rev_band,
        google_review_count=google_review_count,
        google_rating=google_rating,
        source_notes=_join("apollo", cust_note),
    )
    rec._domain = _domain_of(org)
    rec._monthly_revenue_estimate = monthly_rev_aud
    rec._is_repeat_vertical = vertical_key in BY_KEY
    return rec


def _band(monthly_aud: float | None) -> str:
    if not monthly_aud:
        return ""
    lo = int(monthly_aud // 50_000) * 50_000
    return f"${lo/1000:.0f}k-${(lo+50_000)/1000:.0f}k/mo"


def _join(*parts: str) -> str:
    return "; ".join(p for p in parts if p)
