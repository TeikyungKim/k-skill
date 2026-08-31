# Realty Listing Search

## What this skill does

한국 부동산 포털의 **매물(호가) 목록을 지역 기준으로 통합 조회**한다.

포털마다 공개 표면이 달라서 이 스킬은 **provider adapter 레지스트리**를 둔다.
`korean-campsite-vacancy`의 provider adapter, `delivery-tracking`의 carrier
adapter와 같은 구조다.

| provider | 이름 | transport | 인증 | 지원 매물 |
|---|---|---|---|---|
| `zigbang` | 직방 | `apis.zigbang.com` 공개 JSON | 없음 | 원룸·빌라·오피스텔 |
| `dabang` | 다방 | `www.dabangapp.com` 웹 JSON | 없음 (고정 `D-*` 헤더 필요) | 원룸·빌라·오피스텔·아파트 |
| `naver` | 네이버페이 부동산 | **browser-cdp** (fallback: link-only) | 사용자가 연 브라우저 세션 | 원룸·빌라·오피스텔·아파트 |

조회 전용이다. 로그인, 중개사 문의, 찜, 방문예약, 계약은 하지 않는다.

## When to use

- "신흥동 전세 2억 이하 매물 찾아줘"
- "직방이랑 다방에서 문정동 월세 원룸 비교해줘"
- "성남 태평동 빌라 전세 어떤 게 나와 있어?"
- "네이버부동산에서 같은 조건으로 볼 수 있는 링크 만들어줘"

## When not to use

- **실거래가**가 필요한 경우 → `real-estate-search` (국토교통부 신고 데이터)
- 당근부동산 매물 → `daangn-realty-search`
- 공시가격 → `housing-official-price`, `gongsijiga-search`
- LH·SH 청약 공고 → `lh-notice-search`, `sh-notice-search`
- 중개사무소 연락처·영업시간 조회 (이 스킬은 매물만 다룬다)
- 로그인·문의·계약처럼 상대방 계정에 영향을 주는 작업

## Prerequisites

- Python 3.9+, 인터넷 연결
- 표준 라이브러리만 사용한다. API 키·계정·브라우저 모두 불필요하다.

## Commands

```bash
# 어댑터 레지스트리 확인
npx -y @nomadamas/k-skill@0 exec realty-listing-search scripts/run_realty_listing_search.py -- providers

# 기본 검색 (전세, 원룸+빌라, 직방+다방)
npx -y @nomadamas/k-skill@0 exec realty-listing-search scripts/run_realty_listing_search.py -- \
  search --region 신흥동 --prefer 성남 --deposit-max 20000

# 거래유형·매물종류·provider 지정
... search --region 문정동 --trade-type 월세 --property-type 원룸,오피스텔 --rent-max 80

# 네이버 딥링크까지 함께
... search --region 태평동 --prefer 성남 --provider zigbang,dabang,naver

# 상세
... detail --provider zigbang --id 49974607
... detail --provider dabang --id 6a8cf11efcb1045b50d9261b
```

### search 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--region` | (필수) | 동/지역명 |
| `--prefer` | — | 동명이인 좁히기 힌트 (예: `성남`) |
| `--trade-type` | `전세` | `전세\|월세\|매매` 콤마 구분 |
| `--property-type` | `원룸,빌라` | `원룸\|빌라\|오피스텔\|아파트` 콤마 구분 |
| `--deposit-max` / `--deposit-min` | — | 보증금·전세금 만원 |
| `--rent-max` | — | 월세 만원 |
| `--area-min-m2` | — | 전용면적 하한 |
| `--provider` | `zigbang,dabang` | 사용할 어댑터 |
| `--limit` | 30 | 출력 매물 수 |
| `--radius-km` | 1.5 | 다방 bbox 반경 |
| `--pages` | 2 | 다방 페이지 수 |
| `--geohash-precision` | 5 | 직방 geohash 자릿수 |
| `--naver-browser` | 꺼짐 | 네이버를 브라우저(CDP)로 실제 조회 |
| `--node-bin` | `node` | `naver_cdp.js` 실행용 node |
| `--naver-timeout` | 120 | 네이버 브라우저 조회 타임아웃(초) |

**동명이 여럿이면 `--prefer`를 반드시 넣는다.** `신흥동`만 주면 창원·대전·인천
후보가 함께 나오고 첫 후보가 선택된다. 응답의 `region.full_name`과
`region_candidates`로 어느 지역이 잡혔는지 항상 확인한다.

## Data surfaces (검증 완료)

