# Ticket Availability

## What this skill does

YES24 (`ticket.yes24.com`) 와 인터파크 (`tickets.interpark.com`) 의 공개 BFF JSON / Ajax endpoint 를 단일 HTTP 요청으로 호출해 공연 일정과 등급별 잔여석 수를 정규화한다.

- 공연 URL 또는 `platform:id` 표기로 입력을 받는다.
- 일정 (날짜·시간·회차) 조회.
- 등급별 잔여석 수 조회 (등급명, 잔여수, YES24의 경우 노출가).
- 좌석맵 / 좌석 선택 / 예매 / 결제 / 로그인 세션 접근은 하지 않는다.
- CloakBrowser, Playwright, fingerprint spoofing, CAPTCHA 우회를 사용하지 않는다 (`httpx` only).

## When to use

- "오늘 인터파크 ○○ 공연 잔여석 있어?"
- "YES24 콘서트 ID 58026 일정 알려줘"
- "이 공연 R석 몇 자리 남았어?"
- "공연 URL 줄게, 회차별 잔여석 확인해줘"
- "고척·잠실 야구 중에 3명 앉을 자리 남은 경기 알려줘" (goods 코드를 알고 있을 때)

## When not to use

- 예매·결제·취소·환불 처리 — **공연법 §4조의2 (2023.9 시행) 매크로 입장권 부정구매·판매 금지** 대상이며 이 스킬은 의도적으로 예매를 지원하지 않는다.
- 좌석 선택, 좌석맵 시각화, 특정 좌석 번호 확인 — 잔여 *수* 만 노출한다.
- 회원 등급별 우선 예매, 쿠폰가, 카드사 할인가 — 공개 endpoint 만 사용한다.
- 차단 우회, CAPTCHA 우회, headless 감지 우회 — `httpx` 한 호출로 안 되면 실패 모드로 처리하고 종료한다.

## Required inputs

공연 URL 또는 `platform:id` 표기가 없으면 먼저 물어본다. **이 스킬에는 공연/경기 검색 기능이 없다** — 아래 "goods 코드를 구하는 방법" 참고.

권장 질문:

> 확인하실 공연의 YES24 또는 인터파크 URL을 알려주세요.
> 예: `https://tickets.interpark.com/goods/26000541`
>     `https://ticket.yes24.com/Perf/58026`

## Prerequisites

- Python 3.9+
- `httpx` (표준 패키지)

설치:

```bash
pip install httpx
```

## Workflow

### 1. URL 파싱

| 입력 | 매칭 |
|---|---|
| `https://tickets.interpark.com/goods/<goods_code>` | platform=interpark |
| `https://ticket.yes24.com/Perf/<perf_id>` | platform=yes24 |
| `https://ticket.yes24.com/New/Perf/Detail/View/<perf_id>` | platform=yes24 |
| `yes24:<id>` / `interpark:<id>` | shorthand |

### 2. 일정 조회 (`schedule`)

```bash
npx -y @nomadamas/k-skill@0 exec ticket-availability scripts/ticket_availability.py -- schedule "https://tickets.interpark.com/goods/26000541"
```

응답 — Interpark:
```json
{
  "platform": "interpark",
  "id": "26000541",
  "schedule": [
    {"date": "2026-05-13", "time": "14:30", "play_seq": "055"},
    {"date": "2026-05-14", "time": "19:30", "play_seq": "057"}
  ]
}
```

응답 — YES24:
```json
{
  "platform": "yes24",
  "id": "58026",
  "schedule": [
    {"date": "2026-05-16", "time_label": "1회", "id_time": "1432397"}
  ]
}
```

YES24 는 기본 3주 윈도우. 6개월 전체는 `--all-dates` 추가.

### 3. 잔여석 조회 (`seats`)

```bash
npx -y @nomadamas/k-skill@0 exec ticket-availability scripts/ticket_availability.py -- seats "interpark:26000541"
```

