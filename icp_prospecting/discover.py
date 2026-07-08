"""
Phase 1 discovery driver (Google Places).

Iterates vertical seeds x locations, calls Places Text Search, maps results to
BusinessRecords, dedupes, and writes a candidates CSV + a volume report.

Output contains real business contact data (PII), so it is written to an
out-dir OUTSIDE the repo by the caller and must not be committed to git.

    GOOGLE_PLACES_API_KEY=... python -m icp_prospecting.discover \
        --out-dir /path/outside/repo --locations "Melbourne VIC" "Geelong VIC" \
        --max-pages 2
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict

from .adapters.places import places_result_to_record
from .adapters.places_client import search_text
from .schema import BusinessRecord, dedupe
from .pipeline import write_csv
from .verticals import VERTICALS, BY_KEY

# Australian states/territories — used to drop foreign homonyms (e.g. a
# "Perth WA" query occasionally returns Perth, Scotland). Empty state is kept
# (Places didn't return an admin area), foreign non-empty states are dropped.
AU_STATES = {"VIC", "NSW", "QLD", "WA", "SA", "TAS", "ACT", "NT"}


def discover(
    locations: list[str],
    vertical_keys: list[str] | None = None,
    max_pages: int = 1,
    seeds_per_vertical: int = 1,
    sleep_s: float = 0.4,
    verbose: bool = True,
) -> tuple[list[BusinessRecord], int, dict]:
    verticals = [BY_KEY[k] for k in vertical_keys] if vertical_keys else list(VERTICALS)
    records: list[BusinessRecord] = []
    n_queries = 0
    per_vertical_raw: dict[str, int] = defaultdict(int)

    for v in verticals:
        for seed in v.search_seeds[:seeds_per_vertical]:
            for loc in locations:
                query = f"{seed} {loc}"
                page_token = None
                for _ in range(max_pages):
                    data = search_text(query, region_code="AU", page_token=page_token)
                    n_queries += 1
                    places = data.get("places", [])
                    for p in places:
                        rec = places_result_to_record(p, v.key)
                        st = (rec.state or "").strip().upper()
                        if st and st not in AU_STATES:
                            continue  # foreign homonym, e.g. Perth, Scotland
                        records.append(rec)
                        per_vertical_raw[v.key] += 1
                    if verbose:
                        print(f"  [{query}] +{len(places)} (raw total {len(records)})")
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break
                    time.sleep(sleep_s)  # New API requires a short wait before paging

    deduped, removed = dedupe(records)
    stats = {
        "queries": n_queries,
        "raw": len(records),
        "unique": len(deduped),
        "removed": removed,
        "per_vertical_raw": dict(per_vertical_raw),
    }
    return deduped, removed, stats


def report(records: list[BusinessRecord], stats: dict) -> str:
    by_v: dict[str, int] = defaultdict(int)
    with_site = with_phone = with_min_customers = 0
    for r in records:
        by_v[r.industry_vertical] += 1
        with_site += bool(r.website)
        with_phone += bool(r.phone_primary)
        if r.estimated_customer_base and r.estimated_customer_base >= 1000:
            with_min_customers += 1
    lines = [
        f"queries run:        {stats['queries']}",
        f"raw results:        {stats['raw']}",
        f"unique candidates:  {stats['unique']}  (removed {stats['removed']} dupes)",
        f"have website:       {with_site}  (enrichable via Apollo by domain)",
        f"have phone:         {with_phone}",
        f"est >=1000 customers (reviews x mult): {with_min_customers}",
        "unique by vertical:",
    ]
    for vk, n in sorted(by_v.items(), key=lambda x: -x[1]):
        lines.append(f"  {vk:<20}: {n}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--locations", nargs="+", required=True)
    ap.add_argument("--verticals", nargs="*", default=None)
    ap.add_argument("--max-pages", type=int, default=1)
    ap.add_argument("--seeds-per-vertical", type=int, default=1)
    args = ap.parse_args(argv)

    records, _, stats = discover(
        args.locations, args.verticals, args.max_pages, args.seeds_per_vertical)
    out = f"{args.out_dir}/places_candidates.csv"
    write_csv(records, out)
    print("\n" + report(records, stats))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
