"""
Business record schema (Section 4), data-confidence tagging + dedup/QC
(Phase 6). Data-source adapters produce `BusinessRecord`s; the pipeline scores
and writes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields

# Exact column order for the output CSV (Section 4) + appended scoring columns.
CSV_FIELDS: tuple[str, ...] = (
    "business_legal_name",
    "trading_name",
    "abn",
    "industry_vertical",
    "sub_category",
    "website",
    "phone_primary",
    "phone_direct_owner_manager",
    "email_business",
    "email_direct_decision_maker",
    "decision_maker_name",
    "decision_maker_role",
    "linkedin_company_url",
    "linkedin_personal_url",
    "physical_address",
    "suburb",
    "state",
    "postcode",
    "years_in_business",
    "business_founded_year",
    "estimated_customer_base",
    "estimated_monthly_revenue_band",
    "google_review_count",
    "google_rating",
    "seasonality_index",
    "seasonal_pain_score",
    "priority_score",
    "data_confidence",
    "source_notes",
)


@dataclass
class BusinessRecord:
    business_legal_name: str = ""
    trading_name: str = ""
    abn: str = ""
    industry_vertical: str = ""
    sub_category: str = ""
    website: str = ""
    phone_primary: str = ""
    phone_direct_owner_manager: str = ""
    email_business: str = ""
    email_direct_decision_maker: str = ""
    decision_maker_name: str = ""
    decision_maker_role: str = ""
    linkedin_company_url: str = ""
    linkedin_personal_url: str = ""
    physical_address: str = ""
    suburb: str = ""
    state: str = ""
    postcode: str = ""
    years_in_business: int | None = None
    business_founded_year: int | None = None
    estimated_customer_base: int | None = None
    estimated_monthly_revenue_band: str = ""
    google_review_count: int | None = None
    google_rating: float | None = None
    seasonality_index: float | None = None
    seasonal_pain_score: float | None = None
    priority_score: float | None = None
    data_confidence: str = ""        # high / medium / low
    source_notes: str = ""

    # --- not emitted to CSV; used for dedup / scoring internals --------------
    _domain: str = field(default="", repr=False)
    _founded_signal_spread_years: int | None = field(default=None, repr=False)
    # Point estimate (AUD/month) behind the revenue band, for the revenue-fit
    # bell curve. Adapters set this; CSV shows only the band.
    _monthly_revenue_estimate: float | None = field(default=None, repr=False)
    # True if the vertical is a consumer-facing repeat-purchase/service business
    # (Section 2 hard gate). Adapters set this from the vertical mapping.
    _is_repeat_vertical: bool = field(default=True, repr=False)

    def to_row(self) -> dict:
        d = asdict(self)
        return {k: d[k] for k in CSV_FIELDS}


# Reachability fields that drive data_confidence (Phase 6).
_REACH_FIELDS = ("phone_primary", "email_business", "decision_maker_name")


def assess_confidence(rec: BusinessRecord) -> str:
    """Phase 6: a record missing more than one of {phone, email, decision_maker}
    is `low` and sinks to the bottom of the ranking (kept, not dropped).
    Founded-date signals disagreeing >3yr also caps at `low` (flag, Section 8).
    """
    present = sum(1 for f in _REACH_FIELDS if getattr(rec, f))
    missing = len(_REACH_FIELDS) - present

    if rec._founded_signal_spread_years is not None and rec._founded_signal_spread_years > 3:
        return "low"
    if missing >= 2:
        return "low"
    if missing == 1:
        return "medium"
    # full reachability + a direct contact -> high
    if rec.phone_direct_owner_manager or rec.email_direct_decision_maker:
        return "high"
    return "medium"


def dedupe(records: list[BusinessRecord]) -> tuple[list[BusinessRecord], int]:
    """Phase 6: dedupe on ABN first, then domain. Returns (kept, n_removed).
    Merges by keeping the record with the most populated reachability fields.
    """
    def score(r: BusinessRecord) -> int:
        return sum(1 for f in _REACH_FIELDS if getattr(r, f)) + bool(r.abn)

    best: dict[str, BusinessRecord] = {}
    order: list[str] = []
    removed = 0
    for r in records:
        key = f"abn:{r.abn}" if r.abn else (f"dom:{r._domain}" if r._domain else None)
        if key is None:
            # No dedup key — keep, but use identity so it's never merged away.
            key = f"id:{id(r)}"
        if key in best:
            removed += 1
            if score(r) > score(best[key]):
                best[key] = r
        else:
            best[key] = r
            order.append(key)
    return [best[k] for k in order], removed
