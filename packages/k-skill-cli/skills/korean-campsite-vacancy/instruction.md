# Korean Campsite Vacancy

## What this skill does

지자체·공공기관이 운영하는 한국 캠핑장의 **빈자리(잔여 면수)를 날짜 기준으로 조회**한다.

전국 지자체 캠핑장의 실시간 빈자리를 통합 제공하는 공식 API는 존재하지 않는다. 운영기관마다 예약 시스템이 다르므로 이 스킬은 **provider adapter 레지스트리**를 두고 시스템 단위로 어댑터를 늘려 나간다.

조회 전용이다. 로그인, 예약 버튼 클릭, 결제, 캡차·본인인증 처리는 하지 않는다.

## When to use

- "연곡 솔향기 캠핑장 이번 주말 자리 있어?"
- "강릉 바다내음 캠핑장 9월 첫째 주 빈자리 알려줘"
- "글램핑 남은 데 있나 확인해줘"
- "지자체 캠핑장 빈자리 조회 로직을 나중에 더 붙일 수 있게 정리해줘"

## When not to use

- 예약 신청·결제까지 자동화해야 하는 경우 (캡차·SMS 본인인증 구간이다)
- 국립자연휴양림 조회 → `foresttrip-vacancy` 스킬을 쓴다
- 국립공원 야영장 조회 → 별도 시스템(`reservation.knps.or.kr`)이며 아직 어댑터가 없다
- 사설(민간) 캠핑장 조회 → 레지스트리에 없다
- 취소표 스나이핑, 반복 폴링

## Prerequisites

- Python 3.9+
- Playwright Chromium browser — **`dzsmart`·`donghae` transport에만 필요하다.** `thankq`·`gmuc`·`maketicket`은 표준 라이브러리만 쓰므로 브라우저 없이 동작한다.

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- --check-deps
```

## Required environment variables

로그인이 필요한 provider에만 해당한다. 나머지는 아무 것도 필요 없다.

- `KSKILL_DONGHAE_ID` / `KSKILL_DONGHAE_PASSWORD` — 동해시 통합예약(`campingkorea.or.kr`) 회원 계정. `donghae-*` provider 4곳에만 쓴다.

### Credential handling

- 돌쇠 credential mode에서는 `vault-run`을 사용하고, 없으면 `request_vault_credential`을 호출한다.
- 그 밖의 환경에서는 이미 주입된 환경변수 → host vault → `~/.config/k-skill/secrets.env` 순서로 사용한다.
- **평문 credential을 채팅창이나 shell 인자에 넣지 않는다.** helper는 환경변수만 읽는다.
- credential이 없으면 조회를 건너뛰고 그 사실을 말한다. 대체 사이트나 우회 경로를 찾지 않는다.

## Provider adapter rule

이 스킬은 예약 시스템별 로직을 **provider adapter** 단위로 나눈다. `delivery-tracking`의 carrier adapter 규칙과 같은 구조다.

새 캠핑장을 붙일 때는 아래 필드를 먼저 정한다.

- `provider id`: 예) `gtdc-yeongok`
- `운영기관`: 실제 운영 주체
- `entrypoint`: 공식 예약 진입 URL
- `transport`: 데이터를 어떻게 얻는지 (`dzsmart` 브라우저 렌더 파싱 / `thankq` form POST / `gmuc` 공개 페이지 GET / `maketicket` form POST / `donghae` 로그인 후 조회 / `delegate`)
- `zone 모델`: 존·사이트 구분 방식
- `date 모델`: 날짜가 어디에 인코딩되는지
- `parser`: 잔여 면수를 어느 필드에서 뽑는지
- `로그인 필요 여부`
- `rate limit`: 호출 간격과 조회 상한

**운영기관이 공공(지자체·공단·공사)일 때만 등록한다.** 예약 창구가 땡큐캠핑 같은 민간 플랫폼이어도 운영 주체가 공공이면 대상이고, 반대로 민간이 운영하는 사설 캠핑장은 같은 플랫폼에 있어도 등록하지 않는다.

현재 레지스트리는 아래와 같다. 자세한 근거는 `npx -y @nomadamas/k-skill@0 read korean-campsite-vacancy references/PROVIDERS.md`를 읽는다.

| provider id | 대상 | 운영기관 | transport | 로그인 |
| --- | --- | --- | --- | --- |
| `gtdc-yeongok` | 연곡해변 솔향기캠핑장 | 강릉관광개발공사 | `dzsmart` | 불필요 |
| `gtdc-badanaeum` | 강릉바다내음캠핑장 | 강릉관광개발공사 | `dzsmart` | 불필요 |
| `gtdc-ojuk` | 강릉오죽한옥마을(숙박) | 강릉관광개발공사 | `dzsmart` | 불필요 |
| `thankq-jaraseom` | 자라섬캠핑장 | 가평군시설관리공단 | `thankq` | 불필요 |
| `gmuc-dodeoksan` | 도덕산캠핑장 | 광명도시공사 | `gmuc` | 불필요 |
| `maketicket-jangho` | 장호비치캠핑장 | 삼척시 | `maketicket` | 불필요 |
| `maketicket-hyangnam` | 화성시향남오토캠핑장 | 화성도시공사 | `maketicket` | 불필요 |
| `donghae-mangsang` | 망상오토캠핑리조트 | 동해시시설관리공단 | `donghae` | **필요** |
| `donghae-mangsang2` | 망상제2오토캠핑장 | 동해시시설관리공단 | `donghae` | **필요** |
| `donghae-mureung` | 무릉힐링캠핑장 | 동해시시설관리공단 | `donghae` | **필요** |
| `donghae-chuam` | 추암오토캠핑장 | 동해시시설관리공단 | `donghae` | **필요** |
| `foresttrip` | 국립자연휴양림 | 산림청 | `delegate` | 필요 |

`foresttrip`은 조회 경로가 아니라 **위임 표시**다. 이 provider를 지정하면 helper는 `foresttrip-vacancy` 스킬을 쓰라는 오류를 낸다.

## Inputs

- 날짜: `--dates YYYYMMDD` 또는 comma-separated `YYYYMMDD,YYYYMMDD`
- 날짜를 생략하면 `--day-range N`(기본 7)로 오늘부터 N일을 조회한다
- 조회 범위: `--provider gtdc-yeongok` (comma-separated, 생략 시 위임이 아닌 provider 전체)
- 선택 필터:
  - `--zone 글램핑`: 존 이름 부분 일치
  - `--include-full`: 마감된 존까지 표시 (기본은 예약 가능한 존만)
- 출력: `--text` 사람용 요약 / `--json` 구조화 결과(기본)

## Workflow

### 1. Confirm the target campground is in the registry

```bash
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- --list-providers
```

레지스트리에 없는 캠핑장이면 **추측해서 조회하지 않는다.** 없다고 말하고, 필요하면 어댑터 추가가 필요하다고 안내한다.

### 2. Install runtime dependencies when missing

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

### 3. Run a vacancy lookup

특정 캠핑장의 특정 날짜:

```bash
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- \
  --provider gtdc-yeongok --dates 20260905,20260906 --text
