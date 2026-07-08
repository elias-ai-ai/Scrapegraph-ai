"""
Vertical scope (Section 2) + estimation multipliers (Phase 3) +
representative Google Trends keywords (Section 3).

The vertical list is a SEED for search queries, not a hard restriction — the
discovery layer is free to expand beyond it. The point of keeping it here is
that three things must line up per vertical: the search seed, the
customer-per-review multiplier, and the seasonality keyword.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Vertical:
    key: str
    label: str
    # Query seeds handed to the discovery layer (Places text search / Apollo
    # keyword tags). Expanded with location suffixes at query time.
    search_seeds: tuple[str, ...]
    # Representative keyword for the Google Trends seasonality pull (Section 3).
    trends_keyword: str
    # Google-review -> lifetime-customer multiplier (Phase 3). These vary a LOT
    # by industry: hospitality/retail run high (many buyers, few review), health
    # runs low (clients rarely review). Sanity-check against years in business.
    customer_multiplier: int
    # NAICS prefixes to help Apollo/registry-based discovery. Optional.
    naics_hints: tuple[str, ...] = ()


# review -> customer multiplier rationale, in one place so it can be audited and
# flagged back (Section 8) once real data arrives:
#   high (40-60): low review propensity per transaction (trades, home services,
#                 auto) — many jobs never get a review.
#   mid  (25-35): moderate propensity (salons, fitness, pet).
#   low  (12-20): clients review often relative to base OR small bases per
#                 review (some clinics), so a review count over-represents base
#                 less — but health clients rarely review at all, pushing it
#                 back up. Kept conservative; FLAG for calibration.
DEFAULT_MULTIPLIER = 30  # per brief: default when vertical not in table

VERTICALS: tuple[Vertical, ...] = (
    Vertical("pool_service", "Pool cleaning / servicing",
             ("pool cleaning", "pool servicing", "pool maintenance"),
             "pool cleaning", 45, ("5617",)),
    Vertical("landscaping", "Landscaping / lawn care",
             ("landscaping", "lawn care", "lawn mowing"),
             "lawn mowing", 45, ("5617",)),
    Vertical("pressure_washing", "Pressure washing",
             ("pressure washing", "high pressure cleaning"),
             "pressure washing", 50),
    Vertical("car_detailing", "Mobile car detailing",
             ("mobile car detailing", "car detailing"),
             "car detailing", 40, ("8111",)),
    Vertical("pest_control", "Pest control",
             ("pest control", "termite inspection"),
             "pest control", 40, ("5617",)),
    Vertical("home_cleaning", "Home / window cleaning",
             ("house cleaning", "window cleaning", "domestic cleaning"),
             "house cleaning", 45, ("5617",)),
    Vertical("hair_beauty", "Hair & beauty salons",
             ("hair salon", "beauty salon", "hairdresser"),
             "hairdresser", 28, ("8121",)),
    Vertical("med_spa", "Med spas / cosmetic clinics",
             ("med spa", "cosmetic clinic", "skin clinic"),
             "cosmetic clinic", 20, ("6214", "8121")),
    Vertical("dental", "Dental clinics",
             ("dental clinic", "dentist"),
             "dentist", 18, ("6212",)),
    Vertical("allied_health", "Allied health (physio/chiro/optom)",
             ("physiotherapy", "chiropractor", "optometrist"),
             "physiotherapy", 18, ("6213",)),
    Vertical("fitness", "Gyms & fitness studios",
             ("gym", "fitness studio", "pilates studio"),
             "gym membership", 25, ("7139",)),
    Vertical("pet_services", "Pet grooming & boarding",
             ("pet grooming", "dog boarding", "dog grooming"),
             "dog grooming", 30, ("8129",)),
    Vertical("auto_repair", "Auto repair & servicing",
             ("auto repair", "car service", "mechanic"),
             "car service", 40, ("8111",)),
    Vertical("hvac", "HVAC / aircon servicing",
             ("air conditioning service", "hvac service", "aircon repair"),
             "air conditioning service", 50, ("2382",)),
    Vertical("solar_service", "Solar servicing",
             ("solar panel cleaning", "solar service", "solar maintenance"),
             "solar panel cleaning", 45, ("2382",)),
    Vertical("marine_service", "Boat & marine servicing",
             ("boat servicing", "marine mechanic"),
             "boat service", 45, ("8113",)),
    Vertical("tutoring", "Tutoring & education services",
             ("tutoring", "tutor", "maths tutoring"),
             "tutoring", 25, ("6116",)),
    Vertical("property_mgmt", "Real estate property management",
             ("property management", "rental property management"),
             "property management", 20, ("5313",)),
    Vertical("electrical", "Electrical (maintenance contracts)",
             ("electrician", "electrical contractor"),
             "electrician", 50, ("2382",)),
    Vertical("plumbing", "Plumbing (maintenance contracts)",
             ("plumber", "plumbing service"),
             "plumber", 50, ("2382",)),
)

BY_KEY = {v.key: v for v in VERTICALS}


def multiplier_for(vertical_key: str) -> int:
    v = BY_KEY.get(vertical_key)
    return v.customer_multiplier if v else DEFAULT_MULTIPLIER
