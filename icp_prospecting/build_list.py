"""
End-to-end "Places-only" list build (the path chosen when Apollo enrichment is
deferred and ABN/Trends/general-web egress is unavailable).

Discovery (Places) -> relaxed hard gate (vertical + review-based customer base
enforced; years/revenue marked UNVERIFIED, not disqualifying) -> priority score
on available signals -> ranked CSV + summary.

Seasonality is left unscored here (Google Trends is unreachable in this
environment). Run `icp_prospecting.run --seasonality` from a Trends-reachable
machine and feed the result back via score_and_rank(..., seasonality=...) to
add the differentiator.

Output has PII -> write outside the repo.

    GOOGLE_PLACES_API_KEY=... python -m icp_prospecting.build_list \
        --out-dir /path/outside/repo \
        --locations "Melbourne VIC" "Sydney NSW" "Brisbane QLD" "Perth WA" \
                    "Adelaide SA" "Geelong VIC"
"""

from __future__ import annotations

import argparse
import csv

from .config import DEFAULT
from .discover import discover, report
from .schema import BusinessRecord, CSV_FIELDS
from .pipeline import score_and_rank, write_csv, write_summary
from .verticals import BY_KEY


def _load_candidates(path: str) -> list[BusinessRecord]:
    """Reconstruct records from a cached candidates CSV so re-scoring (e.g.
    after seasonality/revenue enrichment) needs no new Places calls."""
    out: list[BusinessRecord] = []
    for row in csv.DictReader(open(path, encoding="utf-8")):
        d = {k: row.get(k, "") for k in CSV_FIELDS}
        for f in ("years_in_business", "business_founded_year",
                  "estimated_customer_base", "google_review_count"):
            d[f] = int(d[f]) if str(d[f]).strip() not in ("", "None") else None
        for f in ("google_rating", "seasonality_index", "seasonal_pain_score",
                  "priority_score"):
            d[f] = float(d[f]) if str(d[f]).strip() not in ("", "None") else None
        rec = BusinessRecord(**d)
        w = (rec.website or "").lower()
        rec._domain = w.replace("https://", "").replace("http://", "") \
            .replace("www.", "").split("/")[0]
        rec._is_repeat_vertical = rec.industry_vertical in BY_KEY
        out.append(rec)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--locations", nargs="+")
    ap.add_argument("--from-candidates", help="re-score a cached candidates CSV (no Places calls)")
    ap.add_argument("--max-pages", type=int, default=1)
    args = ap.parse_args(argv)
    cfg = DEFAULT

    if args.from_candidates:
        print(f"Re-scoring cached candidates: {args.from_candidates}")
        records = _load_candidates(args.from_candidates)
        print(f"  loaded {len(records)} candidates (0 Places calls)")
    else:
        if not args.locations:
            ap.error("--locations required unless --from-candidates is used")
        print("Phase 1 — discovery (Google Places):")
        records, _, stats = discover(args.locations, max_pages=args.max_pages, verbose=False)
        print(report(records, stats))
        write_csv(records, f"{args.out_dir}/candidates_full.csv")
        print(f"  cached full pool -> candidates_full.csv "
              f"(re-score later with --from-candidates)")

    print("\nPhase 6 — gate + score (revenue/years relaxed, seasonality unscored):")
    ranked, summary = score_and_rank(
        records, seasonality={}, cfg=cfg,
        require_revenue=False, require_years=False)

    prospects = f"{args.out_dir}/prospects.csv"
    write_csv(ranked, prospects)
    write_summary(summary, cfg, f"{args.out_dir}/summary.txt")

    print(f"  evaluated {summary.total_evaluated} -> {summary.passed_gate} in list "
          f"(target {cfg.target_pool_size}); confidence {summary.confidence_counts}")
    print(f"\nwrote {prospects} and summary.txt")
    print("\nDATA GAPS (fill later): years_in_business, revenue band, "
          "decision_maker + direct email, ABN, seasonality index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