```

등록된 캠핑장 전체를 이번 주 기준으로:

```bash
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- \
  --day-range 7 --text
```

글램핑만, 마감 포함:

```bash
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- \
  --provider gtdc-yeongok --dates 20260905 --zone 글램핑 --include-full --json
```

### 4. 연박 질문은 밤 전부 + 기준선 날짜를 함께 넘긴다

"10/2~10/5 3박" 같은 질문에서 밤은 10/2·10/3·10/4다. **퇴실일은 넘기지 않는다.**

`--dates`에 밤 전부를 넣는다. 이 스킬에는 `--nights` 옵션이 없고, 존별 잔여 면수는 **날짜 단위 집계**라서 "같은 사이트가 세 밤 연속 비어 있는가"는 알 수 없다. 세 밤 모두 잔여가 있어도 **같은 자리인지는 확정할 수 없다**는 점을 반드시 함께 전달한다. 사이트 단위 확정이 필요하면 공식 예약 화면으로 넘긴다.

`donghae`는 여기에 규칙이 하나 더 붙는다. **예약창이 하루치씩 열리지만 연박은 미오픈 날짜까지 한 번에 뻗는다.** 따라서

- **N박의 승부는 첫 밤이 열리는 날 11:00에 끝난다.** 금·토·일 3박이면 그 **금요일의 30일 전 11:00**이 유일한 기회다. 마지막 밤이 열릴 때까지 기다리라고 안내하면 안 된다
- 미오픈 날짜의 숫자가 연박으로 이미 깎였는지 보려면 **연박이 닿을 수 없는 먼 미개시 날짜를 기준선으로 함께 조회**한다

```bash
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- \
  --provider donghae-mangsang --dates 20261002,20261003,20261004,20261009 --include-full --json
