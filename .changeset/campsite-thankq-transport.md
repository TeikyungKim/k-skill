---
"@nomadamas/k-skill": minor
---

Add a `thankq` transport to `korean-campsite-vacancy` and register 자라섬캠핑장 (가평군시설관리공단).

땡큐캠핑(ThankQ Camping) is a commercial booking platform that municipalities rent instead of running their own system. Unlike the dzSmart transport it answers a plain form POST, so this adapter needs no browser at all — Playwright is now required only for the dzSmart providers.

Registry scope is decided by the **operator**, not the platform: a campground run by a public body qualifies even when its booking window is a private platform, and private campgrounds on the same platform do not. The helper only accepts registered provider ids, so there is no path to sweep arbitrary `campseq` values.
