# 지자체 캠핑장 빈자리 조회 가이드

지자체·공공기관이 운영하는 한국 캠핑장의 **빈자리(잔여 면수) 조회 자동화**다. 예약 신청, 결제, 캡차 처리는 하지 않는다.

## 왜 통합 API가 아닌가

전국 지자체 캠핑장의 **실시간 빈자리**를 제공하는 공식 통합 API는 존재하지 않는다. 전국 단위 공개 데이터는 메타데이터까지만 커버한다.

| 소스 | 제공 범위 | 실시간 빈자리 |
| --- | --- | --- |
| 한국관광공사 고캠핑 (`data.go.kr` 15101933) | 전국 야영장 목록·시설·좌표 | 없음 |
| 공유누리 (`eshare.go.kr`) | 국공립 야영장·공공자원 목록 | 없음 |
| 국립공원 예약시스템 (`reservation.knps.or.kr`) | 국립공원 야영장 | 자체 시스템 |
| 숲나들e (`foresttrip.go.kr`) | 국립자연휴양림 | 로그인 필요 |

그래서 이 스킬은 **provider adapter 레지스트리**를 두고 예약 시스템 단위로 어댑터를 늘린다. `delivery-tracking`의 carrier adapter와 같은 구조다.

## 이 기능으로 할 수 있는 일

- 등록된 지자체 캠핑장의 날짜별 존(zone)별 잔여 면수 조회
- 여러 캠핑장 동시 조회
- 존 이름 부분 일치 필터 (예: 글램핑, 카라반)
- 마감 포함/제외 전환
- 시즌 구분(성수기·준성수기·비수기) 확인
- JSON 또는 사람이 읽기 좋은 텍스트 출력

## 지원 대상

| provider id | 캠핑장 | 운영기관 | 로그인 |
| --- | --- | --- | --- |
| `gtdc-yeongok` | 연곡해변 솔향기캠핑장 | 강릉관광개발공사 | 불필요 |
| `gtdc-badanaeum` | 강릉바다내음캠핑장 | 강릉관광개발공사 | 불필요 |
| `gtdc-ojuk` | 강릉오죽한옥마을(한옥 숙박) | 강릉관광개발공사 | 불필요 |

국립자연휴양림은 [자연휴양림 빈 객실 조회 가이드](foresttrip-vacancy.md)를 본다. 레지스트리에는 `foresttrip`이 **위임 표시**로만 들어 있어, 해당 provider를 지정하면 올바른 스킬을 안내하는 오류가 난다.

## 먼저 필요한 것

- Python 3.9+
- Playwright Chromium
- [공통 설정 가이드](../setup.md) 완료

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- --check-deps
```

## 필요한 환경변수

없다. 등록된 조회 경로는 전부 로그인과 API 키가 필요 없다.

## 사용 예시

레지스트리 확인:

```bash
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- --list-providers
```

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

## 동작 방식

강릉관광개발공사 사이트는 **dzSmart(denobiz)** 예약 플러그인을 쓴다.

1. `GET {entrypoint}/pub/reserv.do?tmonth=YYYYMM` 은 셸만 내려주고 캘린더는 비어 있다.
2. 페이지 JS가 `POST /dzSmart/plugins/Reserv/procedure/reserv-01-calendar.json` 을 호출해 존·일자·시즌 정보를 받는다.
3. 그 결과로 일자별 존 버튼이 렌더된다.

**2단계 endpoint를 out-of-band로 재현하면 일관되게 `503`이 돌아온다.** 쿠키 없는 요청, 세션 쿠키를 실은 요청, 심지어 같은 origin에서 브라우저가 성공시킨 것과 동일한 body를 보낸 요청까지 모두 503이었다. 그래서 helper는 **페이지를 실제로 로드하고 렌더된 DOM을 파싱**한다. Playwright가 필요한 이유다.

파싱은 `button[value="{zoneId}-{YY}-{MM}-{DD}-{seq}"]` 에서 날짜를 뽑고, `span.tit`(존 이름)과 `span.num`(잔여 면수 또는 `마감`)을 읽는다. `disabled` 속성이 있으면 숫자가 있어도 마감으로 처리한다. `8월 30일 (일)` 같은 로케일 문자열은 파싱하지 않는다.

## 경계

예약 응답의 `sets`에 `captcha: true`, `smsauth: true`가 들어 있다. **예약 경로에는 캡차와 SMS 본인인증이 있으며 대신 통과하지 않는다.** 예약을 원하면 공식 예약 페이지 URL을 안내하고 사용자가 직접 진행한다.

취소표를 노린 반복 폴링도 하지 않는다. 한 번의 조회는 provider × 월 단위로 페이지를 1회씩만 연다.

## 실패 모드

- Playwright 미설치: `python3 -m pip install playwright && python3 -m playwright install chromium`
- `wait_for_selector` timeout: 예약 시스템 점검 중이거나 해당 월이 아직 오픈 전이다
- 결과가 전부 마감: 정상 동작이다. 성수기 주말은 대부분 마감이다
- 파서가 0건 반환: 사이트가 렌더링 구조를 바꿨을 가능성이 높다. `korean-campsite-vacancy/tests/fixtures/gtdc_yeongok_202608.html`와 실제 DOM을 비교한다
- 월 조회 상한 초과: 요청 날짜가 6개월을 넘게 걸쳐 있다. 날짜를 나눠 조회한다

## 새 캠핑장 추가

어댑터 추가 절차와 조사 근거는 아래로 확인한다.

```bash
npx -y @nomadamas/k-skill@0 read korean-campsite-vacancy references/PROVIDERS.md
```

예약 페이지 HTML에 `/dzSmart/plugins/Reserv/` 문자열이 있으면 `PROVIDERS` 레지스트리에 항목만 추가하면 된다. 다른 시스템이면 새 transport 함수를 만들고, 파서는 **순수 함수**로 분리해 브라우저 없이 테스트할 수 있게 둔다.
