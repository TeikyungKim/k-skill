---
"@nomadamas/k-skill": patch
---

Fix `campsite-recommend` proxy calls being rejected with HTTP 403, and expand the curated Kakao place map.

- The proxy's Cloudflare front rejects urllib's default `Python-urllib/x.y` User-Agent with 403, so `--origin` distance/duration/toll lookups failed on every run while `/health` and curl still returned 200 — the failure looked like "proxy is down". `geocode_origin` and `fetch_route` now send a `PROXY_HEADERS` set that includes an explicit User-Agent.
- `references/place-map.json` grows from 50 to 154 foresttrip entries (공립 71 + 국립·사립 33). Each addition kept the curation rule: only Kakao Local keyword hits whose facility name matches exactly *and* whose address 시군구 matches were accepted. 국립 places are listed as `국립<휴양림명>`, so those were queried under that form. Seven names that differ from the 숲나들e label (쉬자파크, 절물, 장곡, 거창항노화힐링랜드, 설매재, 학가산, 희리산해송) were confirmed against the candidate list's name/address/category by hand. Facilities where only sub-places exist (안동호반, 기찬, 공주산림휴양마을, 피노키오) are still unmapped rather than guessed.