응답:
```json
{
  "platform": "interpark",
  "id": "26000541",
  "seats": {
    "2026-05-13|14:30|055": {
      "date": "2026-05-13", "time": "14:30", "play_seq": "055",
      "seats": [
        {"grade": "VIP석", "remain": 150},
        {"grade": "R석",  "remain": 36},
        {"grade": "S석",  "remain": 82},
        {"grade": "A석",  "remain": 71}
      ]
    }
  }
}
```

YES24 응답은 등급별 `price` (노출가) 도 포함:
```json
{"grade": "전석", "price": "110,000원", "remain": 2}
```

### 3-1. KBO 경기 정리 (`kbo`)

야구 goods 여러 개를 한 번에 받아 **구장명·경기명·일시**를 붙이고, 인원수 기준으로 등급을 걸러 예매 링크까지 정리한다. 내부적으로 goods 당 `summary` → `playSeq` → `REMAINSEAT` 순으로 공개 endpoint 만 호출한다.

```bash
npx -y @nomadamas/k-skill@0 exec ticket-availability scripts/ticket_availability.py -- \
  kbo interpark:26012601 interpark:26005455 \
  --stadium 잠실,고척 --min-remain 3 --exclude-wheelchair --text
```

옵션:

- `--min-remain N`: N석 이상 남은 등급만 남긴다 (일행 인원수를 그대로 넣는다)
- `--stadium 잠실,고척`: `placeName` 부분일치 필터
- `--exclude-wheelchair` / `--exclude-restricted-view`: 휠체어석·시야방해석 제외
- `--any-genre`: 기본은 `genreSubName == 야구` 인 상품만 남긴다
- `--text`: 사람이 읽는 요약. 기본은 JSON

JSON 출력에는 등급마다 `wheelchair`, `restricted_view` boolean 이 붙는다. 한 번에 최대 20개 goods.

**`--min-remain N`은 "N석이 붙어 있다"는 뜻이 아니다.** 등급별 잔여 *수* 만 보는 것이고 연석 여부는 이 스킬이 알 수 없다. 사용자에게 좌석도에서 직접 확인하라고 안내한다.

### 3-2. goods 코드를 구하는 방법

이 스킬은 **검색·목록 조회를 하지 않는다.** 2026-09-20 확인 기준:

- 인터파크 목록 API `/sports/goods`, `/sports/goods/period` 는 `X-Client-Id` / `X-Client-Secret` 를 요구하는 **비공개 endpoint** 다. 프런트 번들에 들어 있는 키를 꺼내 쓰는 것은 접근통제 우회이므로 하지 않는다.
- `tickets.interpark.com/robots.txt` 는 일반 봇에 `Disallow: /` 이다. 따라서 목록 페이지 HTML 스크래핑도 하지 않는다. (스킬이 호출하는 `api-ticketfront.interpark.com` 은 별도 호스트이며 goods 단위 공개 조회만 쓴다.)

그래서 코드는 이렇게 얻는다.

1. 사용자가 예매 페이지 URL 을 그대로 준다 (권장).
2. 에이전트가 웹 검색으로 해당 경기 예매 페이지를 찾아 URL 을 확보한다.
3. 상품명은 `<홈팀> vs <원정팀> (M.D)` 포맷이고 같은 홈팀의 홈경기 코드는 대체로 연속이지만, **연속 번호를 추측해서 조회하지 않는다** (열거 행위가 된다). 확보한 코드만 조회한다.

경기 일정 자체는 `kbo-results` 스킬로 확인한다.

### 4. 헬스체크 (`health`)

```bash
npx -y @nomadamas/k-skill@0 exec ticket-availability scripts/ticket_availability.py -- health
```

응답:
```json
{"yes24": {"status": 200, "ok": true}, "interpark": {"status": 200, "ok": true}}
```

## Output format

기본 출력은 들여쓰기 JSON. 파이프/스크립트용은 `--compact` 추가 (한 줄 JSON).

## Endpoints used

