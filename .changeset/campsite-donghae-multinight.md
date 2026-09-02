---
"@nomadamas/k-skill": patch
---

Correct how `korean-campsite-vacancy` explains an unopened `donghae` date. The `not_open` note claimed the number was the site's total capacity. It is neither vacancy nor capacity.

동해시 opens one use-date at a time (30 days ahead, 11:00), but a multi-night booking made on the first night's open date reaches forward into still-unopened dates and consumes them. Measured 2026-09-02 at 11:22, minutes after 10/02 opened: 10/03 and 10/04 were still `not_open` yet far below a far-out unopened baseline (자동차캠핑장 37 on 10/09 vs 16 on 10/04 vs 3 on 10/03). Only 10/02 was open, so that drop can only be multi-night stays starting 10/02.

Two consequences are now documented in `instruction.md` and `references/PROVIDERS.md`:

- An N-night stay is decided at 11:00 on the **first** night's open date. Telling a user to wait until the last night opens loses the earlier nights. A Fri/Sat/Sun stay has exactly one chance, 30 days before that Friday.
- Reading an unopened number requires comparing it against a far-out baseline date the multi-night reach cannot touch. The adapter still refuses to guess a capacity, so the comparison is the caller's to make, and the workflow now shows the query.

Also documented: `donghae` intermittently fails month navigation with `net::ERR_ABORTED` and passes on a plain retry, and vacancy on an opening day expires in minutes (망상 10/02 went from 2 sites to `full` in 4 minutes).
