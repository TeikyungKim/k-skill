# Provider adapter registry — realty-listing-search

새 포털을 붙일 때 채워야 하는 필드와, 2026-08-30 discovery에서 확인한 사실을
기록한다. 값은 그때 실제로 요청해 본 결과다.

## 어댑터 추가 시 먼저 정할 것

- `provider id` — 예: `zigbang`
- `운영기관` — 실제 운영 주체
- `entrypoint` — 공식 진입 URL
- `transport` — 데이터를 어떻게 얻는가
- `auth` — 필요한 인증/헤더
- `지역 해석` — 지역명을 좌표/코드로 바꾸는 방법
- `매물 조회` — 좌표/코드로 목록을 얻는 방법
- `가격 단위` — 만원인지 원인지
- `실패 모드` — 차단·빈 응답·필수값 누락이 어떤 모양으로 오는가

---

## zigbang (직방)

| 항목 | 값 |
|---|---|
| 운영기관 | 주식회사 직방 |
| entrypoint | `https://www.zigbang.com` |
| API host | `https://apis.zigbang.com` |
| transport | 공개 JSON |
| auth | 없음. `Referer`도 필수는 아니지만 보내고 있다 |
| 가격 단위 | 만원 |

### 호출 순서

```
GET /v2/search?leaseYn=N&q={지역명}&serviceType=원룸
    -> items[].type=="address" 의 lat/lng, _source.법정동코드

geohash5 = geohash(lat, lng, 5)          # helper가 직접 계산

GET /house/property/v1/items/onerooms?geohash={gh}&salesTypes[0]=전세&domain=zigbang
GET /house/property/v1/items/villas?...
GET /house/property/v1/items/officetels?...
    -> {"items":[{"id":..,"lat":..,"lng":..,"userNo":..}]}   # id만 온다

POST /house/property/v1/items/list   body {"itemIds":[...최대 15...]}
    -> {"items":[{item_id, sales_type, deposit, rent, size_m2, 전용면적{m2,p},
                  floor_string, building_floor, title, address1, service_type,
                  reg_date, manage_cost, ...}]}

GET /house/property/v1/items/{id}/detail
```

### 확인된 사실

- 배치 상한 15건. 초과 시 `400 {"message":["itemIds must contain no more than 15 elements"]}`
- 아파트는 이 경로에 없다. 단지 기반 별도 API(`/apt/...`, `/v2/danjis`)라 미지원.
- `www.zigbang.com`의 **HTML 상세 페이지는 스크립트 요청에 403**을 준다.
  API는 열려 있으므로 링크만 제시하고 페이지를 긁지 않는다.
- 폐기된 경로 (모두 404): `/v2/items/oneroom`, `/v2/items?geohash=`,
  `/v2/items/villa`, `/v3/items/oneroom`, `/v2/items/list`

---

## dabang (다방)

| 항목 | 값 |
|---|---|
| 운영기관 | 주식회사 스테이션3 |
| entrypoint | `https://www.dabangapp.com` |
| transport | 웹 JSON |
| auth | 고정 헤더 3종 |
| 가격 단위 | 만원 (표시 문자열 파싱 필요) |

### 필수 헤더

```
D-Api-Version: 5.0.0
D-App-Version: 1
D-Call-Type: web
```

`web.*.js` 번들의 헤더 빌더에서 확인했다. 빠지면 원인을 숨긴 채
`400 일시적으로 서비스가 지연되고 있습니다`가 돌아온다.

### 호출 순서

```
GET /api/v5/loc/search/region?searchKeyword={지역명}
    -> result.list[] {gid, code, name, fullName, location:[lng, lat]}

GET /api/v5/room-list/category/{one-two|officetel|apt}/bbox
    ?bbox={"sw":{"lat":..,"lng":..},"ne":{"lat":..,"lng":..}}
    &filters={...완전한 객체...}&useMap=naver&zoom=15&page=1
    -> result {roomList[], total, hasMore, page}

GET /api/v5/markers/category/{cat}   # 마커 집계. 목록 대신 밀도만 필요할 때
GET /api/v5/room/{id}                # 상세 -- 비로그인 403 (세션 게이트)
```

### filters 필수 키 (카테고리별)

공통: `sellingTypeList`, `depositRange`, `priceRange`, `isIncludeMaintenance`,
`pyeongRange`, `useApprovalDateRange`, `isShortLease`

| 카테고리 | 추가 필수 키 |
|---|---|
| `one-two` | `roomFloorList`, `roomTypeList`, `canParking`, `hasElevator`, `hasPano`, `isDivision`, `isDuplex` |
| `officetel` | `tradeRange`, `roomCountList`, `parkingNumRange`, `canParking`, `hasElevator`, `hasPano` |
| `apt` | `tradeRange`, `roomCountList`, `householdNumRange`, `parkingNumRange`, `hasTakeTenant` |

`sellingTypeList` 값: `LEASE`(전세), `MONTHLY_RENT`(월세), `SELL`(매매).

키가 빠지면 `400`과 함께 `errorDetails`에 누락 키가 한글로 나열된다. 그 목록을
그대로 보고 채우면 된다.