### zigbang

1. 지역 → 좌표: `GET https://apis.zigbang.com/v2/search?leaseYn=N&q=<지역명>&serviceType=원룸`
   - `items[].type == "address"` 인 항목의 `lat`/`lng`, `_source.법정동코드`
2. 좌표 → geohash(5) — helper가 표준 라이브러리로 직접 계산한다 (의존성 없음)
3. geohash → 매물 id:
   `GET /house/property/v1/items/{onerooms|villas|officetels}?geohash=<gh>&salesTypes[0]=전세&domain=zigbang`
4. id → 요약: `POST /house/property/v1/items/list` body `{"itemIds":[...]}`
   - **한 번에 15건까지.** 초과하면 `400 itemIds must contain no more than 15 elements`
5. 단건 상세: `GET /house/property/v1/items/{id}/detail`

가격 단위는 **만원** (`deposit`, `rent`). `전용면적.m2`를 면적 기준으로 쓴다.

> 구버전 경로 `/v2/items/oneroom`, `/v2/items?geohash=` 는 모두 404다. 쓰지 않는다.

### dabang

모든 요청에 아래 헤더가 **필수**다. 빠지면 `400 일시적으로 서비스가 지연되고 있습니다`
라는 일반 메시지가 돌아와 원인을 오해하기 쉽다.

```
D-Api-Version: 5.0.0
D-App-Version: 1
D-Call-Type: web
```

1. 지역 검색: `GET /api/v5/loc/search/region?searchKeyword=<지역명>`
   - 파라미터 이름은 반드시 `searchKeyword`다. `query`/`q`/`keyword`는 모두
     `400 키워드를 입력하세요`
   - 응답 `result.list[].location` 은 `[lng, lat]` 순서다
2. 매물 목록: `GET /api/v5/room-list/category/{one-two|officetel|apt}/bbox`
   - `bbox`(JSON), `filters`(JSON), `useMap=naver`, `zoom`, `page`
   - **`filters`는 완전한 객체여야 한다.** 키가 하나라도 빠지면 400과 함께
     누락 키 목록이 `errorDetails`로 돌아온다. 카테고리마다 필수 키가 다르며
     helper의 `dabang_filters()`가 카테고리별 기본값을 갖고 있다
3. 단건 상세: `GET /api/v5/room/{id}` — **비로그인은 403이다.** 다방은 단건
   상세만 세션으로 막아 뒀다. 목록 필드로 대체하거나 링크를 브라우저로 연다.
   우회하지 않는다.

`priceTitle`은 표시용 문자열(`"6500"`, `"1000/50"`, `"3억 2,000"`)이라
helper가 만원 단위 숫자로 파싱한다. 면적·층은 `roomDesc`에서 뽑는다.

### naver — 브라우저 세션으로 읽는다

`new.land.naver.com/api/*` 는 **스크립트 HTTP로는 첫 요청부터 모든 경로가**
`429 TOO_MANY_REQUESTS`다. `m.land.naver.com`의 지역 API는 열려 있지만
매물 API(`clusterList`/`articleList`)는 `200`에 본문 `null`이다. 봇 차단이다.

**차단을 우회하지 않는다.** 대신 사용자가 이미 연 브라우저를 쓴다. `--naver-browser`를
주면 `scripts/naver_cdp.js`가 documented CDP endpoint에 붙어서:

1. `new.land.naver.com/houses?ms=<lat>,<lng>,<zoom>&a=<타입>&e=RETAIL&tradTp=<거래>` 로 이동
2. SPA가 스스로 보내는 `/api/articles?...` 요청을 관찰해 URL 템플릿과
   `Authorization: Bearer <JWT>` 헤더를 확보
3. 그 세션의 헤더로 `tradeType=`을 채워 1~N 페이지를 읽는다
   (SPA는 거래유형을 클라이언트 상태로 들고 있어 자기 요청엔 `tradeType=`이 비어 있다)
4. 실패하면 페이지가 이미 받은 응답 본문(`Network.getResponseBody`)으로 폴백

토큰은 만들어내거나 저장하지 않는다. 화면에 열려 있는 그 세션의 것을 그대로 쓴다.
브라우저가 없으면 조회를 건너뛰고 딥링크만 만든다.

```bash
# 사용자가 먼저 띄워야 한다
chrome.exe --remote-debugging-port=9222 --user-data-dir=<임시경로>
```

`KSKILL_CHROME_CDP_URL`(기본 `http://127.0.0.1:9222`)로 엔드포인트를 바꾼다.

