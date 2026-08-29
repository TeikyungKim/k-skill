# KAMIS 농수축산물 가격 조회 가이드

`kamis-food-price`는 한국농수산식품유통공사 KAMIS의
`dailyPriceByCategoryList`를 `k-skill-proxy` 경유로 조회한다.

- 도매/소매 구분
- 식량작물·채소류·특용작물·과일류·축산물·수산물 부류
- 지역 코드와 조사일
- 조회일·전일·1주일·1개월·1년·평년 가격 비교

일반 사용자는 KAMIS API 키를 입력하지 않는다. hosted proxy 운영자만
`KAMIS_API_KEY`를 서버 환경에 보관한다.

```bash
npx -y @nomadamas/k-skill@0 exec kamis-food-price scripts/run_kamis.py -- \
  --product-class 01 --category 200 --county 1101 --text
```

공식 출처: https://www.kamis.or.kr/customer/reference/openapi_list.do?action=detail&boardno=1