이 스킬이 호출하는 공개 endpoint 만:

| Platform | Method | URL |
|---|---|---|
| YES24 | POST | `https://ticket.yes24.com/New/Perf/Sale/Ajax/axPerfDay.aspx` |
| YES24 | POST | `https://ticket.yes24.com/NEw/Perf/Detail/Ajax/axPerfPlayTime.aspx` |
| YES24 | POST | `https://ticket.yes24.com/New/Perf/Detail/Ajax/axPerfRemainSeat.aspx` |
| Interpark | GET | `https://api-ticketfront.interpark.com/v1/goods/<id>/summary` |
| Interpark | GET | `https://api-ticketfront.interpark.com/v1/goods/<id>/playSeq` |
| Interpark | GET | `https://api-ticketfront.interpark.com/v1/goods/<id>/playSeq/PlaySeq/<seq>/REMAINSEAT` |

전부 비로그인 / 무인증. 헤더는 `User-Agent` + `Referer` + JSON `Accept` 만.

## Failure modes

- **YES24 `schedule` 결과 빈 배열**: 공연 ID 가 유효하지만 향후 3주(또는 6개월) 내 일정이 없음. ID 자체가 잘못된 경우와 구분되지 않으므로, 사용자에게 `--all-dates` 또는 다른 ID 확인을 안내한다.
- **Interpark `data: []`**: goods_code 가 지나갔거나 아직 오픈 전 / 비공개. 다른 ID 확인을 안내한다.
- **HTTP 4xx/5xx**: 차단/일시 장애. 우회 시도하지 않고 `http error` 출력 후 종료.
- **JSON 스키마 변경**: YES24 axPerfRemainSeat 는 HTML 응답을 정규식으로 파싱 — 사이트 갱신 시 영향 가능. `remain` 0 으로 잘못 보고될 수 있어 사용자에게 "조회 시각 기준" 이라고 표기.
- **공연 매진**: API 는 `remain: 0` 반환. 매진 표시.
- **`kbo` 에서 "야구 상품이 아니다" 로 건너뜀**: `genreSubName` 이 야구가 아닌 goods 다. 의도한 것이면 `--any-genre` 를 쓴다.
- **`kbo` 에서 구장 필터 불일치**: `placeName` 이 `--stadium` 문자열을 포함하지 않는다. 구장명은 `잠실야구장`, `고척스카이돔` 처럼 전체 이름이므로 부분 문자열로 넣는다.
- **`summary` 는 200 인데 `playSeq` 가 400**: 지난 경기이거나 판매가 끝난 goods 다.

## Response style

- 잔여석은 "조회 시각 기준" 으로 표현한다 (실시간 변동).
- "매크로", "선점", "오픈런", "자동 예매" 표현 금지 — 이 스킬은 조회 전용.
- 잔여석 수치 + 등급명 만 인용. 좌석 번호 / 좌석 위치는 노출하지 않는다.
- "지금 사라" 같은 행위 유도 금지 — 사용자가 직접 페이지에서 결제.

## Notes

- 본 스킬은 의도적으로 **예매 / 결제 / 좌석선택 / 로그인 자동화** 를 포함하지 않는다. 매크로를 통한 입장권 부정구매·판매는 공연법 §4조의2 (2023.9.22 시행) 에 의해 형사처벌 대상.
- 시크릿 / 키 / 로그인 세션 일체 사용하지 않는다.
- Rate limit: `seats` 명령은 회차별 순차 호출 — Interpark 0.3s, YES24 0.4s 간격. 100회차 짜리 공연이면 약 30s ~ 40s 소요. 짧은 모니터링 루프에 넣지 말 것.

## Done when

- 공연 URL 또는 `platform:id` 가 확인되었다.
- 일정 또는 잔여석 결과 JSON 을 반환하거나, 빈 결과 사유를 설명했다.
- 예매 / 결제 / 좌석 선택 기능을 자동화하지 않았다.
- 조회 시각 기준임을 안내했다.