### 확인된 사실

- `location`은 `[lng, lat]` 순서다. 뒤집으면 엉뚱한 지역이 나온다.
- `searchKeyword` 외의 파라미터 이름은 모두 거부된다.
- `roomDesc`는 `"2층, 31.03m², 관리비 없음"` 형태의 표시 문자열이다.
  면적·층을 여기서 파싱한다.
- `priceTitle`은 `"6500"` / `"1000/50"` / `"3억 2,000"` / `"1억5000/3"` 형태다.
- **목록은 열려 있는데 단건 상세만 403이다.** `/api/v5/room/{id}`,
  `/api/v5/room/{id}/detail`, `/api/v5/rooms/{id}` 모두 동일. 로그인 세션이 필요하다.
  헬퍼는 이 경우 `detail_requires_login`으로 보고하고 우회하지 않는다.
- `randomLocation`은 이름 그대로 흔든 좌표다. 역 거리 랭킹까지가 한계다.

---

## naver (네이버페이 부동산) — browser-cdp

| 항목 | 값 |
|---|---|
| entrypoint | `https://new.land.naver.com` |
| transport | **browser-cdp** — 사용자가 연 브라우저에서 읽는다 (없으면 딥링크) |

### 차단 근거 (2026-08-30 측정)

| 경로 | 결과 |
|---|---|
| `new.land.naver.com/api/regions/list` | `429 TOO_MANY_REQUESTS` (첫 요청부터) |
| `new.land.naver.com/api/cortars` | `429` |
| `new.land.naver.com/api/articles/complex/{id}` | `429` |
| `new.land.naver.com/api/complexes/single-markers/2.0` | `429` |
| `m.land.naver.com/cluster/clusterList` | `200` + 본문 `null` |
| `m.land.naver.com/cluster/ajax/complexList` | `200` + `result: []` |
| `m.land.naver.com/map/getRegionList` | 처음엔 JSON, 재요청 시 HTML로 전환 |
| `map.naver.com/p/api/search/allSearch` | `ncaptcha` 응답 |

브라우저 UA·Referer·`sec-fetch-*` 헤더를 모두 붙여도 동일하다. 재시도 간격을
늘려도 마찬가지다. **정상적인 봇 차단이며 우회하지 않는다.**

### 딥링크 형식

```
https://new.land.naver.com/houses?ms={lat},{lng},{zoom}&a={typeCode}&e=RETAIL&tradTp={tradeCode}
https://new.land.naver.com/complexes?ms={lat},{lng},{zoom}&a=APT:PRE:ABYG:JGC&e=RETAIL&tradTp={tradeCode}
```

| 구분 | 코드 |
|---|---|
| 원룸·빌라 | `VL:DDDGG:JWJT` |
| 오피스텔 | `OPST` |
| 아파트 | `APT:PRE:ABYG:JGC` |
| 매매 / 전세 / 월세 | `A1` / `B1` / `B2` |

좌표는 zigbang 또는 dabang의 지역 검색에서 가져온다. 두 지오코더 모두 무인증이라
네이버를 거치지 않고도 정확한 딥링크를 만들 수 있다.

### 브라우저 경로 (2026-08-30 검증)

같은 `/api/*` 경로가 **브라우저 페이지 컨텍스트에서는 200**이다. 차단은 스크립트
HTTP에 걸려 있지 사람이 보는 세션에 걸려 있지 않다.

| 단계 | 확인 결과 |
|---|---|
| `fetch('/api/regions/list?...')` (페이지 컨텍스트) | `200` + 시/도 목록 |
| `fetch('/api/cortars?...')` (페이지 컨텍스트) | `200` + 폴리곤 |
| `/api/articles?...` 를 헤더 없이 재요청 | **`401`** |
| 페이지 자신의 `/api/articles?...` 요청 | `200` + `articleList` 20건 |

`/api/articles`만 `Authorization: Bearer <JWT 159자>`를 요구한다. SPA가 자기
요청에 붙이는 값이며, 헬퍼는 그 값을 관찰해서 페이징에만 재사용한다.

**주의**: SPA는 자기 요청에 `tradeType=`을 비워 보낸다(거래유형이 클라이언트
상태에 있음). 그 URL을 그대로 재생하면 매매·전세·월세가 섞인다. 헬퍼는
`tradeType`을 명시적으로 채워 넣는다.

articleList 주요 필드: `articleNo`, `articleName`, `tradeTypeName`,
`dealOrWarrantPrc`(문자열 "6억 5,000"), `rentPrc`, `area1`(공급)/`area2`(전용),
`floorInfo`("6/16"), `articleConfirmYmd`, `buildingName`, `realtorName`,
`latitude`/`longitude`(**흔들지 않은 실제 좌표**), `isSafeLessorOfHug`, `tagList`.

### 스크립트 HTTP가 풀렸는지 다시 볼 때

`GET https://new.land.naver.com/api/regions/list?cortarNo=0000000000` 한 번이면
충분하다. `429`가 아니라 시/도 목록 JSON이 오면 브라우저 없이도 되는 것이다.
