# 서울 기상 위험 시간대 조회 가이드

`seoul-weather-risk`는 서울 **행정동 이름**으로 장소를 찾고, 해당 장소의 폭염·한파·호우·대설·강풍 **위험 후보 시간대**를 조회하는 읽기 전용 스킬입니다.

> 이 결과는 예보값을 기준으로 만든 참고 정보이며, **기상청 공식 특보를 대체하지 않습니다.** 외출·운영·안전 판단에는 공식 기상청 발표를 함께 확인하세요.

## 이 기능으로 할 수 있는 일

- 서울 행정동 이름으로 장소별 기상 위험 예상 시간대를 조회합니다.
- 폭염·한파·호우·대설·강풍 후보와 예보 시각(`forecast_at`)을 확인합니다.
- 동명이명 행정동은 자치구(`--gu`)를 지정해 정확한 장소로 좁힐 수 있습니다.
- 제품 게시 상태, 공개 컬럼, 페이지별 행 수와 게시 버전(`publication_id`)을 함께 확인합니다.

이 스킬은 ASK 서울 Marketplace의 `weather_place_risk_window` **단일 제품**만 읽습니다. 조회 결과가 없거나 제품이 준비되지 않았을 때 임의의 예시·fixture 데이터를 대신 반환하지 않습니다.

## 먼저 필요한 것

- 인터넷 연결
- Node.js와 `npx`
- [공통 설치 가이드](../install.md) 및 [보안/시크릿 정책](../security-and-secrets.md) 확인

사용자 API Key는 필요하지 않습니다. 기본 hosted proxy가 ASK 서울 API 인증을 대신하므로, 일반 사용자는 별도 키를 발급받거나 secrets 파일을 만들지 않아도 됩니다.

## 설치

전체 스킬을 이미 설치했다면 이 단계는 건너뛰어도 됩니다.

```bash
npx --yes skills add NomaDamas/k-skill --skill seoul-weather-risk -g
```

## 필요한 환경변수

- 없음. `KSKILL_PROXY_BASE_URL`은 self-host 또는 별도 proxy를 사용할 때만 설정하는 선택 항목입니다.
- 환경변수를 비워 두면 기본 hosted `https://k-skill-proxy.nomadamas.org`를 사용합니다.

ASK 서울 전용 서비스 키와 upstream origin은 proxy 운영 환경에서만 관리합니다. 사용자 환경변수, URL, 명령행 인수, 문서, 로그에는 넣지 않습니다.

## 기본 경로

기본적으로 다음 세 read-only route를 proxy가 중계합니다.

- bundle: `GET /v1/ask-seoul/weather-risk/bundle`
- product metadata: `GET /v1/ask-seoul/weather-risk/product`
- data page: `GET /v1/ask-seoul/weather-risk/data`

사용자는 이 route를 직접 조합하기보다 아래 CLI 흐름을 사용하는 것을 권장합니다. proxy 운영·self-host가 필요한 경우에는 [k-skill 프록시 서버 가이드](k-skill-proxy.md)를 참고하세요.

## 입력값

| 입력 | 설명 |
| --- | --- |
| `--admin-dong` | 서울 행정동 이름. 내부 `place_id`를 몰라도 됨 |
| `--gu` | 동명이명 해소용 자치구. `--admin-dong`과 함께 사용 |
| `--from` / `--to` | KST 기준 조회 범위. 날짜만 입력하면 하루의 시작·끝 시각으로 확장 |
| `--limit` | 페이지 행 수, `1`~`500`, 기본값 `100` |
| `--cursor` | 같은 `publication_id`의 다음 페이지를 조회할 때 사용 |
| `--filter` | `column=value` 형식의 공개 컬럼 필터 |

`--product-id`는 항상 `weather_place_risk_window`를 사용합니다. `--admin-dong`과 `--filter place_id=...`는 동시에 사용할 수 없습니다.

## 기본 흐름

