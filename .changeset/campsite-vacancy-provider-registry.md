---
"@nomadamas/k-skill": minor
---

Add the `korean-campsite-vacancy` skill: a read-only vacancy lookup for Korean municipal and public campgrounds, built as a provider adapter registry so new reservation systems can be added one adapter at a time.

The first transport, `dzsmart`, covers the 강릉관광개발공사 sites (연곡해변 솔향기캠핑장, 강릉바다내음캠핑장, 강릉오죽한옥마을) with no login or API key. Its month calendar is rendered client-side and the underlying JSON procedure returns 503 when replayed out-of-band, so the adapter loads the official reservation page with Playwright and parses the rendered DOM. `foresttrip` stays in the registry as a delegation pointer to the existing `foresttrip-vacancy` skill.