응답 필드는 다른 두 포털보다 풍부하다 — `articleConfirmYmd`(확인일자),
`realtorName`(중개사), `buildingName`(건물명), `isSafeLessorOfHug`,
그리고 **흔들지 않은 실제 좌표**.

딥링크는 브라우저 사용 여부와 무관하게 항상 함께 낸다.

```
https://new.land.naver.com/houses?ms=<lat>,<lng>,<zoom>&a=VL:DDDGG:JWJT&e=RETAIL&tradTp=B1
https://new.land.naver.com/complexes?ms=<lat>,<lng>,<zoom>&a=APT:PRE:ABYG:JGC&e=RETAIL&tradTp=B1
```

거래유형 코드: 매매 `A1`, 전세 `B1`, 월세 `B2`.

## Response policy

- 결과는 전부 **호가**다. 실거래가와 섞어 말하지 않는다. 실거래가 필요하면
  `real-estate-search`를 함께 돌린다.
- `region.full_name`을 반드시 함께 보고해 어느 동이 잡혔는지 드러낸다.
- provider별 건수와 `sources`를 남긴다. 한쪽이 0건이면 그 사실을 말한다.
- `errors`가 비어있지 않으면 부분 실패로 보고한다. 조용히 넘기지 않는다.
- 매물 링크는 그대로 제시한다. 직방 HTML 상세 페이지는 스크립트 요청에
  `403`을 주지만 사용자가 브라우저로 열면 정상이다.

## Done when

- 지역이 좌표로 해석됐고 어느 행정구역인지 응답에 남았다.
- 요청한 provider마다 조회를 시도했고 건수·출처를 보고했다.
- 매물이 보증금 오름차순으로 정규화되어 링크와 함께 나왔다.
- naver를 요청했다면 딥링크를 만들고 스크래핑하지 않았다는 사실을 밝혔다.

## Failure modes

- `region_not_resolved` — 지역명 해석 실패. `--prefer`로 시/구를 좁힌다.
- 엉뚱한 동이 잡힘 — 동명이인. `region_candidates`를 보고 `--prefer` 재지정.
- `zigbang detail: HTTP Error 400` — 배치 15건 초과. helper는 이미 15건씩
  나눠 보내므로, 이 오류가 보이면 상한이 또 바뀐 것이다.
- `dabang ...: HTTP Error 400` — `filters` 필수 키 누락. 응답의 `errorDetails`가
  빠진 키를 알려준다. 카테고리 기본값에 그 키를 추가한다.
- naver 429 / 빈 응답 — 스크립트 HTTP의 정상적인 차단 상태다. 우회하지 말고
  `--naver-browser`를 쓰거나 딥링크로 답한다.
- `browser_not_reachable` — CDP 브라우저가 없다. 사용자가 직접 띄워야 한다.
- `no_article_request_observed` — 지도가 렌더되기 전에 타임아웃했거나 그 위치에
  매물이 없다. `--naver-timeout`을 늘리거나 좌표를 확인한다.
- `trade_type_filter_not_applied` (notes) — 필터 주입에 실패해 페이지 응답을 그대로
  읽었다는 뜻이다. 결과에 매매·월세가 섞여 있을 수 있으니 후처리로 걸러야 한다.
- 특정 동에 매물이 0건 — 실제로 없는 경우가 많다. `--radius-km`를 키우거나
  인접 동으로 다시 조회한다.
- `detail_requires_login` (다방 403) — 정상이다. 다방 단건 상세는 로그인 전용이라
  `search` 결과의 필드와 링크로 대신한다.
- `--prefer`가 엉뚱하게 걸림 — 부분 문자열 매칭이다. `--prefer 성남`은 "강원특별자치도
  강릉시 **성남**동"에도 걸린다. 애매하면 `--prefer "성남시 중원구"`처럼 길게 준다.

## Notes

- 가격 단위는 전 provider 공통 **만원** (`deposit_manwon`, `rent_manwon`).
- `lat`/`lng`는 두 포털 모두 **의도적으로 흔든 좌표**(약 100m)다. 역 거리 랭킹에는 쓸 수 있지만 정확한 주소로 쓰면 안 된다.
- 평 = m² / 3.305785.
- 직방 geohash 5자리는 약 5km × 5km라 인접 동 매물이 함께 잡힌다. 결과의
  `address`로 반드시 확인한다.
- 다방 `bbox`는 `--radius-km` 기준 사각형이라 직방보다 범위가 좁다. 두 provider의
  건수가 다른 건 정상이다.