스킬을 설치한 뒤에는 자연어로 다음처럼 요청하면 됩니다.

> 잠실본동의 이번 주 기상 위험 시간대와 각 위험 판정의 근거를 알려줘.

일반적인 오늘 위험 시간대 질문은 아래 fast path를 한 번만 실행합니다. bundled 행정동 매핑과 날짜·limit 검증은 유지하면서 hosted data route만 호출하므로 bundle·product metadata 왕복을 생략합니다.

```bash
npx -y @nomadamas/k-skill@0 exec seoul-weather-risk scripts/seoul_weather_risk.py -- query --fast \
  --product-id weather_place_risk_window \
  --admin-dong 잠실본동 \
  --from 2026-08-12 \
  --to 2026-08-12 \
  --limit 100
```

`--fast`에서는 `--filter` 대신 `--admin-dong`, `--gu`, 날짜, `--limit`, `--cursor`를 사용합니다. `product_not_ready` 또는 계약 오류가 나오면 fixture로 대체하지 말고 게시 계약 진단을 수행합니다.

`--from`과 `--to`에 날짜만 넣으면 그날 시작·끝 시각으로 확장됩니다. ASK 서울이 그 구간을 현재 serving window 밖이라고 거절하면 helper가 요청 구간과 제공 가능 window의 교집합으로 한 번 재시도합니다. 오늘 0시부터 조회해도 오후 예보 window만 열려 있으면 그 교집합만 조회하며, 없는 시간대를 임의로 채우지 않습니다.

## 게시 계약 진단

아래 단계는 일반 질문마다 실행하지 않고, fast path 오류나 게시 상태 점검이 필요할 때만 실행합니다.

### 1. 연결·실행 모드 확인

```bash
npx -y @nomadamas/k-skill@0 exec seoul-weather-risk scripts/seoul_weather_risk.py -- preflight
```

기본 결과의 `mode`는 `hosted_proxy`입니다. `live_network`가 `false`인 것은 preflight가 네트워크를 호출하지 않는다는 뜻이지, 데이터가 준비됐다는 뜻은 아닙니다.

### 2. 제품 게시 상태 확인

```bash
npx -y @nomadamas/k-skill@0 exec seoul-weather-risk scripts/seoul_weather_risk.py -- catalog
```

응답에서 다음을 먼저 확인합니다.

| 필드 | 의미 |
| --- | --- |
| `registration_ready` | bundle을 현재 조회에 사용할 수 있는지 여부 |
| `products` | `weather_place_risk_window` 단일 제품이 포함되어 있는지 |
| `blockers` | 아직 해결되지 않은 게시 차단 사유 |
| `publication_id` | 현재 게시 버전을 식별하는 값 |

`registration_ready`가 `false`이거나 `blockers`가 남아 있으면 조회 성공으로 간주하지 말고, 게시 상태를 먼저 확인해야 합니다.

### 3. 제품 컬럼과 시간축 확인

```bash
npx -y @nomadamas/k-skill@0 exec seoul-weather-risk scripts/seoul_weather_risk.py -- describe \
  --product-id weather_place_risk_window
```

제품의 기본 단위(grain)는 `place_id`와 `forecast_at` 조합입니다. `describe` 응답의 `metadata.columns`에서 실제 공개 컬럼을 확인한 뒤 필요한 필터만 사용하세요.

### 4. full-contract 행정동 조회

```bash
npx -y @nomadamas/k-skill@0 exec seoul-weather-risk scripts/seoul_weather_risk.py -- query \
  --product-id weather_place_risk_window \
  --admin-dong 잠실본동 \
  --from 2026-08-11 \
  --to 2026-08-17 \
  --limit 100
```

`--filter`가 필요하면 `--fast`를 빼고 이 full-contract 경로를 사용합니다. data 응답의 `publication_id`, `row_count`, `rows`, `has_more`, `next_cursor`를 확인하고 다음 page에는 같은 publication의 cursor만 재사용합니다.

