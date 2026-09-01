# campsite-recommend — assembled instructions

Runtime mode: dolshoi (CloakBrowser available)

## Runtime rules

- Detect capabilities, not product names. Dolshoi credential mode is active only when `DOLSHOI_ACTION_BROKER_URL` is set and `vault-run` is available; CloakBrowser mode is active when the built-in browser tool identifies CloakBrowser or `CLOAKBROWSER_PEEK_TOKEN` is set.
- When the user asks for an action and the official surface supports it lawfully, continue beyond lookup through reversible preparation and execution. Do not declare completion at a result list, deep link, or handoff when the action can still be carried out.
- Immediately before an irreversible external side effect such as payment, message/email delivery, final submission, cancellation, account mutation, or public posting, call `clarify` with the exact target, amount/payload, and effect. Execute only after approval; do not ask again for already-approved reversible steps.
- Preserve hard boundaries for law, required physical presence, CAPTCHA, identity proofing, electronic signatures, and unsupported official surfaces. In those cases, complete the furthest lawful supported step and open or prepare the exact next official step for the user.
- Plain lookups go through the hosted `k-skill-proxy` (`https://k-skill-proxy.nomadamas.org`) by default; no user API key is needed. Set `KSKILL_PROXY_BASE_URL` only for a self-hosted or alternate proxy. Direct upstream calls require the skill-documented API key.
- This skill is lookup-oriented. Completion means the requested data is retrieved, summarized with its source (table/endpoint, period, unit), and any requested follow-up action is connected to the official surface that supports it.

## Bundled asset access

- Execute bundled helpers only through `npx -y @nomadamas/k-skill@0 exec campsite-recommend scripts/<file> -- <args>`; do not assume a repository-relative or installed-skill-relative path.
- Resolve an asset path with `npx -y @nomadamas/k-skill@0 path campsite-recommend <relative-path>` only when another tool explicitly requires a filesystem path.
- Read bundled references through `npx -y @nomadamas/k-skill@0 read campsite-recommend references/<file>`.

# Campsite Recommend

## What this skill does

`foresttrip-vacancy`(숲나들e 자연휴양림)와 `korean-campsite-vacancy`(지자체·공공 캠핑장)의
조회 결과 JSON을 받아 **추천 순위로 정렬**한다.

- 순위 근거는 카카오맵 공개 평점·평가수·리뷰수다. 산식(베이지안 보정 평점 70% +
  로그 정규화 리뷰 규모 30%)과 동결 상수는 `npx -y @nomadamas/k-skill@0 read campsite-recommend references/SCORING.md`에 있다.
- 시설 ↔ 카카오 place id 연결은 **큐레이션된 매핑**(`npx -y @nomadamas/k-skill@0 read campsite-recommend references/place-map.json`)만 쓴다.
  자동 이름 검색 매칭은 하지 않는다(2026-08-29 여수 봉황산에 충주 봉황휴양림 평점이
  붙은 오매핑 사고가 계기). 매핑에 없는 시설은 순위를 추측하지 않고 `unranked`로
  분리해 가용 사이트 수 순으로 보고한다.
- `--origin`을 주면 k-skill-proxy의 Kakao Mobility route로 시설별 자동차
  거리·소요시간·통행료를 붙인다.

조회 전용이다. 예약·결제·리뷰 작성은 하지 않는다.

## When to use

- "연박 가능한 캠핑장을 추천순으로 정렬해줘"
- "이 조회 결과에서 평점 좋은 순으로 알려줘"
- "집에서 가까운 거리·통행료까지 붙여서 순위 매겨줘"
- vacancy 스킬 결과를 노션/문서에 순위표로 저장하기 전 정렬 단계

## When not to use

- 빈자리 조회 자체 → `foresttrip-vacancy` / `korean-campsite-vacancy`
- 매핑에 없는 시설의 순위 추측 → 하지 않는다. 매핑 추가가 먼저다
- 카카오맵 리뷰 대량 수집·인덱싱 → 입력에 등장한 시설만 1회씩 조회한다

## Prerequisites

- Python 3.9+ (표준 라이브러리만 사용, 추가 dependency 없음)
- optional: `KSKILL_PROXY_BASE_URL` (self-host proxy 사용 시. 비우면 hosted
  `https://k-skill-proxy.nomadamas.org` 기본. `--origin` 거리 계산에만 필요)

```bash
npx -y @nomadamas/k-skill@0 exec campsite-recommend scripts/run_campsite_recommend.py -- --check-deps
```

## Required environment variables

없음. 카카오 평점은 공개 place 페이지 데이터라 키가 필요 없고, 거리 계산의
Kakao Mobility 키는 proxy 서버에만 있다.

## Data path (site-dependent knowledge)

- **평점**: `GET https://place-api.map.kakao.com/places/panel3/{place_id}` —
  place.map.kakao.com 프런트가 쓰는 공개 JSON. 키는 없지만 **브라우저형 헤더
  세트가 없으면 406**을 준다(`pf: web` + `Accept` + `Origin`/`Referer` +
  `sec-fetch-*`; helper에 하드코딩됨. placePrint 번들 분석으로 확인, 2026-09-01).
  읽는 필드: `kakaomap_review.score_set.average_score`(평점) /
  `.review_count`(평가수), `blog_review.review_count`(리뷰수),
  `summary.point`(WGS84 좌표), `summary.name`, `summary.address.disp`.
