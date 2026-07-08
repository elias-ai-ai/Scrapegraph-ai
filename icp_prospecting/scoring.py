"""
Hard gate (Section 2) + priority scoring model (Section 6).

    priority_score (0-100) =
        seasonal_pain_score   (0-40, from seasonality.py, by vertical)
      + customer_base_score   (0-25, log-scaled on estimated_customer_base)
      + revenue_fit_score     (0-15, bell curve peaking at revenue-band midpoint)
      + reachability_score    (0-10, from data_confidence + verified fields)
      + longevity_bonus       (0-10, full at 10+ years)

    then x vic_metro_weight for VIC / metro-Melbourne records, clamped to 100.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Config
from .schema import BusinessRecord


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]  # why it failed (empty if passed)


def hard_gate(
    rec: BusinessRecord,
    cfg: Config,
    require_revenue: bool = True,
    require_years: bool = True,
) -> GateResult:
    """Section 2 hard gate. `require_revenue`/`require_years` can be relaxed
    when those signals are unavailable (e.g. Places-only runs where ABN Lookup
    and Apollo enrichment aren't reachable): a missing value then passes with a
    flag instead of disqualifying, but an out-of-band KNOWN value still fails."""
    reasons: list[str] = []

    rev = rec._monthly_revenue_estimate
    if rev is None:
        if require_revenue:
            reasons.append("no revenue estimate")
    elif not (cfg.revenue_min_monthly_aud <= rev <= cfg.revenue_max_monthly_aud):
        reasons.append(f"revenue {rev:.0f}/mo outside band")

    if rec.years_in_business is None:
        if require_years:
            reasons.append("no years-in-business")
    elif rec.years_in_business < cfg.min_years_in_business:
        reasons.append(f"only {rec.years_in_business}y trading")

    if rec.estimated_customer_base is None:
        reasons.append("no customer estimate")
    elif rec.estimated_customer_base < cfg.min_estimated_past_customers:
        reasons.append(f"only ~{rec.estimated_customer_base} customers")

    if not rec._is_repeat_vertical:
        reasons.append("not a repeat-purchase/service vertical")

    return GateResult(not reasons, reasons)


def _customer_base_score(estimated: int | None, cfg: Config, band: float = 25.0) -> float:
    """Log-scale between the gate minimum and a 20x-minimum ceiling.
    More customers -> more score, with diminishing returns."""
    if not estimated:
        return 0.0
    lo = cfg.min_estimated_past_customers            # 1,000
    hi = cfg.min_estimated_past_customers * 20       # 20,000
    e = max(lo, min(hi, estimated))
    frac = (math.log(e) - math.log(lo)) / (math.log(hi) - math.log(lo))
    return round(frac * band, 2)


def _revenue_fit_score(monthly: float | None, cfg: Config, band: float = 15.0) -> float:
    """Bell curve peaking at the midpoint of the revenue band. An established-
    but-not-enterprise business is the best fit for the reactivation offer."""
    if monthly is None:
        return 0.0
    mid = (cfg.revenue_min_monthly_aud + cfg.revenue_max_monthly_aud) / 2
    half_width = (cfg.revenue_max_monthly_aud - cfg.revenue_min_monthly_aud) / 2
    if half_width <= 0:
        return band
    # sigma chosen so the band edges sit at ~1.5 sigma (score ~0.32*band there).
    sigma = half_width / 1.5
    z = (monthly - mid) / sigma
    return round(band * math.exp(-0.5 * z * z), 2)


def _scale_fit_score(reviews: int | None, band: float = 15.0) -> float:
    """Places-only stand-in for revenue-fit when no revenue is available.
    Review count is the only scale signal Places gives; the brief wants
    established-but-not-enterprise, so we peak on a log-review sweet spot and
    demote BOTH tiny shops (too small) and 1000+-review national franchises
    (above the revenue ceiling). Peak ~120 reviews, edges near ~15 and ~1000.
    PROXY — replace with real revenue-fit once revenue is enriched."""
    if not reviews or reviews <= 0:
        return 0.0
    peak_log = math.log(120)
    sigma = math.log(9)  # ~15 and ~950 reviews sit ~1.5 sigma from the peak
    z = (math.log(reviews) - peak_log) / sigma
    return round(band * math.exp(-0.5 * z * z), 2)


def _reachability_score(rec: BusinessRecord, band: float = 10.0) -> float:
    conf_base = {"high": 0.7, "medium": 0.45, "low": 0.15}.get(rec.data_confidence, 0.15)
    verified = sum(bool(getattr(rec, f)) for f in (
        "phone_primary", "phone_direct_owner_manager",
        "email_business", "email_direct_decision_maker",
        "decision_maker_name",
    ))
    verified_frac = min(1.0, verified / 5)
    return round(band * (0.6 * conf_base / 0.7 + 0.4 * verified_frac), 2)


def _longevity_bonus(years: int | None, band: float = 10.0) -> float:
    if not years:
        return 0.0
    return round(band * min(1.0, years / 10), 2)


def _is_vic_metro(rec: BusinessRecord, cfg: Config) -> bool:
    if rec.state and rec.state.strip().upper() in ("VIC", "VICTORIA"):
        return True
    suburb = (rec.suburb or "").strip().lower()
    return any(h in suburb for h in cfg.vic_metro_suburbs_hint)


def priority_score(rec: BusinessRecord, cfg: Config) -> float:
    """Assumes rec passed the hard gate and rec.seasonal_pain_score is set."""
    # Revenue-fit when we have a revenue estimate; otherwise the review-based
    # scale-fit proxy (Places-only runs).
    fit = (_revenue_fit_score(rec._monthly_revenue_estimate, cfg)
           if rec._monthly_revenue_estimate is not None
           else _scale_fit_score(rec.google_review_count))
    total = (
        (rec.seasonal_pain_score or 0.0)
        + _customer_base_score(rec.estimated_customer_base, cfg)
        + fit
        + _reachability_score(rec)
        + _longevity_bonus(rec.years_in_business)
    )
    if _is_vic_metro(rec, cfg):
        total *= cfg.vic_metro_weight
    return round(min(100.0, total), 2)