`--from`과 `--to`에 날짜만 넣으면 KST 기준으로 각각 `00:00:00`, `23:59:59`로 확장됩니다. 특정 시각이 필요하면 `2026-08-11 09:00:00`처럼 명시하세요. 확장한 하루가 현재 제공 window보다 앞이면 helper가 겹치는 구간으로 다시 조회합니다.

## 행정동 입력 규칙

스킬은 입력한 행정동을 로컬 reference에서 결정적으로 `place_id`로 바꾼 뒤, proxy에는 `place_id`만 전달합니다.

| 상황 | 동작 | 예시 |
| --- | --- | --- |
| 공식 행정동명 | 정확히 일치하는 항목 사용 | `잠실본동` |
| 허용된 표기 차이 | 숫자 앞 `제` 생략, 숫자 구분점 `.`·`·`·생략 허용 | `성수2가제3동` → `성수2가3동` |
| 자치구가 필요한 동명이명 | `--gu`로 자치구를 함께 지정 | `신사동 --gu 강남구` |
| 오타·생활권·부분 이름 | 추측하지 않고 오류 반환 | `성수동` |

동명이명은 임의로 선택하지 않습니다. 예를 들어 `신사동`은 강남구와 관악구에 모두 있으므로 아래처럼 자치구를 함께 입력해야 합니다.

```bash
npx -y @nomadamas/k-skill@0 exec seoul-weather-risk scripts/seoul_weather_risk.py -- query \
  --product-id weather_place_risk_window \
  --admin-dong 신사동 \
  --gu 강남구 \
  --limit 100
```

지원하지 않는 이름을 억지로 보정하지 않는 것은 잘못된 장소의 기상 정보를 보여주는 것을 막기 위한 안전장치입니다.

`--admin-dong`을 사용하지 않는 기존 자동화는 다음처럼 `place_id`를 직접 필터링할 수 있습니다.

```bash
npx -y @nomadamas/k-skill@0 exec seoul-weather-risk scripts/seoul_weather_risk.py -- query \
  --product-id weather_place_risk_window \
  --filter place_id=seoul_admd_1171065000 \
  --from 2026-08-11 \
  --to 2026-08-17 \
  --limit 100
```

## 응답 읽는 법

데이터 응답은 한 페이지 단위 JSON입니다.

| 필드 | 확인할 내용 |
| --- | --- |
| `publication_id` | 조회한 행이 어느 게시 버전에 속하는지. 페이지를 이어갈 때 같은 값인지 확인 |
| `row_count` | 이번 응답의 실제 행 수. `rows` 길이와 일치해야 함 |
| `rows` | `place_id`, `forecast_at`, `risk_labels` 등 공개 컬럼을 가진 행 목록 |
| `has_more` | 다음 페이지가 있는지 여부 |
| `next_cursor` | `has_more=true`일 때 다음 요청에 사용할 cursor |
| `forecast_at` | 위험 후보가 예상되는 예보 시각. 이 제품의 시간축 |
| `risk_labels` | 폭염·한파·호우·대설·강풍 등 위험 후보 라벨 |

여러 페이지를 조회할 때는 **같은 `publication_id`의 `next_cursor`만** 재사용합니다. 게시 버전이 바뀌어 `409 cursor_expired`가 나오면 cursor를 계속 재시도하지 말고 첫 페이지부터 다시 조회하세요.

## 오류가 나면

