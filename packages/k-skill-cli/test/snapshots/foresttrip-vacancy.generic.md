# foresttrip-vacancy — assembled instructions

Runtime mode: generic

## Runtime rules

- Detect capabilities, not product names. Dolshoi credential mode is active only when `DOLSHOI_ACTION_BROKER_URL` is set and `vault-run` is available; CloakBrowser mode is active when the built-in browser tool identifies CloakBrowser or `CLOAKBROWSER_PEEK_TOKEN` is set.
- When the user asks for an action and the official surface supports it lawfully, continue beyond lookup through reversible preparation and execution. Do not declare completion at a result list, deep link, or handoff when the action can still be carried out.
- Immediately before an irreversible external side effect such as payment, message/email delivery, final submission, cancellation, account mutation, or public posting, call `clarify` with the exact target, amount/payload, and effect. Execute only after approval; do not ask again for already-approved reversible steps.
- Preserve hard boundaries for law, required physical presence, CAPTCHA, identity proofing, electronic signatures, and unsupported official surfaces. In those cases, complete the furthest lawful supported step and open or prepare the exact next official step for the user.
- Resolve credentials in this order: already-injected environment variables, then the host vault, then `~/.config/k-skill/secrets.env` (mode `0600`). If the value is missing, request it through the safest input surface the host provides and store it in the vault or dotenv; never echo it back.
- Use `k-skill-browser-runtime` (provider `auto`: BrowserOS CDP, then Aside CLI, then user-launched Chrome CDP) for logged-in or rendered-page automation. Do not launch or close the user's browser, and never solve CAPTCHA, identity proofing, or e-signature flows.
- Complete search and reversible reservation steps that the documented portable workflow supports, then report the confirmation, purchase deadline, and the exact official surface where the user finishes payment. Do not automate payment here.

## Bundled asset access

- Execute bundled helpers only through `npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/<file> -- <args>`; do not assume a repository-relative or installed-skill-relative path.
- Resolve an asset path with `npx -y @nomadamas/k-skill@0 path foresttrip-vacancy <relative-path>` only when another tool explicitly requires a filesystem path.
- Read bundled references through `npx -y @nomadamas/k-skill@0 read foresttrip-vacancy references/<file>`.

# Foresttrip Vacancy

## What this skill does

숲나들e 공식 사이트(`https://foresttrip.go.kr/index.jsp`)에서 자연휴양림 예약 가능 객실을 날짜 기준으로 조회한다.

사용자가 명시적으로 예약 준비를 요청하면 조회 결과를 공식 예약 화면으로 이어간다. 돌쇠에서는 CloakBrowser를 우선하고, generic runtime에서는 Python 예외 helper가 소유한 보이는 Playwright 브라우저를 열어 정확한 시설을 선택한다. CAPTCHA·약관 동의·예약 제출·결제는 자동화하지 않는다.

## When to use

- "이번 주말 자연휴양림 빈 객실 있어?"
- "숲나들e 2026년 5월 4일 예약 가능한 곳 조회해줘"
- "자연휴양림 빈자리 전체 조회해줘"
- "관심 휴양림 중 예약 가능한 객실만 알려줘"
- "이 객실로 결제 직전 화면까지 열어줘"

## When not to use

- CAPTCHA 입력, 약관 동의, 예약 제출 또는 결제를 자동화해야 하는 경우
- 캡차를 풀거나 대기열을 우회해야 하는 경우
- 계정 정보를 채팅창에 직접 넣으려는 경우
- aggressive polling, 스나이핑, 반복 예약 시도가 필요한 경우

## Prerequisites

