"""
Amy AI — ICP Prospecting: run parameters (Section 1 of the brief).

Edit these before a run. Everything downstream (hard gate, scoring, output)
reads from this single Config object so a run is fully reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    # --- Section 1 parameters -------------------------------------------------
    geography: str = "Australia-wide"
    # Scoring weight applied to VIC / metro-Melbourne businesses. No hard
    # exclusion of other regions — this only nudges ranking.
    vic_metro_weight: float = 1.2

    target_pool_size: int = 300

    revenue_min_monthly_aud: int = 50_000
    revenue_max_monthly_aud: int = 400_000

    min_years_in_business: int = 3
    min_estimated_past_customers: int = 1_000

    # Current pain window we score seasonality against.
    seasonal_window_months: tuple[int, ...] = (7, 8, 9)  # Jul-Sep
    campaign_launch_month: str = "2026-07"

    # --- Derived / convenience ------------------------------------------------
    # AUD annual revenue band the monthly figures imply, for sources (e.g.
    # Apollo) that only expose annual revenue. Used by data-source adapters.
    @property
    def revenue_min_annual_aud(self) -> int:
        return self.revenue_min_monthly_aud * 12

    @property
    def revenue_max_annual_aud(self) -> int:
        return self.revenue_max_monthly_aud * 12

    # Wave-one cutoff: top quartile of the target pool goes out first.
    @property
    def wave_one_size(self) -> int:
        return max(1, round(self.target_pool_size * 0.25))

    # States/territories that receive the metro weight boost. Kept explicit so
    # the boost is auditable rather than a magic string match.
    vic_metro_suburbs_hint: tuple[str, ...] = field(
        default=(
            "melbourne", "richmond", "st kilda", "brunswick", "footscray",
            "box hill", "dandenong", "frankston", "geelong", "ringwood",
        )
    )


DEFAULT = Config()