| 오류 코드 | 의미 | 대응 |
| --- | --- | --- |
| `unknown_admin_dong` | reference에 없는 행정동·자치구 | 공식 행정동명을 다시 입력 |
| `ambiguous_admin_dong` | 동명이명이라 자치구가 필요함 | `--gu`를 추가 |
| `conflicting_location_input` | `--admin-dong`과 `place_id` 필터를 동시에 사용함 | 둘 중 하나만 사용 |
| `invalid_limit` | `--limit`이 1~500 범위를 벗어남 | 범위 안의 값으로 재시도 |
| `product_not_ready` (503) | 제품이 아직 게시 준비되지 않음 | `catalog`의 `registration_ready`와 `blockers` 확인 |
| `rate_limited` (429) | 호출 한도 초과 | 응답의 `Retry-After`를 따르고 재시도 |
| `cursor_expired` (409) | publication이 바뀌어 cursor가 만료됨 | 첫 페이지부터 새로 조회 |
| `query_window_unavailable` (422) | 요청 기간이 현재 제공 가능한 예보 window와 겹치지 않음 | 응답의 `available_from_at`/`available_to_at` 범위로 다시 조회. 겹치면 helper가 이미 재시도함 |
| `response_contract_invalid` | API 응답 계약 또는 단일 제품 계약이 바뀜 | 성공 데이터로 처리하지 말고 운영자에게 신고 |
| `network_error` | proxy 연결 실패 | 네트워크와 `KSKILL_PROXY_BASE_URL` 설정 확인 |

`401`, `403`, `503` 또는 네트워크 오류가 발생했을 때 fixture·예시·추정값을 실제 결과처럼 사용하지 않습니다.

## 인증과 보안

### 일반 사용자: 별도 API Key 없음

기본 hosted proxy 경로에서는 사용자 `Authorization` 헤더나 ASK 서울 API Key를 사용하지 않습니다. 사용자는 `KSKILL_PROXY_BASE_URL`을 설정하지 않아도 기본 hosted proxy를 사용합니다.

### self-host proxy 설정

별도 proxy를 사용할 때만 `KSKILL_PROXY_BASE_URL`에 **HTTPS origin**을 설정합니다. helper는 현재 작업 디렉터리의 `.env`나 사용자 Marketplace API key를 읽지 않으며, hosted proxy 운영용 ASK 서울 전용 서비스 키는 proxy 서버 환경에서만 관리됩니다.

## 주의할 점

- 기상청 공식 특보를 발령하거나 대체하는 판단
- 행정동을 좌표·생활권·통칭으로 추정하는 검색
- 임의의 SQL, 테이블명, 조인, 집계, 정렬 실행
- 제품이 준비되지 않았을 때 임의의 fixture·synthetic 데이터 반환
- bundle에 포함되지 않은 다른 제품 조회

## 공식 출처와 추가 문서

- ASK 서울 데이터 상품·게시 상태: [ASK 서울 Marketplace](https://ask-seoul.kr)
- 공공 데이터 출처 목록: [Sources](../sources.md)
- 공통 설치: [공통 설치 가이드](../install.md)
- 보안 및 시크릿 정책: [보안/시크릿 정책](../security-and-secrets.md)
- proxy 운영자용 route·서비스 키 정책: [k-skill 프록시 서버 가이드](k-skill-proxy.md)
- 스킬의 상세 실행 계약: [`seoul-weather-risk/instruction.md`](../../seoul-weather-risk/instruction.md)

## 사용 전 체크리스트

- [ ] 일반 사용자 조회는 `query --fast` 한 번만 실행했다.
- [ ] fast path가 실패했거나 게시 계약·준비 상태를 명시적으로 점검할 때만 `preflight`, `catalog`, `describe` 진단을 순서대로 실행했다.
- [ ] 진단이 필요한 경우 `catalog`에서 `registration_ready=true`와 빈 `blockers`를 확인하고, `describe`에서 제품 컬럼과 `forecast_at` 시간축을 확인했다.
- [ ] 행정동이 모호하면 `--gu`를 지정했다.
- [ ] 조회 결과의 `publication_id`, `row_count`, `forecast_at`, `risk_labels`를 확인했다.
- [ ] 공식 특보가 아닌 예보 기반 참고 정보라는 점을 사용자에게 알렸다.
- [ ] 오류 응답을 성공 데이터나 추정값으로 바꾸지 않았다.
