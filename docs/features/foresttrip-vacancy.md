# 자연휴양림 빈 객실 조회 가이드

대상 사이트는 숲나들e 공식 사이트 `https://foresttrip.go.kr/index.jsp` 이다. 빈 객실을 조회하고, 사용자가 명시적으로 요청하면 helper가 소유한 보이는 브라우저에서 정확한 시설을 선택해 CAPTCHA/약관 수동 단계까지 준비한다.

## 이 기능으로 할 수 있는 일

- 숲나들e/자연휴양림 예약 가능 객실 조회
- 특정 날짜 또는 여러 날짜 기준 조회
- 전체 자연휴양림 또는 휴양림명/ID 기준 조회
- 숙박/야영 카테고리별 조회
- JSON 또는 사람이 읽기 좋은 텍스트 출력
- 공식 NetFunnel 대기열을 통한 예약 화면 진입
- 정확한 시설 선택과 결제 직전 수동 인계

CAPTCHA 입력, 약관 동의, 예약 제출, 결제, 대기열 우회, 반복 스나이핑은 자동화하지 않는다. 사용자가 직접 예약을 제출해 결제 화면에 도달하면 helper는 자동화를 멈춘 채 화면을 유지한다.

## 먼저 필요한 것

- Python 3.9+
- Playwright Chromium
- [공통 설정 가이드](../setup.md) 완료
- [보안/시크릿 정책](../security-and-secrets.md) 확인

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --check-deps
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/prepare_foresttrip_booking.py -- --check-deps
```

`--check-deps` 는 숲나들e 로그인이나 네트워크 조회를 수행하지 않고, 로컬 Python/Playwright Chromium 준비 상태만 확인한다.

## 필요한 환경변수

- `KSKILL_FORESTTRIP_ID`
- `KSKILL_FORESTTRIP_PASSWORD`

선택:

- 없음

### Credential resolution order

1. **이미 환경변수에 있으면** 그대로 사용한다.
2. **에이전트가 자체 secret vault(1Password CLI, Bitwarden CLI, macOS Keychain 등)를 사용 중이면** 거기서 꺼내 환경변수로 주입해도 된다.
3. **`~/.config/k-skill/secrets.env`** (기본 fallback) — plain dotenv 파일, 퍼미션 `0600`.
4. **아무것도 없으면** 유저에게 물어서 2 또는 3에 저장한다.

조회 helper는 `KSKILL_FORESTTRIP_ID`, `KSKILL_FORESTTRIP_PASSWORD` 환경변수를 읽는다. 브라우저 helper는 이미 주입된 값을 우선하고, 값이 없을 때 `~/.config/k-skill/secrets.env`를 fallback으로 읽는다. 두 helper 모두 계정을 출력하거나 명령행 인자로 받지 않는다.

## 처음 실행 순서

처음 쓰는 사용자는 의존성 확인 후 환경변수를 현재 shell에만 주입해서 1개 휴양림으로 먼저 조회한다.

```bash
export KSKILL_FORESTTRIP_ID="your-foresttrip-id"
export KSKILL_FORESTTRIP_PASSWORD="your-foresttrip-password"

npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --check-deps
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --forest-name 유명산 --text --dates 20260504
```

성공 여부를 먼저 보려면 전체 조회보다 `--forest-name` 또는 `--forest-id` 로 범위를 좁혀 실행한다. JSON 결과가 필요하면 같은 조건에 `--json` 을 사용한다.

## 입력값

- 날짜: `YYYYMMDD`
- 여러 날짜: `YYYYMMDD,YYYYMMDD`
- 조회 범위: 전체 자연휴양림, 휴양림 ID, 휴양림명 부분 일치
- 카테고리:
  - `01`: 숙박
  - `02`: 야영/캠핑
  - `01,02`: 숙박 + 야영/캠핑
- 고급 옵션:
  - `--week-range N`: `--dates` 를 생략했을 때만 오늘부터 N주 조회
  - `--concurrency N`: 병렬 조회 worker 수, 1-5 범위
  - `--session-cache PATH`: 로그인 세션 캐시 경로 override

## 기본 흐름

1. `KSKILL_FORESTTRIP_ID`, `KSKILL_FORESTTRIP_PASSWORD` 를 확보한다.
2. 필요한 경우 `python3 -m pip install playwright` 와 `python3 -m playwright install chromium` 을 실행한다.
3. helper로 read-only 월별예약조회 endpoint를 실행한다.
4. helper가 로그인 세션, CSRF, 공식 휴양림 ID 목록을 확보한다.
5. 날짜, 휴양림명, 객실/시설명, 숙박/야영 구분, 정원 중심으로 요약한다.
6. 응답 정제: API가 `srchDate` 기준 최대 5일 윈도우를 반환할 수 있어 helper가 요청 범위 밖 `useDt`, 운영자 보유분("예비" 포함 객실), 같은 객실 중복 행을 자동 제거한다.
7. 사용자가 예약 준비를 명시적으로 요청한 경우, 전체 숙박일에 같은 시설이 연속으로 비어 있는지 재확인한다.
8. 브라우저 helper가 공식 로그인·NetFunnel을 거쳐 정확한 시설을 선택한다.
9. CAPTCHA·약관·예약 제출은 사용자가 직접 처리한다. 결제 화면이 열리면 자동화가 멈춘다.

2026-04-29 확인 기준, 로그인 없이 월별예약조회 화면에 접근하면 `401 Unauthorized`가 반환되고, 조회 endpoint는 JSON 대신 안내 HTML을 반환한다. 따라서 현재 구현은 로그인 세션/CSRF 확보를 필수 전제로 둔다.

## 검증 방식

메인테이너가 별도 숲나들e 계정을 새로 만들 필요는 없다.

- CI/리뷰 검증: `./scripts/validate-skills.sh`, 두 helper의 `python3 -m py_compile`, unit test, `--help`, `--check-deps` 로 진행한다.
- 실제 조회 검증: 기여자 또는 이미 숲나들e 계정을 가진 사용자가 개인 계정으로 선택 실행한다.
- PR에는 실제 조회 결과의 `forests_scanned`, `fetch_failures`, `filter_hits` 같은 비민감 요약값만 기록하고, 계정 정보와 세션 쿠키는 공유하지 않는다.

## 예시

전체 자연휴양림에서 하루 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --all --text --dates 20260504
```

JSON으로 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --all --json --dates 20260504
```

여러 날짜 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --all --text --dates 20260504,20260505
```

야영/캠핑만 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --all --text --dates 20260504 --categories 02
```

휴양림명으로 좁혀 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --forest-name 유명산 --text --dates 20260504
```

로그인 세션 캐시를 무시하고 새로 조회:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- --all --text --dates 20260504 --refresh-session
```

정확한 시설을 선택하고 CAPTCHA/약관 수동 단계까지 보이는 브라우저로 열기:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/prepare_foresttrip_booking.py -- \
  --forest-id ID02030054 \
  --check-in 20260906 \
  --check-out 20260907 \
  --facility-type "국민여가오토캠핑장" \
  --room-name "데크 01"
```

## 주의할 점

- 브라우저 helper는 명시적인 예약 준비 요청에서만 실행한다.
- 결제, CAPTCHA 입력, 약관 동의, 예약 제출, 대기열 우회는 자동화하지 않는다.
- aggressive polling은 피한다.
- 조회 결과는 시점 차이로 숲나들e 화면과 달라질 수 있다.
- 로그인 실패 시 계정 정보 또는 숲나들e 정책 변경을 먼저 확인한다.
- API가 요청 날짜보다 넓은 5일 윈도우를 반환해도 출력에는 요청 범위(`today`–`last_day`) 안의 행만 포함된다.
- "예비" 표기가 있는 객실은 사용자 예약 화면에 노출되지 않는 운영자 보유분이라 결과에서 자동 제외된다.

## 흔한 문제 해결

- `Playwright browser missing`: `python3 -m playwright install chromium` 을 실행한다.
- `Missing KSKILL_FORESTTRIP_ID` 또는 `Missing KSKILL_FORESTTRIP_PASSWORD`: 환경변수가 현재 shell에 주입됐는지 확인한다.
- 로그인 실패: 숲나들e 웹사이트에서 같은 계정으로 직접 로그인되는지 먼저 확인한다.
- 날짜/카테고리/출력 옵션 오류: helper가 로그인 전에 argparse error로 중단하므로 메시지에 맞춰 값을 고친다.
- JSON 대신 HTML 안내 페이지가 반환됨: 세션/CSRF가 없거나 만료된 상태일 수 있으므로 `--refresh-session` 으로 1회 재조회한다.
- 일부 휴양림 fetch failure: 성공한 결과와 실패 개수를 함께 보고하고, 반복 polling으로 보정하지 않는다.
- 브라우저 helper가 객실명을 둘 이상 찾음: 더 정확한 전체 객실/사이트명으로 다시 실행한다.
- `SAFE_STOP`: 열린 공식 화면에서 상태를 확인하되 CAPTCHA·대기열·payment endpoint를 우회하지 않는다.
