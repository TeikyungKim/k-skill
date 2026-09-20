---
"@nomadamas/k-skill": minor
---

Add a `kbo` command to `ticket-availability` that turns a set of Interpark goods codes into a stadium-aware remaining-seat report.

- New public endpoint: `GET /v1/goods/<id>/summary` (no key) supplies `goodsName`, `placeName` and `genreSubName`, so the command can label each goods with the game, the stadium and the date instead of only echoing a code.
- `kbo <url|code> ...` chains `summary` → `playSeq` → `REMAINSEAT` per goods and reports grades with `--min-remain N` (pass the party size), `--stadium 잠실,고척` (substring match on `placeName`), `--exclude-wheelchair`, `--exclude-restricted-view`, `--any-genre` and `--text`. JSON output flags each grade with `wheelchair` / `restricted_view`. Capped at 20 goods per run.
- `instruction.md` now records why the skill does **not** discover goods codes itself: Interpark's list APIs (`/sports/goods`, `/sports/goods/period`) require `X-Client-Id` / `X-Client-Secret`, and `tickets.interpark.com/robots.txt` is `Disallow: /` for generic agents. Codes come from the user or from a web search; the skill never enumerates neighbouring codes.
- `--min-remain` is documented as a per-grade count, not a guarantee of adjacent seats.
