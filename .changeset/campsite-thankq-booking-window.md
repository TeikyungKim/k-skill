---
"@nomadamas/k-skill": patch
---

Fix `korean-campsite-vacancy` reporting unopened dates as vacancy on the `thankq` and `dzsmart` transports.

땡큐캠핑의 사이트 목록 endpoint(`axResCampSite.hbb`)는 예약창이 열렸는지 알려주지 않는다. 2027년 날짜를 넣어도 `예약가능 68`처럼 총 정원을 그대로 돌려주기 때문에, 자라섬 10/2~10/4 조회가 "사이트 A 68면 여유"로 보고됐다. 실제로는 `res_able_max_dt`가 `20261001`이라 10월 2일부터는 아무도 예약할 수 없었다.

`thankq` 어댑터가 provider당 예약 페이지(`/resv/view.hbb?cseq=`)를 1회 읽어 `res_able_max_dt`와 datepicker 범위를 잡고, 그 밖의 날짜를 `booking_status: not_open`(또는 지난 날짜면 `closed`)으로 표시한 뒤 모든 zone을 `available: false`로 만든다. 마커가 사라지면 날짜를 건드리지 않고 `scope: booking-window` 실패만 남긴다.

같은 결에서 `dzsmart`도 고쳤다. 아직 열리지 않은 달을 요청하면 달력이 통째로 비어 오는데, 예전에는 그 날짜가 결과에서 조용히 빠져 "빈자리 없음"과 구분되지 않았다. 이제 `booking_status: not_open`과 `2026-10 예약 달력이 아직 열리지 않았다` 같은 `status_note`로 남는다.