- Python 3.9+
- Playwright Chromium browser

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --check-deps
```

## Required environment variables

- `KSKILL_FORESTTRIP_ID`
- `KSKILL_FORESTTRIP_PASSWORD`

Optional:

- none

### Credential handling

- 돌쇠 credential mode에서는 `vault-run` capability를 사용하고, 없으면 `request_vault_credential`을 호출한다. ID/PW 원문을 채팅이나 shell에 넣지 않는다.
- 그 밖의 환경에서는 이미 주입된 환경변수 → host vault → `~/.config/k-skill/secrets.env` 순서로 사용한다.
- Generic helper 자체는 `KSKILL_FORESTTRIP_ID`, `KSKILL_FORESTTRIP_PASSWORD` 환경변수만 읽는다.
- 브라우저 예약 helper는 이미 주입된 환경변수를 우선하고, 없을 때만 `~/.config/k-skill/secrets.env`를 읽는다. 계정을 shell 인자로 받거나 출력하지 않는다.

## Inputs

- 날짜: `YYYYMMDD`, 여러 날짜면 comma-separated `YYYYMMDD,YYYYMMDD`
- 조회 범위:
  - `--all`: 전체 자연휴양림 조회
  - `--forest-id`: 특정 `insttId` 조회
  - `--forest-name`: 공식 휴양림명 부분 일치 조회
- 출력 형식:
  - `--text`: 사람용 요약
  - `--json`: 구조화 결과
- 연박 조회:
  - `--nights 3`: 같은 객실이 3박 연속 비어 있고, 휴양림의 최대 숙박일수도 3박 이상인 건만 남긴다
- 선택 필터:
  - `--categories 01`: 숙박
  - `--categories 02`: 야영/캠핑
  - `--categories 01,02`: 숙박 + 야영/캠핑
- 고급 실행 옵션:
  - `--week-range N`: `--dates` 를 생략했을 때만 오늘부터 N주 범위를 조회
  - `--concurrency N`: 병렬 조회 worker 수, 1-5 범위
  - `--session-cache PATH`: 로그인 세션 캐시 경로 override
- 브라우저 예약 준비:
  - `--forest-id`: 공식 `hmpgId`/`insttId`
  - `--check-in`, `--check-out`: `YYYYMMDD`
  - `--facility-type` 또는 `--facility-code`: 화면의 상품 유형
  - `--room-name`: 최신 조회 결과의 정확한 객실/사이트명
  - `--browser-channel`: helper가 소유할 `chromium`(기본), `chrome`, `msedge`

## Workflow

### 1. Ensure credentials are available

돌쇠 credential mode에서는 숲나들e capability를 사용하고, 없으면 `request_vault_credential`을 호출한다. generic fallback에서만 `KSKILL_FORESTTRIP_ID`, `KSKILL_FORESTTRIP_PASSWORD`를 확인한다.

시크릿이 없다는 이유로 대체 사이트, 캡차 우회, 비공식 예약 경로를 찾지 않는다.

### 2. Install runtime dependencies when missing

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

### 3. Run a vacancy lookup

이 스킬의 helper를 통해 조회한다. Helper는 Playwright로 숲나들e에 로그인해 CSRF/cookie와 공식 휴양림 ID 목록을 얻은 뒤, 월별예약조회 JSON endpoint만 호출한다.

2026-04-29 확인 기준, 로그인 없이 월별예약조회 화면에 접근하면 `401 Unauthorized`가 반환되고, 조회 endpoint는 JSON 대신 안내 HTML을 반환한다. 따라서 현재 helper는 로그인 세션/CSRF 확보를 필수 전제로 둔다.

API는 `srchDate` 단일 일자만 요청해도 응답에 5일 윈도우를 포함할 수 있다. helper는 요청 범위(`today`–`last_day`) 밖 `useDt` 행을 자동 제거하므로 사용자에게는 요청한 날짜의 빈자리만 노출된다.

전체 자연휴양림에서 특정 날짜 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --all --text --dates 20260504
```

JSON 출력:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --all --json --dates 20260504
```

캠핑/야영만 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --all --text --dates 20260504 --categories 02
```

