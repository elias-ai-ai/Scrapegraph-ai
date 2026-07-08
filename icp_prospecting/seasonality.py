"""
Seasonal pain scoring (Section 3) — the differentiator.

    seasonality_index = avg(interest, Jul-Sep) / avg(interest, full year)

Lower index = deeper winter trough = higher pain = higher priority. We invert
and scale to a 0-40 point band for the priority model (Section 6).

METHOD IS "MEASURE, DON'T ASSUME": the numbers come from Google Trends via
pytrends over the trailing 3 years, per vertical keyword. We do NOT hardcode
which verticals suffer.

ENVIRONMENT NOTE: in the current sandbox, trends.google.com is blocked by the
egress policy (403 on CONNECT), so `fetch_seasonality_index` will raise. Run
this module from an environment with Google Trends reachable (or a saved Trends
export) to populate real indices. `provisional_index` exists ONLY as a clearly
labelled placeholder for wiring/testing and must never be shipped as a measured
value — `pain_scores` refuses to use it unless allow_provisional=True.
"""

from __future__ import annotations

from dataclasses import dataclass

from .verticals import Vertical


@dataclass
class SeasonalityResult:
    vertical_key: str
    keyword: str
    seasonality_index: float | None      # None => could not be measured
    seasonal_pain_score: float | None    # 0-40
    n_months: int
    source: str                          # "google_trends" | "provisional" | "unavailable"
    note: str = ""


def fetch_seasonality_index(
    vertical: Vertical,
    geo: str = "AU",
    years: int = 3,
) -> float:
    """Pull monthly interest for the vertical keyword and return the Jul-Sep
    index. Raises on any network/egress failure — callers decide how to degrade.
    """
    from pytrends.request import TrendReq  # local import: optional dependency

    pytrends = TrendReq(hl="en-AU", tz=600, timeout=(10, 25))
    timeframe = f"today {years * 12}-m"
    pytrends.build_payload([vertical.trends_keyword], timeframe=timeframe, geo=geo)
    df = pytrends.interest_over_time()
    if df is None or df.empty:
        raise RuntimeError(f"no Trends data for '{vertical.trends_keyword}'")

    series = df[vertical.trends_keyword]
    full_year_avg = float(series.mean())
    if full_year_avg == 0:
        raise RuntimeError(f"flat/zero Trends series for '{vertical.trends_keyword}'")

    # Jul-Sep months across all captured years.
    winter = series[series.index.month.isin((7, 8, 9))]
    winter_avg = float(winter.mean())
    return winter_avg / full_year_avg


def index_to_pain_score(seasonality_index: float, band: float = 40.0) -> float:
    """Invert + scale the index into 0-`band`.

    index ~1.0 -> no seasonal dip -> ~0 pain.
    index well below 1.0 -> deep trough -> toward `band`.
    An index of 0.5 (Jul-Sep at half the yearly average) maps to full band;
    indices above 1.0 (summer keyword actually peaking in winter, unusual)
    clamp to 0.
    """
    # pain fraction: how far below 1.0 the index sits, capped at a 0.5 floor.
    pain_fraction = max(0.0, min(1.0, (1.0 - seasonality_index) / 0.5))
    return round(pain_fraction * band, 2)


# ---------------------------------------------------------------------------
# PROVISIONAL Australian (Southern-Hemisphere) seasonality — ASSUMPTION, NOT
# MEASURED. Jul-Sep = AU winter/early spring. Values are the estimated
# Jul-Sep-interest / full-year-interest ratio (lower = deeper winter trough =
# more reactivation pain). These are domain-reasoned placeholders to give an
# interim seasonal ranking; REPLACE with measured Google Trends indices
# (fetch_seasonality_index) from a Trends-reachable environment. Flagged so no
# one mistakes them for real data (Section 3 "measure, don't assume").
# ---------------------------------------------------------------------------
PROVISIONAL_AU_SEASONALITY: dict[str, float] = {
    "marine_service": 0.50,    # boating is summer; deep winter trough
    "pool_service": 0.55,      # pools idle in winter
    "pressure_washing": 0.60,  # outdoor, spring/summer driven
    "pest_control": 0.60,      # pests peak in warm months
    "landscaping": 0.62,       # slow grass growth in winter
    "solar_service": 0.70,     # cleaning/checks peak sunny months
    "car_detailing": 0.75,     # dips in winter
    "home_cleaning": 0.80,     # spring-cleaning peak; winter softer
    "fitness": 0.85,           # Jan (summer) peak; winter low motivation
    "pet_services": 0.85,      # boarding peaks summer holidays
    "hair_beauty": 0.90,       # pre-event (spring/summer) peaks
    "property_mgmt": 0.90,     # rental churn peaks summer
    "hvac": 0.92,              # mixed: heating up, cooling-service down
    "med_spa": 0.95,           # winter is treatment-prep season (fairly flat)
    "electrical": 0.95,        # broadly aseasonal, slight winter dip
    "allied_health": 0.97,     # aseasonal
    "auto_repair": 0.97,       # aseasonal
    "dental": 0.98,            # aseasonal
    "tutoring": 1.00,          # Term 3 + mid-year exams: no winter trough
    "plumbing": 1.05,          # winter burst pipes/hot-water: counter-seasonal
}


def provisional_pain_scores(verticals: tuple[Vertical, ...]) -> list[SeasonalityResult]:
    """Build pain scores directly from PROVISIONAL_AU_SEASONALITY with no
    network. Every result is tagged source='provisional' and carries the
    'not measured' note."""
    out: list[SeasonalityResult] = []
    for v in verticals:
        idx = PROVISIONAL_AU_SEASONALITY.get(v.key)
        if idx is None:
            out.append(SeasonalityResult(v.key, v.trends_keyword, None, None, 0,
                                         "unavailable", "no provisional value"))
        else:
            out.append(SeasonalityResult(
                v.key, v.trends_keyword, idx, index_to_pain_score(idx), 0,
                "provisional", "PROVISIONAL AU winter estimate — not measured"))
    return out


def pain_scores(
    verticals: tuple[Vertical, ...],
    geo: str = "AU",
    years: int = 3,
    allow_provisional: bool = False,
    provisional_table: dict[str, float] | None = None,
) -> list[SeasonalityResult]:
    """Compute a SeasonalityResult per vertical.

    Tries the live Trends measurement first. On failure, emits an
    `unavailable` result (index=None) UNLESS allow_provisional=True and a
    provisional_table entry exists — in which case it emits a clearly-marked
    `provisional` score for pipeline testing only.
    """
    results: list[SeasonalityResult] = []
    provisional_table = provisional_table or {}
    for v in verticals:
        try:
            idx = fetch_seasonality_index(v, geo=geo, years=years)
            results.append(SeasonalityResult(
                v.key, v.trends_keyword, round(idx, 4),
                index_to_pain_score(idx), years * 12, "google_trends"))
        except Exception as exc:  # noqa: BLE001 - degrade, don't crash a batch
            prov = provisional_table.get(v.key)
            if allow_provisional and prov is not None:
                results.append(SeasonalityResult(
                    v.key, v.trends_keyword, round(prov, 4),
                    index_to_pain_score(prov), 0, "provisional",
                    note="PLACEHOLDER — not a measured value; replace with live Trends"))
            else:
                results.append(SeasonalityResult(
                    v.key, v.trends_keyword, None, None, 0, "unavailable",
                    note=f"{type(exc).__name__}: {str(exc)[:120]}"))
    return results
