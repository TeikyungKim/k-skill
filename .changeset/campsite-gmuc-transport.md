---
"@nomadamas/k-skill": minor
---

Add a `gmuc` transport to `korean-campsite-vacancy` covering 광명도시공사 도덕산캠핑장.

This is the cheapest adapter in the registry: one plain GET to the public reservation-status page returns two server-rendered month tables (current + next), with no login, no browser, and no parameters.

The page carries no month caption beside the grid and its arrows only toggle the two already-rendered tables, so the parser uses the day sequence rolling over (…31, 1, 2…) as the month boundary. Dates outside that two-month window are reported as an explicit failure rather than silently reading as "no vacancy".

Also records the survey of the remaining 지자체·공공 우수야영장 in `references/PROVIDERS.md`: 미리해 (`mirihae.com`, multi-tenant but queue-gated — deliberately not adapted), xticket, 인터파크 추첨제, and 국립공원.