특정 휴양림명으로 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --forest-name 유명산 --text --dates 20260504
```

### 3-1. Multi-night requests must use `--nights`

날짜별 잔여를 눈으로 교집합해서 "3박 가능"이라고 말하면 안 된다. 같은 객실이 3일 다 비어 있어도 휴양림별 **최대 숙박일수**를 넘으면 예약 단계에서 `휴양림의 최대 숙박일수를 초과하여 신청하셨습니다`로 막힌다(2026-08-30 확인: 금원산 야영데크는 최대 2박이라 3박 신청이 거부된다).

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- \
  --all --json --dates 20261002,20261003,20261004 --nights 3
```

`--nights N`은 같은 `goodsId`가 N일 연속 비어 있는 건만 남기고, `mxmmStngDayCnt`가 N보다 작은 객실은 제외한다. 남은 행에는 `stay_nights`가 붙는다.

### 4. Summarize results conservatively

응답은 아래 항목 중심으로 짧게 정리한다.

- 조회 날짜 (연박이면 `nights`도)
- 조회 범위
- 예약 가능한 휴양림명
- 객실/시설명
- 숙박/야영 구분
- 정원 또는 수용 인원
- fetch failure가 있으면 실패 개수

결과가 없으면 "조회 시점 기준 예약 가능 객실 없음"이라고 말한다. 실제 예약 가능 여부는 숲나들e 화면에서 재확인될 수 있음을 덧붙인다.

`goodsNm`에 "예비"가 포함된 객실은 운영자가 보유하는 내부용 자리로, 사용자 예약 화면에는 노출되지 않는다. helper는 이 객실들을 결과에서 자동 제외한다. 같은 `(휴양림, 날짜, 객실명)` 조합의 중복 행도 dedup된다.

### 5. Open the visible booking handoff only on explicit request

먼저 전 숙박일에 같은 객실/사이트가 연속으로 비어 있는지 read-only helper로 다시 확인한다. 그 다음 브라우저 운영 절차를 읽는다.

```bash
npx -y @nomadamas/k-skill@0 read foresttrip-vacancy references/browser-booking.md
```

generic runtime에서 정확한 시설을 공식 화면에 선택하는 예시:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/prepare_foresttrip_booking.py -- \
  --forest-id ID02030054 \
  --check-in 20260906 \
  --check-out 20260907 \
  --facility-type "국민여가오토캠핑장" \
  --room-name "데크 01"
