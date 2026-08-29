# 외교부 해외안전·여행경보 조회 가이드

`mofa-travel-safety`는 외교부
`국가·지역별 여행경보 목록 조회(0404 대륙정보)`를
`k-skill-proxy` 경유로 조회한다.

- 한글 국가명 또는 ISO 2자리 국가코드
- 공식 경보 단계와 지역 유형
- 경보 내용·작성일·0404 지도 링크

이 스킬은 자체적인 안전 점수나 여행 허가 판단을 만들지 않고, 외교부
공식 필드와 원문 링크를 요약한다.

```bash
npx -y @nomadamas/k-skill@0 exec mofa-travel-safety scripts/run_mofa_travel_safety.py -- \
  --country-iso RU --text
```

공식 출처: https://www.data.go.kr/data/15095500/openapi.do

