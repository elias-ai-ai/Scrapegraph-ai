"""
Google Places (Text Search) -> BusinessRecord mapping — the brief's primary
Phase 1 discovery path.

NOT ACTIVE in the current environment (no Places API key present). Kept as the
drop-in adapter for when a key is provided: Places is the natural source for the
Google review count + rating that the Phase 3 customer estimate depends on, so
a Places pass complements Apollo (contacts/firmographics) nicely.
"""

from __future__ import annotations

from ..schema import BusinessRecord
from ..verticals import BY_KEY
from ..pipeline import estimate_customers


def places_result_to_record(
    place: dict,
    vertical_key: str,
    *,
    years_in_business: int | None = None,
    monthly_revenue_estimate: float | None = None,
) -> BusinessRecord:
    """Map one Places Text Search result to a BusinessRecord. Places gives the
    review count/rating and address; years-in-business and revenue come from the
    later enrichment phases (ABN Lookup / employee bands) and are passed in."""
    reviews = place.get("user_ratings_total")
    est_customers, cust_note = estimate_customers(reviews, vertical_key, years_in_business)

    rec = BusinessRecord(
        business_legal_name=place.get("name", ""),
        trading_name=place.get("name", ""),
        industry_vertical=vertical_key,
        website=place.get("website", ""),
        phone_primary=place.get("formatted_phone_number", "")
        or place.get("international_phone_number", ""),
        physical_address=place.get("formatted_address", ""),
        google_review_count=reviews,
        google_rating=place.get("rating"),
        years_in_business=years_in_business,
        estimated_customer_base=est_customers,
        source_notes=_join("google_places", cust_note),
    )
    website = (place.get("website") or "").lower()
    rec._domain = website.replace("https://", "").replace("http://", "") \
        .replace("www.", "").split("/")[0]
    rec._monthly_revenue_estimate = monthly_revenue_estimate
    rec._is_repeat_vertical = vertical_key in BY_KEY
    return rec


def _join(*parts: str) -> str:
    return "; ".join(p for p in parts if p)