```

이 Python 스킬은 저장소의 browser-runtime 예외다. helper는 사용자 브라우저나 기존 profile을 닫지 않고 자신이 소유한 보이는 브라우저만 연다. 공식 `fn_goRsvt()`와 NetFunnel 대기열을 그대로 사용하고, 정확한 객실명이 하나의 상품과 일치할 때만 선택한다.

`자동예약 방지숫자`와 약관 동의 화면에서 자동화를 멈춘다. 사용자가 내용을 확인하고 CAPTCHA·동의·`예약` 제출을 직접 완료하면 helper는 결제 화면을 감지해 열린 상태로 유지한다. 결제 컨트롤은 누르지 않는다.

## Done when

- 요청 날짜와 조회 범위가 명확하다.
- read-only 월별예약조회 helper를 최소 1회 실행했다.
- 빈 객실이 있으면 날짜/휴양림/객실을 정리했다.
- 빈 객실이 없으면 없다고 명확히 말했다.
- 예약 준비 요청이면 공식 브라우저에서 정확한 시설을 선택하고 CAPTCHA/약관 수동 단계까지 열었다.
- 사용자가 직접 예약을 제출해 결제 화면에 도달한 경우 자동화가 멈춘 상태로 화면을 유지했다.
- CAPTCHA/대기열 우회는 시도하지 않았다.

## Failure modes

- 로그인 실패: `KSKILL_FORESTTRIP_ID`, `KSKILL_FORESTTRIP_PASSWORD` 확인
- Playwright browser 미설치: `python3 -m playwright install chromium`
- fetch failure 일부 발생: 결과와 실패 개수를 함께 보고하고, 필요하면 `--refresh-session` 으로 1회 재조회
- 숲나들e 표면 변경: helper의 login/session bootstrap 또는 parser 점검 필요
- "(예비)" 객실이 결과에 안 나옴: 정상 동작이다. 사용자 예약 화면에 노출되지 않는 운영자 보유분이라 의도적으로 제외된다.
- 사용자 화면 객실 수와 helper 결과가 다름: 같은 객실의 중복 행이 dedup되었거나, 요청 범위 밖 `useDt`가 제거됐을 가능성이 높다. raw API 응답을 확인하려면 helper 로직을 우회해서 직접 호출 필요.
- **월별예약조회 API에는 있는데 공식 화면에는 없는 객실**: 정상 동작이다. helper는 `selectRsrvtGoodsListForMonthRsrvtSmpl.do`가 실제로 파는 상품(`rsrvtGoodsList`)만 남긴다. 공식 화면도 이 목록이 비면 아무것도 그리지 않는다(2026-08-30 확인: 가리산 야영장은 `rsrvtAvail=Y`/`rsrvtCnt=0` 행이 102건 오지만 판매 상품은 0건이라 화면에 아무것도 안 뜬다)
- `goods:` 로 시작하는 failure: 상품 목록 조회가 실패한 것이다. 이때는 행을 지우지 않고 그대로 두므로, **공식 화면 교차 확인**을 함께 안내한다
- `window:` 로 시작하는 failure: 예약가능기간 조회가 실패한 것이다. 같은 이유로 날짜를 지우지 않는다
- 예약가능기간 밖 날짜가 사라짐: 정상 동작이다. 휴양림마다 `금일 ~ N까지`가 다르고(주별/월별 주기), helper는 `selectSthngListForMonthRsrvt.do`의 정책값으로 그 뒤 날짜를 제외한다
- 브라우저 helper에서 객실명 중복: 임의 선택하지 말고 전체 객실명을 더 정확하게 지정
- 공식 대기열 timeout: 우회하지 말고 열린 브라우저에서 기다리거나 종료
- CAPTCHA/약관 화면: 정상 수동 인계이며 helper가 입력하거나 체크하지 않음
- 화면 변경: `SAFE_STOP`과 query string이 제거된 공식 URL을 보고하고, payment endpoint를 추측해 호출하지 않음

## Maintainer review notes

메인테이너가 이 스킬을 검토하기 위해 숲나들e 계정을 새로 만들 필요는 없다.

계정 없이 가능한 검증:

- `./scripts/validate-skills.sh`
- `python3 -m py_compile foresttrip-vacancy/scripts/run_foresttrip_vacancy.py`
- `python3 -m py_compile foresttrip-vacancy/scripts/prepare_foresttrip_booking.py`
- `python3 foresttrip-vacancy/tests/test_prepare_foresttrip_booking.py`
- `npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --help`
- `npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --check-deps`
- `npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/prepare_foresttrip_booking.py -- --check-deps`
- `npm run ci`

실제 live smoke는 기여자 또는 이미 숲나들e 계정을 가진 사용자가 선택적으로 수행한다. PR에는 `forests_scanned`, `fetch_failures`, `filter_hits` 같은 비민감 요약만 남기고 계정 정보, 세션 쿠키, 개인 조회 세부 내역은 공유하지 않는다.

## Safety notes

- 조회 helper는 read-only다. 브라우저 helper는 명시적인 요청에서만 정확한 시설 선택까지 진행한다.
- 브라우저 helper에는 CAPTCHA 입력, 약관 동의, 예약 제출, 결제 클릭 코드가 없다.
- 캡차 처리, 대기열 우회, 공격적인 반복 조회를 하지 않는다.
- 돌쇠에서는 vault action을 사용하고, generic fallback에서만 환경변수 또는 `~/.config/k-skill/secrets.env`를 사용한다.