- **거리·통행료**: proxy `GET /v1/kakao-mobility/directions` (RECOMMEND 경로),
  출발지 키워드 → 좌표는 proxy `GET /v1/kakao-map/search/keyword`.
- **rate limit**: 입력에 등장한 시설만 조회, 시설당 1회 + 0.5초 간격,
  run 당 상한 120회. 평점은 24시간, 경로는 7일 로컬 캐시
  (`~/.cache/k-skill/campsite-recommend.json`).

## Inputs

- `--input PATH`: vacancy 결과 JSON. 반복 지정으로 두 스킬 결과 병합, `-`는 stdin.
  foresttrip/campsite 형식은 자동 감지.
- `--origin "신대방삼거리역"`: 자동차 거리 계산 출발지 (선택)
- `--origin-coords LON,LAT`: 좌표 직접 입력 (선택, `--origin` 대신)
- `--text` / 기본 JSON
- `--refresh-ratings`: 평점 캐시 무시
- `--proxy-base`, `--cache`: override

## Workflow

### 1. Run the vacancy skills first

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- \
  --all --json --dates 20261002,20261003,20261004 --nights 3 --categories 02 > forest.json
```

지자체까지 합치려면 `korean-campsite-vacancy`도 같은 날짜로 실행한다.

### 2. Rank

```bash
npx -y @nomadamas/k-skill@0 exec campsite-recommend scripts/run_campsite_recommend.py -- \
  --input forest.json --input municipal.json --origin "신대방삼거리역" --text
```

### 3. Summarize

- `ranked`: 종합점수 내림차순. 각 행에 점수 분해(`rating_term`/`review_term`),
  평점·평가수·리뷰수, 가용 사이트 수·유형, (origin 지정 시) 거리·시간·통행료.
- `unranked`: 매핑 없음 / 평점 조회 실패 / 연박 미확정 시설. 가용 사이트 수 순.
  **순위를 추측해 섞지 말고 별도 목록으로 전달한다.**
- 여러 날짜가 입력이면 "모든 날짜에 공통으로 빈 사이트"만 가용으로 센다.
  지자체 결과에서 `booking_status`가 `open`이 아닌 날짜가 하나라도 있으면 그
  시설은 미확정(unranked)이다.
- 점수는 시설 품질 전부가 아니라 공개 평점 신호일 뿐임을 함께 전달한다
  (`npx -y @nomadamas/k-skill@0 read campsite-recommend references/SCORING.md`의 "점수가 반영하지 않는 것").

### 4. Extend the mapping (매핑에 없는 시설이 나올 때)

1. 카카오맵에서 시설을 검색해 place 페이지를 연다: `https://place.map.kakao.com/<id>`
2. **시설명·주소가 실제 시설과 일치하는지 사람이 확인**한다. 동명 시설 오매핑이
   최대 리스크다.
3. 저장소 스킬 디렉터리의 place-map.json 해당 섹션(`foresttrip`은 hmpgId 키,
   `providers`는 provider id 키)에 `{name, region, kakao_place_id}`를 추가하고
   `npm run sync:cli-skills`로 번들을 갱신한다.

## Done when

- vacancy 결과를 최소 1개 입력받아 helper를 실행했다.
- `ranked`가 종합점수순으로 정렬됐고 점수 근거(평점·평가수·리뷰수)가 붙어 있다.
- 매핑 없는 시설이 `unranked`로 분리됐고 순위 추측을 하지 않았다.
- `--origin`이 있으면 거리·시간·통행료가 붙었거나 실패가 보고됐다.
- `fetch_failures`가 있으면 개수와 범위를 함께 보고했다.

## Failure modes

- **place-api 406**: 헤더 세트가 바뀐 것. helper의 `PLACE_HEADERS`를 place.map.kakao.com
  프런트(placePrint 번들)에서 다시 확인해 갱신한다.
- **place id가 404/폐업**: 카카오가 장소를 통폐합한 것. place-map.json에서 새 id로
  갱신하고 시설 일치를 다시 사람이 확인한다.
- **proxy 503 `upstream_not_configured`**: proxy에 `KAKAO_REST_API_KEY` 미설정.
  거리 없이 평점 순위만 출력되고 실패로 보고된다.
- **origin 검색 결과 없음**: 키워드를 더 구체적으로 (역명·주소). `--origin-coords`로
  우회 가능.
- **모든 시설이 unranked**: 입력이 vacancy 결과가 아니거나(형식 자동 감지 실패)
  매핑이 비어 있는 것. 입력 JSON의 `results` 구조를 확인한다.
- **run 당 조회 상한(120) 초과**: 캐시가 채워진 뒤 재실행하면 이어서 처리된다.
- **점수가 100 근처로 몰림**: 정규화 기준(979)이 동결 상수라서 리뷰가 많은 시설은
  리뷰항이 100을 넘을 수 있다. 버그가 아니다 (`npx -y @nomadamas/k-skill@0 read campsite-recommend references/SCORING.md`).

## Safety notes

- read-only다. 입력에 등장한 시설만, 캐시 우선으로 조회한다. 대량 인덱싱·반복
  폴링을 하지 않는다.
- 순위는 카카오맵 공개 평점 기반 자체 산정이며 공식 순위가 아니다. 결과를 외부에
  공유할 때 이 사실을 남긴다.
