# Amy AI — ICP Prospecting pipeline

BDR prospecting for the reactivation offer: find and rank consumer-facing,
repeat-service SMEs where "seasonal trough + dormant customer base → AI SMS
reactivation" lands hardest right now. Implements the brief's hard gate,
seasonal-pain scoring, customer/revenue estimation, QC/dedup, and the ranked
CSV + summary.

## Layout

| File | Brief section | What it does |
|------|---------------|--------------|
| `config.py` | §1 | Run parameters (edit before a run) |
| `verticals.py` | §2, Phase 3 | Seed verticals, Trends keywords, review→customer multipliers |
| `seasonality.py` | §3 | Google Trends seasonality index → 0–40 pain score |
| `scoring.py` | §2, §6 | Hard gate + 0–100 priority model |
| `schema.py` | §4, Phase 6 | Record schema, confidence tagging, dedup |
| `pipeline.py` | Phase 3/6, §7 | Estimation, scoring orchestration, CSV + summary |
| `adapters/apollo.py` | Phase 1/4/5 | Apollo JSON → schema (the live source here) |
| `adapters/places.py` + `places_client.py` | Phase 1/3 | Google Places → schema (needs key) |
| `run.py` | — | CLI: `--self-test`, `--seasonality`, `--records` |

Smoke test (no external calls, fake fixture rows):

```bash
python -m icp_prospecting.run --self-test --out-dir /tmp/icp
```

## What runs in the current (web) environment vs. what needs setup

| Brief data source | Status | Note |
|---|---|---|
| **Apollo.io** | ✅ live | Amy AI's own account via MCP. Costs credits; every call needs explicit confirmation. |
| **Google Places** | ⚠️ reachable, needs key | Host **is allowed** by egress policy; just add `GOOGLE_PLACES_API_KEY`. See below. |
| Google Trends (pytrends, §3) | ❌ blocked | `trends.google.com` is denied by the egress policy (403 at gateway). Run `--seasonality` from a Trends-reachable environment. |
| ABN Lookup (Phase 2) | ❌ no GUID | Free, but needs a registered GUID. |
| SerpAPI / LinkedIn scrape | ❌ no key / N/A | Apollo covers decision-maker contacts instead. |

Two data gaps to keep in mind (Section 8 flags):
- Apollo has **no Google review count** → the review×multiplier customer
  estimate can't run from Apollo alone; `pipeline.estimate_customers_from_scale`
  is a low-confidence fallback. A **Places pass supplies the review count**, so
  Places + Apollo together are the intended combination.
- Apollo has **no ABN** → dedup falls back to domain; ABN column stays blank
  unless cross-referenced against ABN Lookup.

## Connecting to Google Places — securely

The host is reachable here; you only need credentials. Recommended setup:

**1. Create a scoped key in Google Cloud**
   - In the GCP project with billing, enable **Places API (New)**.
   - Create an **API key** used *only* by this pipeline.
   - **Restrict it** (this is the security that matters):
     - *API restriction* → Places API (New) only. A leaked key is then useless
       for any other Google API.
     - *Application restriction* → for server-side use, **IP address**
       restriction to your egress IP if it's stable. In an ephemeral cloud
       container the egress IP can rotate, so if IP-locking isn't practical,
       lean on API restriction + tight quotas + billing alerts instead of an
       unrestricted key.
   - Set a **daily quota cap** and a **billing budget alert** so a leaked or
     runaway key can't run up a bill.

**2. Store the key as a secret, never in the repo**
   - In Claude Code on the web: add `GOOGLE_PLACES_API_KEY` to the
     **environment's variable/secret configuration** (see
     https://code.claude.com/docs/en/claude-code-on-the-web). It is injected at
     runtime and never committed.
   - Locally: `export GOOGLE_PLACES_API_KEY=…` in your shell, not in a tracked
     file. `.env` files must stay git-ignored.
   - The client reads it from `os.environ` only, sends it in the
     `X-Goog-Api-Key` **header** (not the URL, so it can't leak via logs/referrers),
     and never prints it.

**3. Verify the connection**

```bash
export GOOGLE_PLACES_API_KEY=…      # from your secret store
python -c "from icp_prospecting.adapters.places_client import connectivity_check; print(connectivity_check())"
```

**Preferred alternative — OAuth instead of a long-lived key.** Places API (New)
accepts an OAuth 2.0 bearer token from a **service account**, which avoids a
static key entirely. If this environment is provisioned with valid Application
Default Credentials for the billing project, that's the more secure path (no
key to leak, short-lived tokens). The token currently present in this container
is expired, so a key is the fastest route today; wire ADC when available.

Do **not**: hardcode the key, commit it, put it in the URL query string, paste
it into chat, or disable TLS verification to "make it work" (TLS via the proxy
CA bundle already works).
