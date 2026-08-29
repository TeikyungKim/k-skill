---
"@nomadamas/k-skill": minor
---

Add a `maketicket` transport to `korean-campsite-vacancy` covering 삼척 장호비치캠핑장 and 화성시향남오토캠핑장.

스마틱스(smartix) MakeTicket is rented by several municipalities and has no login, no CAPTCHA, and no queue — a ticket-page GET for the rotating `idkey`, then a plain form POST returns the month calendar. Each rendered slot carries its own full date, so the parser never infers a month from position.

화성 향남 was previously recorded as blocked: its 화성시 통합예약 surface walls off even the vacancy view behind a login. The same campground is public on MakeTicket, so that entry is corrected — when one official surface is login-walled, check whether another public one exists before giving up.
