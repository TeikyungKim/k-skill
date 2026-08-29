---
"@nomadamas/k-skill": minor
---

Add a `donghae` transport to `korean-campsite-vacancy` covering the four 동해시시설관리공단 campgrounds: 망상오토캠핑리조트, 망상제2오토캠핑장, 무릉힐링캠핑장, 추암오토캠핑장.

This is the skill's first provider that needs a login. The site encrypts the password client-side with CryptoJS AES, so the adapter drives the real form with Playwright instead of reimplementing the crypto, and reads credentials only from `KSKILL_DONGHAE_ID` / `KSKILL_DONGHAE_PASSWORD`. The skill now declares the `vault` profile.

The CAPTCHA on that site guards the booking step, not the vacancy view: the reservation page issues its own PASS key on load and the read-only calendar endpoint accepts it, the same way `foresttrip-vacancy` reuses its page's CSRF token. The adapter never solves, OCRs, or bypasses the CAPTCHA, and reports `NOPASS` as a failure instead of retrying.
