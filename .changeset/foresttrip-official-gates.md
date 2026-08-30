---
"@nomadamas/k-skill": patch
---

Fix `foresttrip-vacancy` reporting rooms the official screen never offers, and add `--nights` for honest multi-night lookups.

월별예약조회 API는 실제로 팔지 않는 상품에도 `rsrvtAvail=Y` / `rsrvtCnt=0` 행을 준다. 가리산자연휴양림 야영장은 이런 행이 102건 오지만 공식 화면은 아무것도 그리지 않는다 — 판매 상품 목록이 0건이기 때문이다. 그래서 "데크 34면 예약 가능"이라는 잘못된 결과가 나왔다.

이제 조회 결과가 있는 휴양림에 한해 두 가지 공식 관문을 통과시킨다.

- `selectRsrvtGoodsListForMonthRsrvtSmpl.do`의 `rsrvtGoodsList`에 없는 `goodsId`는 제외한다. 공식 화면이 그리기 전에 적용하는 것과 같은 조건이다.
- `selectSthngListForMonthRsrvt.do`의 예약 정책(`weekLastDay`/`monthLastDay`, `gnrlRsrvtTrnseDtm`)으로 휴양림별 예약가능기간을 구해 그 뒤 날짜를 제외한다.

관문 조회가 실패하면 행을 지우지 않고 `goods:` / `window:` 접두사가 붙은 failure로 보고한다. 없는 데이터로 조용히 결과를 줄이지 않기 위해서다.

새 `--nights N`은 같은 객실이 N일 연속 비어 있는 건만 남기고, 휴양림의 최대 숙박일수(`mxmmStngDayCnt`)보다 긴 요청은 제외한다. 날짜별 잔여를 교집합하는 것만으로는 부족하다 — 금원산 야영데크는 3일 모두 비어 있어도 최대 2박이라 3박 신청이 `휴양림의 최대 숙박일수를 초과하여 신청하셨습니다`로 거부된다.
