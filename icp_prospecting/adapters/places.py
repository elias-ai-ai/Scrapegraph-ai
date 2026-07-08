"""
Google Places API (New) result -> BusinessRecord mapping — the brief's
primary Phase 1 discovery path.

Places supplies the fields Apollo can't: Google review count + rating (which
the Phase 3 customer estimate depends on), address, and a public phone.
Years-in-business and revenue come from later enrichment (ABN Lookup / Apollo)
and are passed in when available.
"""

from __future__ import annotations

from ..schema import BusinessRecord
from ..verticals import BY_KEY
from ..pipeline import estimate_customers


def _address_parts(place: dict) -> tuple[str, str, str]:
    """Return (suburb, state, postcode) from Places addressComponents."""
    suburb = state = postcode = ""
    for comp in place.get("addressComponents", []):
        types = comp.get("types", [])
        if "locality" in types:
            suburb = comp.get("longText", "") or comp.get("shortText", "")
        elif "administrative_area_level_1" in types:
            state = comp.get("shortText", "") or comp.get("longText", "")
        elif "postal_code" in types:
            postcode = comp.get("longText", "") or comp.get("shortText", "")
    return suburb, state, postcode


def places_result_to_record(
    place: dict,
    vertical_key: str,
    *,
    years_in_business: int | None = None,
    monthly_revenue_estimate: float | None = None,
) -> BusinessRecord:
    reviews = place.get("userRatingCount")
    est_customers, cust_note = estimate_customers(reviews, vertical_key, years_in_business)
    suburb, state, postcode = _address_parts(place)
    name = (place.get("displayName") or {}).get("text", "")
    website = place.get("websiteUri", "") or ""

    rec = BusinessRecord(
        business_legal_name=name,
        trading_name=name,
        industry_vertical=vertical_key,
        sub_category=place.get("primaryType", ""),
        website=website,
        phone_primary=place.get("nationalPhoneNumber", "")
        or place.get("internationalPhoneNumber", ""),
        physical_address=place.get("formattedAddress", ""),
        suburb=suburb,
        state=state,
        postcode=postcode,
        google_review_count=reviews,
        google_rating=place.get("rating"),
        years_in_business=years_in_business,
        estimated_customer_base=est_customers,
        source_notes=_join("google_places", cust_note),
    )
    rec._domain = website.lower().replace("https://", "").replace("http://", "") \
        .replace("www.", "").split("/")[0]
    rec._monthly_revenue_estimate = monthly_revenue_estimate
    rec._is_repeat_vertical = vertical_key in BY_KEY
    return rec


def _join(*parts: str) -> str:
    return "; ".join(p for p in parts if p)
