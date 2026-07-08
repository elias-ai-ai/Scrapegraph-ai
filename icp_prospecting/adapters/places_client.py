"""
Minimal, secure Google Places API (New) client for Phase 1 discovery.

SECURITY MODEL (see README "Connecting to Google Places" for the full writeup):
  * The API key is read ONLY from the GOOGLE_PLACES_API_KEY environment
    variable. It is never hardcoded, never logged, and never written to the
    repo. Set it in the Claude Code web environment's variable/secret config
    (or your local shell), not in code.
  * requests honours HTTPS_PROXY + the CA bundle from the environment, so calls
    go through the policy-enforcing egress proxy with TLS intact.
  * Field mask is set explicitly so we pull only what Phase 1/3 need
    (name, address, phone, rating, review count) — smaller responses, and it
    keeps the request to the cheaper SKU where possible.

This module is import-safe with no key present; connect() raises a clear error.
"""

from __future__ import annotations

import os

import requests

_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = ",".join((
    "places.displayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.primaryType",
    "places.addressComponents",
))


def _require_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY is not set. Add it to the environment's "
            "secret config; do not hardcode it. See README.")
    return key


def search_text(query: str, region_code: str = "AU", page_token: str | None = None,
                timeout: int = 25) -> dict:
    """Places Text Search (New). Returns the raw JSON; map results with
    adapters.places.places_result_to_record. Raises on HTTP error."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _require_key(),   # key travels in header, not URL/logs
        "X-Goog-FieldMask": _FIELD_MASK,
    }
    body: dict = {"textQuery": query, "regionCode": region_code}
    if page_token:
        body["pageToken"] = page_token
    resp = requests.post(_ENDPOINT, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def connectivity_check() -> tuple[bool, str]:
    """Cheap probe: is the host reachable and the key valid? Never prints the
    key. Returns (ok, message)."""
    try:
        data = search_text("pool cleaning Melbourne VIC")
        n = len(data.get("places", []))
        return True, f"OK — Places reachable and key valid ({n} sample results)"
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        return False, f"HTTP {code}: {(e.response.text[:200] if e.response else '')}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:200]}"
