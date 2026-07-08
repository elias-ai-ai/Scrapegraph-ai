"""
Run entry point.

Modes:
  python -m icp_prospecting.run --self-test
      Runs the full pipeline on an obviously-fake fixture (rows are tagged
      "FIXTURE — NOT A REAL BUSINESS") to prove the scoring/QC/output works
      end-to-end. Produces no real prospect data.

  python -m icp_prospecting.run --records path/to/records.json --out-dir out/
      Scores real records. `records.json` is a list of BusinessRecord dicts,
      produced by the discovery/enrichment step (e.g. the agent's Apollo MCP
      calls mapped through adapters/apollo.py). Writes prospects.csv + summary.

  python -m icp_prospecting.run --seasonality --out-dir out/
      Attempts the live Google Trends seasonality pull (Section 3) and writes
      seasonality.csv. Fails loudly per-vertical where Trends is unreachable.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from .config import DEFAULT, Config
from .schema import BusinessRecord, CSV_FIELDS
from .seasonality import SeasonalityResult, pain_scores
from .pipeline import score_and_rank, write_csv, write_summary
from .verticals import VERTICALS


def _seasonality_map_from_results(results: list[SeasonalityResult]) -> dict[str, SeasonalityResult]:
    return {r.vertical_key: r for r in results}


def cmd_seasonality(cfg: Config, out_dir: str, allow_provisional: bool) -> None:
    results = pain_scores(VERTICALS, geo="AU", years=3, allow_provisional=allow_provisional)
    path = f"{out_dir}/seasonality.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["vertical_key", "keyword", "seasonality_index",
                    "seasonal_pain_score", "source", "note"])
        for r in results:
            w.writerow([r.vertical_key, r.keyword, r.seasonality_index,
                        r.seasonal_pain_score, r.source, r.note])
    measured = sum(1 for r in results if r.source == "google_trends")
    print(f"seasonality: {measured}/{len(results)} verticals measured -> {path}")
    if measured == 0:
        print("WARNING: no verticals measured — Google Trends unreachable here "
              "(egress policy). Run from a Trends-reachable environment.",
              file=sys.stderr)


def cmd_score(cfg: Config, records_path: str, out_dir: str,
              seasonality_path: str | None) -> None:
    with open(records_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    records = [_rec_from_dict(d) for d in raw]

    seasonality: dict[str, SeasonalityResult] = {}
    if seasonality_path:
        with open(seasonality_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                idx = row.get("seasonality_index")
                pain = row.get("seasonal_pain_score")
                seasonality[row["vertical_key"]] = SeasonalityResult(
                    row["vertical_key"], row.get("keyword", ""),
                    float(idx) if idx not in (None, "", "None") else None,
                    float(pain) if pain not in (None, "", "None") else None,
                    0, row.get("source", "unknown"))

    ranked, summary = score_and_rank(records, seasonality, cfg)
    write_csv(ranked, f"{out_dir}/prospects.csv")
    write_summary(summary, cfg, f"{out_dir}/summary.txt")
    print(f"scored {summary.total_evaluated} -> {summary.passed_gate} passing "
          f"-> {out_dir}/prospects.csv")


def _rec_from_dict(d: dict) -> BusinessRecord:
    known = {f for f in CSV_FIELDS}
    rec = BusinessRecord(**{k: v for k, v in d.items() if k in known})
    rec._domain = d.get("_domain", "")
    rec._monthly_revenue_estimate = d.get("_monthly_revenue_estimate")
    rec._is_repeat_vertical = d.get("_is_repeat_vertical", True)
    rec._founded_signal_spread_years = d.get("_founded_signal_spread_years")
    return rec


def _fixture() -> list[BusinessRecord]:
    """Obviously-fake rows for the self-test. NOT real businesses."""
    rows = []
    specs = [
        ("pool_service", "VIC", "Melbourne", 8, 220_000, 900),
        ("dental", "NSW", "Sydney", 12, 180_000, 400),
        ("hair_beauty", "VIC", "Richmond", 5, 90_000, 700),
        ("hvac", "QLD", "Brisbane", 15, 350_000, 1200),
        ("tutoring", "VIC", "Box Hill", 2, 40_000, 300),  # fails gate (young+small)
    ]
    for i, (vk, st, sub, yrs, monthly, reviews) in enumerate(specs):
        r = BusinessRecord(
            business_legal_name=f"FIXTURE — NOT A REAL BUSINESS #{i}",
            trading_name=f"FIXTURE #{i}",
            industry_vertical=vk, state=st, suburb=sub,
            phone_primary="000000000", email_business=f"fixture{i}@example.invalid",
            decision_maker_name=f"Fixture Owner {i}",
            years_in_business=yrs, business_founded_year=2026 - yrs,
            google_review_count=reviews,
        )
        from .pipeline import estimate_customers
        r.estimated_customer_base, _ = estimate_customers(reviews, vk, yrs)
        r._monthly_revenue_estimate = monthly
        r._domain = f"fixture{i}.example.invalid"
        rows.append(r)
    return rows


def cmd_self_test(cfg: Config, out_dir: str) -> None:
    from .seasonality import index_to_pain_score
    # Deterministic fake seasonality so the self-test is reproducible offline.
    fake = {v.key: SeasonalityResult(v.key, v.trends_keyword, 0.7,
                                     index_to_pain_score(0.7), 0, "provisional")
            for v in VERTICALS}
    ranked, summary = score_and_rank(_fixture(), fake, cfg)
    write_csv(ranked, f"{out_dir}/selftest_prospects.csv")
    write_summary(summary, cfg, f"{out_dir}/selftest_summary.txt")
    print(f"self-test OK: {summary.total_evaluated} evaluated, "
          f"{summary.passed_gate} passed gate")
    for r in ranked:
        print(f"  {r.priority_score:5.1f}  {r.data_confidence:<6} "
              f"{r.industry_vertical:<14} {r.business_legal_name}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Amy AI ICP prospecting pipeline")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--seasonality", action="store_true")
    ap.add_argument("--allow-provisional", action="store_true",
                    help="allow placeholder seasonality (testing only)")
    ap.add_argument("--records", help="path to records.json to score")
    ap.add_argument("--seasonality-file", help="seasonality.csv to feed scoring")
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args(argv)

    cfg = DEFAULT
    if args.self_test:
        cmd_self_test(cfg, args.out_dir)
    elif args.seasonality:
        cmd_seasonality(cfg, args.out_dir, args.allow_provisional)
    elif args.records:
        cmd_score(cfg, args.records, args.out_dir, args.seasonality_file)
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
