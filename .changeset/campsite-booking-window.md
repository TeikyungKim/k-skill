---
"@nomadamas/k-skill": patch
---

Fix `korean-campsite-vacancy` reporting full capacity as vacancy for dates whose booking window has not opened yet.

동해시 opens each date 30 days ahead at 11:00. Before that the detail endpoint still answers, but with the site's full capacity — nobody can have booked. A lookup for 10/2~10/5 returned identical numbers for all four days, matching total inventory, and read as "everything wide open".

The `donghae` adapter now reads the month calendar's per-day label alongside the detail call and carries a `booking_status` (`open` / `full` / `closed` / `not_open` / `unknown`). Non-open days are still shown — silently dropping a date the user asked about is worse — but every zone is forced to `available: false` and a `status_note` explains why. An unrecognised label degrades to `unknown` rather than being assumed open.