```

10/9(기준선)보다 10/3·10/4가 낮으면 그만큼 연박이 이미 나간 것이다. 근거는 `npx -y @nomadamas/k-skill@0 read korean-campsite-vacancy references/PROVIDERS.md`의 `donghae` 연박 절에 있다.

### 5. Summarize results conservatively

- 조회 날짜와 캠핑장명
- 존별 잔여 면수 (마감이면 마감이라고 쓴다)
- 시즌 구분(성수기/준성수기/비수기)이 있으면 요금 판단에 영향을 주므로 함께 전달
- 요금이 함께 오면(`thankq`) 같이 전달한다. 주말·주중 요금이 다르다
- **`booking_status`가 `open`이 아니면 그 사실을 먼저 말한다.** 특히 `not_open`은 예약창이 안 열린 날이라 **숫자를 빈자리로 전달하지 않는다.** 총 정원이라고 단정하지도 않는다. `donghae`에서는 연박이 미오픈 날짜 재고를 이미 먹었을 수 있다(위 4단계)
- `not_open`은 `donghae`(이용일 30일 전 오픈), `thankq`(예약 페이지의 `res_able_max_dt` 이후), `dzsmart`(해당 월 달력 미공개) 세 경로에서 나온다. 셋 다 **마감이 아니라 "아직 열리지 않음"**이므로 언제 열리는지와 함께 전달한다
- `fetch_failures`가 0이 아니면 실패한 provider와 실패 범위(`scope`)를 함께 보고

빈자리가 없으면 **"조회 시점 기준 예약 가능 사이트 없음"** 이라고 명확히 말한다. 잔여 면수는 실시간으로 바뀌므로 실제 예약 화면에서 재확인될 수 있음을 덧붙인다.

### 6. Hand off to the official booking page

예약을 원하면 공식 예약 페이지 URL을 그대로 안내한다.

```
https://camping.gtdc.or.kr/pub/reserv.do
```

이 구간에는 캡차와 SMS 본인인증이 걸려 있다(`sets.captcha=true`, `sets.smsauth=true`). 대신 통과하지 않는다.

## Done when

- 대상 캠핑장이 레지스트리에 있는지 확인했다.
- 조회 helper를 최소 1회 실행했다.
- 빈자리가 있으면 날짜/캠핑장/존/잔여 면수를 정리했다.
- 빈자리가 없으면 없다고 명확히 말했다.
- 연박 질문이면 밤 전부를 조회했고, 존별 잔여로는 **같은 자리 연속 여부를 확정할 수 없다**는 점을 전달했다.
- `donghae` 연박이면 첫 밤이 열리는 날 11:00이 기회라고 말했고, 미오픈 날짜 숫자를 잔여나 총 정원으로 전달하지 않았다.
- 레지스트리에 없는 캠핑장을 임의 URL로 추측 조회하지 않았다.
- 캡차·본인인증·결제 구간은 사용자에게 넘겼다.

## Failure modes

- Playwright 미설치: `python3 -m pip install playwright && python3 -m playwright install chromium` (`dzsmart` provider에만 해당)
- `thankq` 500 응답: 날짜 형식이 `YYYYMMDD`가 아니거나 `camp_seq`가 잘못됐다
- `thankq` 예약창 밖 날짜: 사이트 목록 endpoint는 **예약창이 열리지 않은 날짜에도 총 정원을 그대로 응답한다.** 어댑터가 예약 페이지(`/resv/view.hbb?cseq=`)의 `res_able_max_dt`·datepicker 범위를 읽어 `booking_status: not_open`으로 표시한다. 이 숫자를 잔여로 읽지 않는다
- `thankq` booking-window 조회 실패: `scope: booking-window` 실패로 보고된다. 이때 날짜 상태는 `open`으로 남으므로 **공식 화면에서 예약 가능 기간을 직접 확인**하라고 안내한다
- `maketicket` 날짜 없음: 예약 미오픈이거나 운영하지 않는 날짜다. 실패로 보고되며 "빈자리 없음"이 아니다
- `gmuc` 범위 밖 날짜: 공개 예약현황이 **당월+익월 2개월만** 노출한다. 그 밖의 날짜는 실패로 보고되며 "빈자리 없음"이 아니다
- `donghae` credential 누락: `KSKILL_DONGHAE_ID` / `KSKILL_DONGHAE_PASSWORD` 확인. 값이 `replace-me`면 미설정으로 처리된다
- `donghae` 로그인 실패: 아이디/비밀번호를 확인한다. 대신 캡차를 풀지 않는다
- `donghae` NOPASS 응답: 사이트 흐름이 바뀐 것이다. **캡차를 우회하지 말고** 실패로 보고한다
- `donghae` `Page.goto: net::ERR_ABORTED`: 월 달력 이동에서 간헐 발생한다. 어댑터에 재시도가 없으므로 **같은 명령을 그대로 다시 실행**한다. 2026-09-02에 망상이 2회 연속 실패 후 3회차에 통과했다. 이걸 "조회 불가"로 결론내지 않는다
- 미래 날짜인데 모든 시설이 만석으로 나옴: `booking_status: not_open`인지 확인한다. 동해시는 이용일 **30일 전 오전 11시**에 예약창을 연다
- `donghae` 미오픈 날짜 숫자를 총 정원으로 오독: 연박이 미오픈 날짜 재고를 이미 먹었을 수 있다. **먼 미개시 날짜를 기준선으로 함께 조회**해 비교한다. 위 workflow 4단계 참고
- `donghae` 오픈 당일 조회가 몇 분 만에 무의미해짐: 연휴 구간은 오픈 직후 소진이 매우 빠르다. 망상 10/2분은 2026-09-02 11:00 오픈 후 **22분 만에 전 존 마감**됐다. 조회 시각을 반드시 함께 전달한다
- `booking_status: unknown`: 달력 라벨이 바뀐 것이다. 예약 가능으로 단정하지 말고 사용자에게 공식 화면 확인을 안내한다
- `wait_for_selector` timeout: 예약 시스템 점검 중이거나 해당 월이 아직 오픈 전이다. 월을 바꿔 재확인하고, 그래도 비면 "해당 월 예약 미오픈"으로 보고한다
- `dzsmart` 요청 월이 달력에 없음: 그 달 예약이 아직 안 열린 것이다. 결과에서 조용히 빠지지 않고 `booking_status: not_open` + `2026-10 예약 달력이 아직 열리지 않았다` 같은 `status_note`로 나온다. **마감이 아니다**
- 결과가 전부 마감: 정상 동작이다. 성수기 주말은 대부분 마감이다
- 존 이름이 바뀜: dzSmart 존 구성은 운영기관이 시즌마다 바꾼다. `--include-full`로 원본 존 목록을 먼저 확인한다
- 파서가 0건 반환: 사이트가 렌더링 구조를 바꿨을 가능성이 높다. `tests/fixtures/`의 캡처와 실제 응답을 비교해 `parse_month_html`(dzsmart) 또는 `parse_thankq_html`(thankq)을 점검한다
- 월 조회 상한 초과: 요청 날짜가 6개월을 넘게 걸쳐 있다. 날짜를 나눠 조회한다

## Rate limit

- `dzsmart`는 provider × 월 단위로 페이지를 1회씩만 연다.
- `thankq`는 월 조회 화면이 없어 provider × 날짜 단위로 1회씩 요청한다. 날짜 범위를 넓게 잡으면 요청 수가 그만큼 늘어나므로 필요한 날짜만 지정한다.
- `donghae`는 provider당 로그인 1회 + 날짜당 조회 1회다. 로그인이 비싸므로 날짜를 모아서 한 번에 넘긴다.
- `gmuc`는 페이지 1회 요청으로 두 달치를 모두 얻는다. 가장 가벼운 경로다.
- `maketicket`은 ticket 페이지 1회 + 월별 캘린더 1회다. `idkey`는 하드코딩하지 않고 매번 ticket 페이지에서 읽는다.
- 취소표를 노린 반복 폴링을 하지 않는다. 사용자가 반복 확인을 원하면 공식 알림 기능을 안내한다.

## Maintainer review notes

계정 없이 가능한 검증:

- `./scripts/validate-skills.sh`
- `python3 -m py_compile korean-campsite-vacancy/scripts/run_campsite_vacancy.py`
- `python3 -m unittest discover -s korean-campsite-vacancy/tests -p "test_*.py"`
- `npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- --list-providers`
- `npm run ci`

파서 테스트는 `tests/fixtures/`의 실제 캡처 HTML로 돌기 때문에 브라우저 없이 통과한다. live smoke는 Playwright가 설치된 환경에서 선택적으로 수행한다.

## Safety notes

- 조회 전용이다. 예약 폼 제출, 결제, 좌석 선점을 하지 않는다.
- 캡차·SMS 본인인증을 대신 처리하지 않는다.
- 레지스트리에 없는 사이트를 URL 패턴으로 추측해 조회하지 않는다.
- 공개 예약 화면이 노출하는 잔여 수만 읽고, 개인 예약 내역 조회 화면에는 접근하지 않는다.
- 민간 플랫폼(`thankq`)에서는 등록된 공공 운영 캠핑장만 조회한다. `camp_seq`를 임의로 바꿔 사설 캠핑장을 훑지 않는다.
- `donghae`는 사용자 본인 계정으로 로그인해 **공개 잔여 현황 화면만** 읽는다. 예약 단계의 캡차는 건드리지 않고, 타인 예약 내역에도 접근하지 않는다.
