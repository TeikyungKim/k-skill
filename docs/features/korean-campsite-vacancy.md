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
| `thankq-jaraseom` | 자라섬캠핑장 | 가평군시설관리공단 | 불필요 |
| `donghae-mangsang` | 망상오토캠핑리조트 | 동해시시설관리공단 | **필요** |
| `donghae-mangsang2` | 망상제2오토캠핑장 | 동해시시설관리공단 | **필요** |
| `donghae-mureung` | 무릉힐링캠핑장 | 동해시시설관리공단 | **필요** |
| `donghae-chuam` | 추암오토캠핑장 | 동해시시설관리공단 | **필요** |

국립자연휴양림은 [자연휴양림 빈 객실 조회 가이드](foresttrip-vacancy.md)를 본다. 레지스트리에는 `foresttrip`이 **위임 표시**로만 들어 있어, 해당 provider를 지정하면 올바른 스킬을 안내하는 오류가 난다.

## 먼저 필요한 것

- Python 3.9+
- Playwright Chromium — **`dzsmart`(강릉 3곳)·`donghae`(동해 4곳) 경로에 필요하다.** 자라섬(`thankq`)은 표준 라이브러리만으로 조회된다
- [공통 설정 가이드](../setup.md) 완료

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
npx -y @nomadamas/k-skill@0 exec korean-campsite-vacancy scripts/run_campsite_vacancy.py -- --check-deps
```

## 필요한 환경변수

강릉 3곳과 자라섬은 아무 것도 필요 없다. 동해시 4곳만 회원 계정이 필요하다.

```
KSKILL_DONGHAE_ID
KSKILL_DONGHAE_PASSWORD
```

`~/.config/k-skill/secrets.env`에 넣고 셸에 올리거나, 사용자 환경변수로 등록한다. helper는 환경변수만 읽으며 평문 credential을 인자로 받지 않는다.

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

운영기관마다 예약 시스템이 달라 transport를 나눠 둔다.

### `dzsmart` — 강릉관광개발공사 3곳

강릉관광개발공사 사이트는 **dzSmart(denobiz)** 예약 플러그인을 쓴다.

1. `GET {entrypoint}/pub/reserv.do?tmonth=YYYYMM` 은 셸만 내려주고 캘린더는 비어 있다.
2. 페이지 JS가 `POST /dzSmart/plugins/Reserv/procedure/reserv-01-calendar.json` 을 호출해 존·일자·시즌 정보를 받는다.
3. 그 결과로 일자별 존 버튼이 렌더된다.

**2단계 endpoint를 out-of-band로 재현하면 일관되게 `503`이 돌아온다.** 쿠키 없는 요청, 세션 쿠키를 실은 요청, 심지어 같은 origin에서 브라우저가 성공시킨 것과 동일한 body를 보낸 요청까지 모두 503이었다. 그래서 helper는 **페이지를 실제로 로드하고 렌더된 DOM을 파싱**한다. Playwright가 필요한 이유다.

파싱은 `button[value="{zoneId}-{YY}-{MM}-{DD}-{seq}"]` 에서 날짜를 뽑고, `span.tit`(존 이름)과 `span.num`(잔여 면수 또는 `마감`)을 읽는다. `disabled` 속성이 있으면 숫자가 있어도 마감으로 처리한다. `8월 30일 (일)` 같은 로케일 문자열은 파싱하지 않는다.

### `thankq` — 자라섬캠핑장

가평군시설관리공단은 자체 시스템 대신 **땡큐캠핑** 이라는 민간 예약 플랫폼에 입점해 있다. 이쪽은 **브라우저가 필요 없다.** 평범한 form POST 하나로 끝난다.

```
POST https://m.thankqcamping.com/resv/axResCampSite.hbb
campseq=1&res_dt=20260905&res_edt=20260905&res_days=1&site_tp=&only_able_yn=
```

날짜는 `YYYYMMDD`여야 하고(`2026-09-05`로 보내면 500), 월 단위 조회 화면이 없어 **날짜당 1회**씩 요청한다. 응답 HTML의 `span.q_tip` 클래스가 상태를 결정한다 — `og`면 예약가능이고 `<em>` 안이 잔여 면수, 클래스가 없으면 `예약완료`, `red`면 `예약불가`다. 요금(`p.pri`)도 함께 온다.

응답에는 존마다 구버전 마크업이 주석으로 중복돼 들어오므로, 파서는 주석을 먼저 제거한 뒤 존을 센다.

> **플랫폼이 민간인 것과 캠핑장이 민간인 것은 다르다.** 등록 기준은 **운영기관**이다. 자라섬은 가평군시설관리공단이 운영하므로 대상이고, 같은 플랫폼의 사설 캠핑장은 대상이 아니다. dzSmart도 denobiz라는 민간 업체 제품이라는 점에서 사정이 같다. helper는 레지스트리에 등록된 id만 받으므로 `campseq`를 임의로 바꿔 사설 캠핑장을 훑을 경로가 없다.

### `donghae` — 동해시 4곳

동해시 통합예약은 **조회부터 로그인이 필요하다.** 비밀번호가 CryptoJS AES로 클라이언트 암호화되어 전송되므로 순수 HTTP로는 로그인이 안 된다(500). `foresttrip-vacancy`처럼 Playwright로 실제 폼을 구동한다.

응답은 `전통한옥:6|^|캐빈하우스:예약완료` 형태의 구분자 문자열이다. 존 이름에 `글램핑(4인)`처럼 괄호가 들어가므로 마지막 `:` 기준으로 나눈다.

> **CAPTCHA 위치가 중요하다.** 이 사이트의 캡차는 **예약 진행(1단계 → 다음)** 을 막는다. 잔여 현황 조회는 예약 페이지가 로드 시점에 스스로 발급한 PASS 키만 있으면 된다. 어댑터는 그 키를 재사용할 뿐이며 — `foresttrip-vacancy`가 자기 페이지의 CSRF 토큰을 쓰는 것과 같다 — 캡차를 풀거나 우회하지 않는다. `NOPASS` 응답이 오면 실패로 보고하고 멈춘다.

## 경계

예약 응답의 `sets`에 `captcha: true`, `smsauth: true`가 들어 있다. **예약 경로에는 캡차와 SMS 본인인증이 있으며 대신 통과하지 않는다.** 예약을 원하면 공식 예약 페이지 URL을 안내하고 사용자가 직접 진행한다.

취소표를 노린 반복 폴링도 하지 않는다. 한 번의 조회는 provider × 월 단위로 페이지를 1회씩만 연다.

## 실패 모드

- Playwright 미설치: `python3 -m pip install playwright && python3 -m playwright install chromium` (`dzsmart` 경로에만 해당)
- `thankq` 500 응답: 날짜 형식이 `YYYYMMDD`가 아니다
- `wait_for_selector` timeout: 예약 시스템 점검 중이거나 해당 월이 아직 오픈 전이다
- 결과가 전부 마감: 정상 동작이다. 성수기 주말은 대부분 마감이다
- 파서가 0건 반환: 사이트가 렌더링 구조를 바꿨을 가능성이 높다. `korean-campsite-vacancy/tests/fixtures/gtdc_yeongok_202608.html`와 실제 DOM을 비교한다
- 월 조회 상한 초과: 요청 날짜가 6개월을 넘게 걸쳐 있다. 날짜를 나눠 조회한다

## 새 캠핑장 추가

어댑터 추가 절차와 조사 근거는 아래로 확인한다.

```bash
npx -y @nomadamas/k-skill@0 read korean-campsite-vacancy references/PROVIDERS.md
```

예약 페이지 HTML에 `/dzSmart/plugins/Reserv/` 문자열이 있거나, 예약 버튼이 `thankqcamping.com`으로 나가면 `PROVIDERS` 레지스트리에 항목만 추가하면 된다. 다른 시스템이면 새 transport 함수를 만들고, 파서는 **순수 함수**로 분리해 브라우저 없이 테스트할 수 있게 둔다.

등록 전에 **운영기관이 공공인지 반드시 확인한다.**
