---
"@nomadamas/k-skill": minor
---

Add the `campsite-recommend` skill: rank `foresttrip-vacancy` / `korean-campsite-vacancy` results by a reproducible recommendation score.

- Score = Bayesian-adjusted Kakao Map rating (70%) + log-normalized review volume (30%), constants frozen for snapshot-to-snapshot comparability (`references/SCORING.md`).
- Facility → Kakao place id joins use only the curated `references/place-map.json` (숲나들e 50 + 지자체 11 to start); unmapped facilities are reported separately instead of being guessed by name search.
- Ratings come from the public `place-api.map.kakao.com/places/panel3/{id}` surface (no key, browser-shaped headers required); optional `--origin` adds driving distance/duration/toll through the existing k-skill-proxy Kakao Mobility route. Per-facility fetches only, 24h/7d local caches, hard per-run cap.

Also repairs `realty-listing-search` repo bookkeeping that blocked CI: missing `docs/features/realty-listing-search.md`, missing runtime-action-audit row, missing CLI snapshot fixtures, and stale skill-count assertions.
