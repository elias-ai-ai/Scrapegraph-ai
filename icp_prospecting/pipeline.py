"""
Orchestration: customer estimation (Phase 3), scoring, dedup/QC (Phase 6),
CSV + summary output (Section 7).

Data flows in as `BusinessRecord`s from a data-source adapter (Apollo, Google
Places, etc.). This module is source-agnostic: hand it records + a per-vertical
seasonality map and it produces the ranked CSV and the summary.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass

from .config import Config
from .schema import BusinessRecord, CSV_FIELDS, assess_confidence, dedupe
from .scoring import hard_gate, priority_score
from .seasonality import SeasonalityResult
from .verticals import multiplier_for


def estimate_customers(
    google_review_count: int | None,
    vertical_key: str,
    years_in_business: int | None,
) -> tuple[int | None, str]:
    """Phase 3: estimated_customers = reviews x vertical_multiplier, with a
    plausibility check against tenure. Returns (estimate, flag_note)."""
    if not google_review_count:
        return None, "no review count"
    est = google_review_count * multiplier_for(vertical_key)
    note = ""
    # Sanity check: a young business claiming a huge base is suspect (Section 8).
    if years_in_business and years_in_business <= 3 and est > 8_000:
        note = f"FLAG: {est} customers in <=3y — manual review"
    return est, note


def estimate_customers_from_scale(
    annual_revenue_aud: float | None,
    vertical_key: str,
    avg_ticket_aud: float | None = None,
) -> tuple[int | None, str]:
    """Fallback customer-base proxy when no Google review count is available
    (e.g. Apollo-only discovery). Rough: lifetime customers ~ (annual revenue /
    average ticket) x an assumed tenure/repeat factor. LOW CONFIDENCE — always
    noted. Prefer `estimate_customers` (review-based) when reviews exist."""
    if not annual_revenue_aud:
        return None, "no revenue for customer proxy"
    # Very rough default ticket sizes by vertical family (AUD). Deliberately
    # conservative; flag for calibration (Section 8).
    default_ticket = {
        "dental": 250, "allied_health": 90, "med_spa": 300, "hair_beauty": 80,
        "fitness": 60, "pet_services": 70, "tutoring": 60,
        "auto_repair": 400, "hvac": 350, "pool_service": 120,
        "pest_control": 200, "property_mgmt": 1800,
    }.get(vertical_key, 200)
    ticket = avg_ticket_aud or default_ticket
    # annual transactions -> scale to a ~4yr lifetime base, de-dup repeat buyers.
    annual_txns = annual_revenue_aud / ticket
    est = int(annual_txns * 4 * 0.6)  # 4yr window, 0.6 unique-customer factor
    return est, "customer base is a scale proxy (no reviews) — LOW confidence"


@dataclass
class RunSummary:
    total_evaluated: int
    passed_gate: int
    by_vertical: dict[str, int]
    by_state: dict[str, int]
    avg_pain_by_vertical: dict[str, float | None]
    removed_duplicates: int
    confidence_counts: dict[str, int]


def score_and_rank(
    records: list[BusinessRecord],
    seasonality: dict[str, SeasonalityResult],
    cfg: Config,
) -> tuple[list[BusinessRecord], RunSummary]:
    """Full run: dedupe -> hard gate -> apply seasonality -> confidence ->
    priority score -> sort. Returns (ranked_passing_records, summary)."""
    deduped, removed = dedupe(records)

    passing: list[BusinessRecord] = []
    by_vertical: dict[str, int] = defaultdict(int)
    by_state: dict[str, int] = defaultdict(int)
    conf_counts: dict[str, int] = defaultdict(int)

    for rec in deduped:
        gate = hard_gate(rec, cfg)
        if not gate.passed:
            continue

        sr = seasonality.get(rec.industry_vertical)
        if sr and sr.seasonal_pain_score is not None:
            rec.seasonality_index = sr.seasonality_index
            rec.seasonal_pain_score = sr.seasonal_pain_score
        else:
            # No measured seasonality -> pain contributes 0, noted in source_notes.
            rec.seasonal_pain_score = rec.seasonal_pain_score or 0.0
            _append_note(rec, "seasonality not measured (Trends unavailable)")

        rec.data_confidence = assess_confidence(rec)
        rec.priority_score = priority_score(rec, cfg)
        conf_counts[rec.data_confidence] += 1
        by_vertical[rec.industry_vertical] += 1
        by_state[rec.state or "UNKNOWN"] += 1
        passing.append(rec)

    # Sort: priority desc, but low-confidence records sink (Phase 6).
    conf_rank = {"high": 2, "medium": 1, "low": 0}
    passing.sort(
        key=lambda r: (conf_rank.get(r.data_confidence, 0), r.priority_score or 0.0),
        reverse=True,
    )
    passing = passing[: cfg.target_pool_size]

    avg_pain = {
        vk: (sr.seasonal_pain_score if sr else None)
        for vk, sr in seasonality.items()
    }
    summary = RunSummary(
        total_evaluated=len(deduped),
        passed_gate=len(passing),
        by_vertical=dict(by_vertical),
        by_state=dict(by_state),
        avg_pain_by_vertical=avg_pain,
        removed_duplicates=removed,
        confidence_counts=dict(conf_counts),
    )
    return passing, summary


def _append_note(rec: BusinessRecord, note: str) -> None:
    rec.source_notes = f"{rec.source_notes}; {note}".lstrip("; ") if rec.source_notes else note


def write_csv(records: list[BusinessRecord], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(r.to_row())


def write_summary(summary: RunSummary, cfg: Config, path: str) -> None:
    lines = [
        "Amy AI — ICP Prospecting run summary",
        f"Geography: {cfg.geography} | Target pool: {cfg.target_pool_size} "
        f"| Seasonal window: Jul-Sep | Launch: {cfg.campaign_launch_month}",
        "",
        f"Total businesses evaluated (post-dedup): {summary.total_evaluated}",
        f"Duplicates removed:                      {summary.removed_duplicates}",
        f"Passing hard gate (in final list):       {summary.passed_gate}",
        f"Wave-one size (top 25%):                 {cfg.wave_one_size}",
        "",
        "Data confidence distribution:",
    ]
    for k in ("high", "medium", "low"):
        lines.append(f"  {k:<8}: {summary.confidence_counts.get(k, 0)}")
    lines += ["", "Distribution by vertical:"]
    for vk, n in sorted(summary.by_vertical.items(), key=lambda x: -x[1]):
        lines.append(f"  {vk:<20}: {n}")
    lines += ["", "Distribution by state:"]
    for st, n in sorted(summary.by_state.items(), key=lambda x: -x[1]):
        lines.append(f"  {st:<10}: {n}")
    lines += ["", "Avg seasonal_pain_score by vertical (target-order signal):"]
    for vk, p in sorted(
        summary.avg_pain_by_vertical.items(),
        key=lambda x: (x[1] is None, -(x[1] or 0)),
    ):
        lines.append(f"  {vk:<20}: {'n/a' if p is None else f'{p:.1f}'}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
