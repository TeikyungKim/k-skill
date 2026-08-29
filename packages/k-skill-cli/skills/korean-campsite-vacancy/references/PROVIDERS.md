# Provider adapter reference

새 캠핑장 어댑터를 붙이기 전에 읽는다. 조사 근거와 확인 방법을 함께 남긴다.

---

## 왜 통합 API가 아니라 어댑터인가

전국 지자체 캠핑장의 **실시간 빈자리**를 제공하는 공식 통합 API는 없다. 전국 단위 공개 데이터는 메타데이터까지만 커버한다.

| 소스 | 제공 범위 | 실시간 빈자리 |
| --- | --- | --- |
| 한국관광공사 고캠핑 (`data.go.kr` 15101933) | 전국 야영장 목록·시설·좌표 | 없음 |
| 공유누리 (`eshare.go.kr`) | 국공립 야영장·공공자원 목록 | 없음 |
| 국립공원 예약시스템 (`reservation.knps.or.kr`) | 국립공원 야영장 | 자체 시스템 |
| 숲나들e (`foresttrip.go.kr`) | 국립자연휴양림 | 로그인 필요, 별도 스킬 |

따라서 **discovery(어떤 캠핑장이 있나)는 전국 데이터, vacancy(빈자리)는 provider adapter** 로 층을 나눈다.

고캠핑 API는 서비스 키가 필요하므로, 추후 discovery 기능을 붙인다면 repo 규칙에 따라 `k-skill-proxy` route로 편입한다. 반대로 아래 dzSmart 경로는 키가 필요 없으므로 **프록시를 거치지 않고 스킬에서 직접 호출한다.**

---

## transport: `dzsmart`

강릉관광개발공사(GTDC) 예약 사이트가 쓰는 **dzSmart(denobiz)** 예약 플러그인이다.

### 식별 방법

예약 페이지 HTML에 아래 문자열이 있으면 이 어댑터를 재사용할 수 있다.

```
/dzSmart/plugins/Reserv/
```

### 데이터 흐름 (2026-08-29 확인)

1. `GET {entrypoint}/pub/reserv.do?tmonth=YYYYMM` — 셸만 내려온다. 캘린더는 비어 있다.
2. 페이지 JS가 `POST /dzSmart/plugins/Reserv/procedure/reserv-01-calendar.json` (`actMode=month_state&month=YYYYMM`)을 호출한다.
3. 응답 JSON은 `zones`(존별 총 면수), `calendar`(일자별 시즌·요일), `sets`(예약 정책)를 담는다.
4. JS가 그 결과로 일자별 존 버튼을 렌더한다.

### 왜 JSON endpoint를 직접 부르지 않는가

**2단계 endpoint를 out-of-band로 재현하면 일관되게 `503`이 돌아온다.** 확인한 것:

- 쿠키 없는 `curl` → 503
- 세션 쿠키를 실어도 → 503
- 같은 origin(페이지 컨텍스트) 안에서 `fetch`로 **브라우저가 성공시킨 것과 동일한 body**를 보내도 → 503

파라미터 문제가 아니라 1회성 가드로 보인다. 그래서 어댑터는 **페이지를 실제로 로드하고 렌더된 DOM을 파싱**한다. 서버사이드 렌더가 아니므로 Playwright가 필요하다.

### 파싱 대상 DOM

```html
<dl class="isEnabled">
  <dt><span class="day">30</span><span class="date">8월 30일 (일)</span></dt>
  <dd><div class="season">준성수기주중</div></dd>
  <dd><ul>
    <li><button value="1-26-08-30-1" class="R-1-26-08-30">
      <span class="tit">A-대형데크</span><span class="num">17</span></button></li>
    <li><button value="4-26-08-30-1" class="R-4-26-08-30" disabled="">
      <span class="tit">D-카라반</span><span class="num">마감</span></button></li>
  </ul></dd>
</dl>
```

- `button[value]` = `{zoneId}-{YY}-{MM}-{DD}-{seq}` — **날짜를 여기서 뽑는다.** `8월 30일 (일)` 같은 로케일 문자열을 파싱하지 않는다
- `span.tit` = 존 이름, `span.num` = 잔여 면수 또는 `마감`
- `disabled` 속성 = 예약 불가. `num`이 숫자여도 `disabled`가 이기게 한다
- `div.season` = 시즌 구분. 요금 판단에 쓰인다

### 예약 정책 (`sets`)

`sets`에 `captcha: true`, `smsauth: true`가 들어 있다. **예약 경로에는 캡차와 SMS 본인인증이 있다.** 조회 전용 경계를 유지하는 근거다.

### 등록된 사이트

| provider id | 호스트 | 확인 |
| --- | --- | --- |
| `gtdc-yeongok` | `camping.gtdc.or.kr` | 존 A/B/C/D/E/G/H/I, 라이브 확인 완료 |
| `gtdc-badanaeum` | `autocamping.gtdc.or.kr` | 동일 dzSmart 구조, 존 A/B/C |
| `gtdc-ojuk` | `ojuk.gtdc.or.kr` | 동일 dzSmart 구조, 한옥 숙박 |

---

## transport: `thankq`

**땡큐캠핑(ThankQ Camping)** 은 민간 상용 예약 플랫폼이다. 자체 예약 시스템을 만들지 않는 지자체가 여기에 입점해 운영하는 경우가 있다.

> **플랫폼이 민간인 것과 캠핑장이 민간인 것은 다르다.** 이 레지스트리의 기준은 **운영기관**이다. 자라섬캠핑장은 가평군시설관리공단이 운영하므로 대상이고, 같은 플랫폼의 사설 캠핑장은 대상이 아니다. dzSmart도 denobiz라는 민간 업체 제품이라는 점에서 사정이 같다.

### 식별 방법

지자체 홈페이지의 예약 버튼이 `thankqcamping.com`으로 나가면 이 어댑터를 재사용할 수 있다. 캠핑장별 식별자는 예약 상세 URL의 `cseq` 값이다.

```
https://m.thankqcamping.com/resv/view.hbb?cseq=1     ← 자라섬 = 1
```

### 데이터 흐름 (2026-08-29 확인)

dzSmart와 달리 **브라우저가 필요 없다.** 평범한 form POST 하나로 끝난다.

```
POST https://m.thankqcamping.com/resv/axResCampSite.hbb
Content-Type: application/x-www-form-urlencoded; charset=UTF-8

campseq=1&res_dt=20260905&res_edt=20260905&res_days=1&site_tp=&only_able_yn=
```

- `res_dt` / `res_edt` 는 **`YYYYMMDD`** 다. `2026-09-05` 처럼 보내면 `500`이 돌아온다
- 하루치를 볼 때 `res_dt` 와 `res_edt` 는 같은 값이고 `res_days=1` 이다 (사이트 자체 기본 동작)
- 월 단위 조회 화면이 없다. 그래서 어댑터는 **날짜당 1회** 요청한다

응답은 JSON이 아니라 사이트 목록 HTML 조각이다.

### 파싱 대상 DOM

```html
<div class="site_div type2" onClick="goNoMemResAlert('113092','');">
  <span class="q_tip og">예약가능 <em>34</em></span>
  <p class="na">사이트 A</p>
  <p class="pri">45,000원</p>
</div>
```

- `span.q_tip` 의 클래스가 상태를 결정한다
  - `og` → 예약가능, `<em>` 안의 숫자가 잔여 면수
  - 클래스 없음 → `예약완료`
  - `red` → `예약불가`
- `p.na` = 존 이름, `p.pri` = 요금 (주말·주중이 다르다)

### 주의: 주석 처리된 중복 블록

응답에는 존마다 **구버전 마크업이 `<!--li> ... </li-->` 로 주석 처리되어 함께** 들어온다. 그대로 파싱하면 모든 존이 두 번 잡힌다. `parse_thankq_html` 은 주석을 먼저 제거한 뒤 `site_div` 단위로 나눈다.

### 등록된 사이트

| provider id | cseq | 캠핑장 | 운영기관 | 확인 |
| --- | --- | --- | --- | --- |
| `thankq-jaraseom` | 1 | 자라섬캠핑장 | 가평군시설관리공단 | 라이브 확인 완료 |

---

## transport: `maketicket`

스마틱스(smartix)의 **MakeTicket**(`forest.maketicket.co.kr`)을 여러 지자체가 임대해 쓴다. **로그인·캡차·대기열이 전부 없다.**

### 식별 방법

지자체 홈페이지의 예약 버튼이 `forest.maketicket.co.kr/ticket/{gd_seq}`로 나가면 이 어댑터를 재사용할 수 있다. `gd_seq`가 캠핑장 식별자다.

### 데이터 흐름 (2026-08-29 확인)

```
GET  /ticket/GD41                    → 페이지 JS에 idkey: "5M8190"
POST /camp/reserve/calendar.jsp      idkey=5M8190&gd_seq=GD41&yyyymmdd=20260901&sd_date=20260901
```

`yyyymmdd`로 임의 월을 요청할 수 있다. `idkey`는 운영자가 바꿀 수 있으므로 **레지스트리에 하드코딩하지 않고 매번 ticket 페이지에서 읽는다.**

### 파싱 대상 DOM

```html
<li class='s1'><a href='#' onclick='javascript:f_SelectDateZone( "20260901" , "CM000036" , "SD68940" , "1" , "2" );'>
  <span>2</span>컨테이너하우스(A동)</a></li>
<li class='s3 zero'><a href='#' onclick='javascript:f_SelectDateZone( "20260901" , "CM000038" , "SD68940" , "3" , "0" );'>
  <span>0</span>오토캠핑장(C동)</a></li>
```

- **첫 인자가 그 슬롯의 전체 날짜**다. `gmuc`처럼 위치로 월을 추론할 필요가 없다
- 마지막 인자 = 잔여 수. `0`이면 마감이다
- `<span>` 다음 텍스트가 존 이름. `카라반(B동)`처럼 괄호가 들어간다

달력에 없는 날짜는 예약 미오픈이거나 운영하지 않는 날짜다. **실패로 명시 보고**한다.

### 등록된 사이트

| provider id | gd_seq | 캠핑장 | 운영기관 | 확인 |
| --- | --- | --- | --- | --- |
| `maketicket-jangho` | GD41 | 장호비치캠핑장 | 삼척시 | 라이브 확인 완료 |
| `maketicket-hyangnam` | GD90 | 화성시향남오토캠핑장 | 화성도시공사 | 라이브 확인 완료(조회 시점 달력 비어 있음) |

> **공개 표면이 있으면 그쪽을 쓴다.** 화성 향남은 화성시 통합예약(`yeyak.hscity.go.kr`)에서는 조회부터 로그인 벽이지만, 같은 캠핑장이 MakeTicket에도 올라와 있고 그쪽은 공개다. 로그인 벽을 만나면 다른 공식 표면이 있는지 먼저 확인한다.

---

## transport: `gmuc`

광명도시공사 도덕산캠핑장이다. **레지스트리에서 가장 가벼운 경로** — 로그인도, 브라우저도, 파라미터도 필요 없다.

```
GET https://www.gmuc.co.kr/user/conn/campReserve.do
```

한 번의 GET이 서버사이드 렌더된 **두 달치(당월+익월)** 달력을 그대로 돌려준다.

### 파싱 대상 DOM

```html
<td>
  <div class="date">30</div>
  <div class="area"><a href="/user/conn/directLink.do?cTo=...">A구역 : 11</a></div>
  <div class="area_done"><a href="javascript:alert('...')">B구역 : 예약마감</a></div>
</td>
```

- `div.area` = 예약 가능, `이름 : 숫자`가 잔여 면수
- `div.area_done` = 마감. 숫자가 있어도 `area_done`이 이긴다
- `div.date` = 일자

### 월을 어떻게 아는가

**달력 옆에 월 캡션이 없다.** `2026년 8월` 같은 텍스트는 페이지 하단 별도 영역에 있고 표와 붙어 있지 않다. 이전/다음달 버튼은 `calCont()` JS로 이미 렌더된 두 표를 토글할 뿐이라 임의 월을 요청할 수도 없다.

그래서 파서는 **일자 시퀀스가 되감기는 지점**(…30, 31, 1, 2…)을 월 경계로 삼고, 호출자가 "첫 달 = 오늘의 달, 둘째 달 = 다음 달"을 넘겨준다. 연말 경계(202612 → 202701)도 같은 방식으로 처리된다.

### 2개월 창 밖 날짜

조회 범위를 벗어난 날짜는 **실패로 명시 보고한다.** 조용히 비우면 "빈자리 없음"으로 읽히기 때문이다.

```
! fetch failed: gmuc-dodeoksan 20261002 — 공개 예약현황이 당월+익월만 노출한다. 202608/202609 범위 밖이라 조회할 수 없다
```

### 주의: 추첨제 혼합

광명시민은 추첨, 그 외는 선착순이다. 잔여 면수가 선착순 사이트와 의미가 다를 수 있으므로 사용자에게 공식 안내 확인을 권한다.

### 등록된 사이트

| provider id | 캠핑장 | 운영기관 | 확인 |
| --- | --- | --- | --- |
| `gmuc-dodeoksan` | 도덕산캠핑장 | 광명도시공사 | 라이브 확인 완료 |

---

## transport: `donghae`

동해시 통합예약(`campingkorea.or.kr`)이다. 동해시시설관리공단이 캠핑장 4곳을 여기서 운영한다. **다른 transport와 달리 조회부터 회원 로그인이 필요하다.**

### 로그인

비로그인 상태로 예약 endpoint를 호출하면 이렇게 답한다.

```json
{"result":false,"message":"로그인 후 이용해 주십시오."}
```

로그인 폼은 `POST /login/ND_loginAction.do` (`userId`, `userPassword`)인데, **비밀번호가 CryptoJS AES로 클라이언트에서 암호화**된 뒤 전송된다(`userPassword=<base64 ciphertext>`). 순수 HTTP로 재현하면 `500`이 난다. 그래서 `foresttrip-vacancy`와 같이 **Playwright로 실제 폼을 구동**해 페이지 JS가 암호화하게 둔다.

credential은 `KSKILL_DONGHAE_ID` / `KSKILL_DONGHAE_PASSWORD` 환경변수로만 읽는다.

### 경계: CAPTCHA는 예약 단계에만 있다

이 사이트에는 CAPTCHA(`/user/reservation/ND_ncaptcha.do`, 입력 필드 `answer`)가 있다. 위치가 중요하다.

- **1단계 날짜선택 → "다음"** 으로 넘어갈 때 = 예약 진행. **여기가 CAPTCHA 구간이고 건드리지 않는다.**
- **잔여 현황 조회**(달력의 `예약현황보기`) = 예약 페이지가 로드 시점에 `sessionStorage.dhscamp_pass_RESV1`로 발급한 PASS 키만 있으면 된다.

확인한 것:

- `passResv1`를 비우고 호출 → `{"result":false,"value":"NOPASS: 디지털 패스권 확인에 실패하였습니다."}`
- 페이지가 스스로 발급한 키를 그대로 사용 → `{"result":true,"value":"전통한옥:6|^|..."}`

즉 어댑터는 **페이지가 자기에게 건네준 키를 재사용**할 뿐이다. `foresttrip-vacancy`가 자기 페이지의 CSRF 토큰을 재사용하는 것과 같다. 캡차를 풀거나 OCR하거나 우회하지 않는다. NOPASS가 돌아오면 **실패로 보고하고 멈춘다.**

### 데이터 흐름

```
POST /user/reservation/ND_selectFcltyCalendarDetail.do
trrsrtCode=1000&q_year=2026&q_month=08&qDay=30&passResv1=<page key>&passNfTime=<page key>
```

응답 `value`는 JSON이 아니라 구분자로 묶인 문자열이다.

```
전통한옥:6|^|캐빈하우스:예약완료|^|난바다:1|^|자동차캠핑장:24
```

- 구분자는 `|^|`, 각 조각은 `이름:상태`
- 상태가 숫자면 잔여 면수, `예약완료`면 마감
- 존 이름에 `글램핑(4인)`처럼 괄호가 들어가므로 **마지막 `:` 기준으로 나눈다**

### 예약창 오픈 여부 (중요)

동해시는 **이용일 30일 전 오전 11시**에 예약창을 연다. 그 전에도 상세 endpoint는 정상 응답하는데, **아직 아무도 예약할 수 없으므로 총 정원이 그대로 돌아온다.** 이걸 잔여 면수로 읽으면 "전 시설 여유"라는 정반대 결론이 난다.

2026-08-29 확인: 10월 2~5일을 조회하면 4일 내내 숫자가 완전히 동일했고 전 시설 정원과 일치했다.

그래서 어댑터는 상세 응답만 믿지 않고 **월 달력의 날짜별 라벨을 함께 읽는다.**

```
GET /user/reservation/BD_reservation.do?q_year=2026&q_month=10
```

`td` 셀의 두 번째 줄이 라벨이다.

| 라벨 | `booking_status` | 의미 |
| --- | --- | --- |
| `예약현황보기` | `open` | 예약창이 열려 있다. 숫자가 실제 잔여다 |
| `예약마감` | `full` | 그 날짜는 마감됐다 |
| `예약종료` | `closed` | 지난 날짜이거나 접수 종료 |
| (빈 값) | `not_open` | **예약창 미오픈. 숫자는 총 정원이다** |
| 그 외 | `unknown` | 사이트가 바뀐 것이다. 예약 가능으로 단정하지 않는다 |

확인 결과: 2026-09는 1~28일에 라벨이 있고 29·30일은 비어 있었다(오늘 기준 정확히 30일). 2026-10은 31일 전부 비어 있었다.

`open`이 아닌 날은 **숨기지 않고 그대로 보여주되** 모든 zone의 `available`을 `False`로 만들고 `status_note`를 붙인다. 사용자가 물어본 날짜를 조용히 없애는 것이 더 나쁘기 때문이다.

### 등록된 사이트

| provider id | trrsrtCode | 캠핑장 | 확인 |
| --- | --- | --- | --- |
| `donghae-mangsang` | 1000 | 망상오토캠핑리조트 | 라이브 확인 완료 |
| `donghae-mangsang2` | 2000 | 망상제2오토캠핑장 | 라이브 확인 완료 |
| `donghae-mureung` | 3000 | 무릉힐링캠핑장 | 라이브 확인 완료 |
| `donghae-chuam` | 4000 | 추암오토캠핑장 | 라이브 확인 완료 |

---

## transport: `delegate`

다른 스킬이 이미 담당하는 시스템이다. 레지스트리에는 **사용자를 올바른 스킬로 보내기 위해** 남긴다.

| provider id | 담당 스킬 | 이유 |
| --- | --- | --- |
| `foresttrip` | `foresttrip-vacancy` | 로그인·CSRF가 필요하고 조회 endpoint가 완전히 다르다 |

### 아직 어댑터가 없는 곳

| 대상 | 시스템 | 막힌 지점 |
| --- | --- | --- |
| 충주 목계솔밭 외 다수 | **미리해** (`mirihae.com`) | 모든 경로가 `cdn.mirihae.com:9443/entering.html` **웹대기(대기열)** 로 리다이렉트된다. 대기열 뒤에 자동 조회를 붙이지 않는다는 것이 이 스킬의 경계다. 재사용 가치는 가장 크지만(이포보·금은모래·다리안·충주 등 멀티테넌트) 보류한다 |
| 달서 별빛캠프 | **xticket** (`camp.xticket.kr`) | `shopEncode` 링크가 302 루프를 돈다. 세션 구조 조사 필요. 멀티테넌트로 보여 조사 가치는 있다 |
| 안산 화랑 오토캠핑장 | 인터파크 + **추첨제** | 선착순이 아니라 추첨이라 "잔여 면수" 모델이 맞지 않는다. 붙이려면 추첨 신청기간·발표일을 다루는 별도 모델이 필요하다 |
| 국립공원 야영장 전체 (태백산 소도 포함) | 국립공원 (`reservation.knps.or.kr`) | **NetFunnel 대기열.** 아래 참고 |
| 국립공원 야영장 | `reservation.knps.or.kr` | 미조사 |

---

### 대기열 게이트로 채택하지 않은 시스템

두 시스템은 커버리지가 크지만 **잔여 조회 자체가 대기열 뒤에 있다.** 이 스킬은 대기열 우회를 하지 않으므로 채택하지 않는다. 기술적으로 막힌 것이 아니라 **의도적으로 멈춘 것**이다.

**미리해 (`mirihae.com`)** — 이포보·금은모래·다리안·충주 목계솔밭 등 다수 지자체가 쓰는 멀티테넌트 플랫폼이다. 재사용 가치는 레지스트리에서 가장 크다. 그러나 모든 경로가 `cdn.mirihae.com:9443/entering.html`(웹 대기)로 리다이렉트된다.

**국립공원 (`reservation.knps.or.kr`)** — 전국 20개 국립공원 야영장을 한 곳에서 커버한다. 잔여현황 화면은 로그인 없이 열리고 엔드포인트도 단순하다.

```javascript
NetFunnel_Action({action_id:'reservation2'}, function(ev, ret){
    $.ajax({ type:'post', url:'/reservation/campsiteList.do',
             data:{ dept_id, dept_name, parent_dept_name, prd_ctg_id, isGreenpoint } });
});
```

`campsiteList.do` 호출이 **NetFunnel(상용 대기열 솔루션)로 감싸여** 있다. 이 래퍼를 건너뛰고 엔드포인트를 직접 부르는 것이 곧 대기열 우회다. 서버가 강제하는지 여부와 무관하게 하지 않는다.

두 곳 모두 사이트가 대기열을 푸는 방식으로 바뀌면 재검토한다.

## 조사 완료 목록 (2026-08-29)

행정안전부 「지자체·공공 운영 분야별 우수야영장 20개소」를 전수 조사한 결과다. **플랫폼 재사용은 여기까지가 끝**이라는 것이 결론이다. 남은 곳은 전부 지자체가 자체 시스템을 굴리거나, 대기열 뒤에 있거나, 상용 티켓 플랫폼이거나, 민간 운영이다. 앞으로는 **한 곳당 개별 조사 + 어댑터 1:1**이다.

### 커버 중 (7 / 20)

| 야영장 | 지자체 | 경로 |
| --- | --- | --- |
| 연곡해변 솔향기 캠핑장 | 강릉시 | `gtdc-yeongok` |
| 도덕산 캠핑장 | 광명시 | `gmuc-dodeoksan` |
| 향남 오토캠핑장 | 화성시 | `maketicket-hyangnam` |
| 월아산 자연휴양림 야영장 | 진주시 | `foresttrip-vacancy` (공립) |
| 백운산 자연휴양림 야영장 | 광양시 | `foresttrip-vacancy` (공립) |
| 제암산 자연휴양림 야영장 | 보성군 | `foresttrip-vacancy` (공립) |
| 장호비치캠핑장 (목록 외) | 삼척시 | `maketicket-jangho` |

숲나들e가 **국립뿐 아니라 공립 자연휴양림도 포함**한다는 점이 확인됐다. 자연휴양림 계열은 먼저 `foresttrip-vacancy`로 이름 조회를 해본다.

### 미커버와 사유

| 야영장 | 예약 시스템 | 사유 |
| --- | --- | --- |
| 태백산 국립공원 소도자동차 야영장 | 국립공원 `knps.or.kr` | NetFunnel 대기열 |
| 내원 자동차 야영장 (산청) | 국립공원 `knps.or.kr` | NetFunnel 대기열 |
| 목계솔밭 캠핑장 (충주) | 미리해 `mirihae.com` | 웹대기 게이트 |
| 라이프위드도그 캠핑장 (인제) | 투어비스·호텔패키지 등 | 민간 운영으로 보인다. 운영기관 기준에 맞지 않는다 |
| 별빛야영장 (영천) | 인터파크 티켓 | 상용 티켓 플랫폼 |
| 안산화랑 오토캠핑장 | 인터파크 + 추첨제 | 선착순이 아니라 추첨이라 "잔여 면수" 모델이 맞지 않는다 |
| 별난독서문화 체험장 캠핑장 (파주) | `pajubookcamp.com` | 도메인 DNS 미해결. 사이트 이전/폐쇄 추정 |
| 단호샌드파크 캠핑장 (안동) | `danhosand.or.kr` 자체 | 미조사. 개별 어댑터 필요 |
| 정읍시 국민여가 캠핑장 | 정읍시 통합예약 자체 | 미조사. 개별 어댑터 필요 |
| 송호관광지 캠핑장 (영동) | 영동군 통합예매 `yd21.go.kr` | 미조사. 개별 어댑터 필요 |
| 황산문화체육공원 국민여가 캠핑장 (양산) | `hscamping.yssisul.or.kr` 자체 | 추첨제. 개별 어댑터 필요 |
| 황매산 국민여가 캠핑장 (합천) | `camp850.com` 자체 | 미조사. 개별 어댑터 필요 |
| 수승대 야영장 (거창) | `geochang.go.kr` 자체 | 미조사. 개별 어댑터 필요 |
| 북암 농촌체험관 야영장 (보은) | 보은군 자체 (`*.boeun.go.kr`) | 미조사. 개별 어댑터 필요 |
| 달서 별빛캠프 캠핑장 (대구) | xticket `camp.xticket.kr` | `shopEncode` 링크가 302 루프. 세션 구조 조사 필요. 멀티테넌트로 보여 조사 가치는 있다 |

### 조사할 때 겪은 함정

- **검색 결과를 그대로 믿지 않는다.** 인제 라이프위드도그가 땡큐캠핑 `cseq=1578`로 검색됐지만, 실제로 열어보니 그 cseq는 **인제캠핑타운**이라는 다른 캠핑장이었고 민간 사업자였다. 등록 전에 반드시 해당 페이지를 열어 이름과 운영 주체를 확인한다.
- **로그인 벽을 만나면 다른 공개 표면을 찾는다.** 화성 향남은 화성시 통합예약에서 조회부터 막혀 미지원으로 기록했었지만, 같은 캠핑장이 MakeTicket에 공개로 올라와 있었다.
- **"국민여가 캠핑장"은 공통 시스템이 아니다.** 이름이 같아도(양산·합천·정읍) 각자 다른 자체 시스템을 쓴다.

## 새 어댑터 추가 절차

1. **discovery 먼저.** 방법을 고정하기 전에 공개 입구, 브라우저에서 보이는 데이터 흐름, RSS/정적 JSON/모바일 페이지, 차단·빈 응답·로그인벽 실패 모드를 확인한다.
2. 예약 페이지 HTML에서 `/dzSmart/plugins/Reserv/`를 찾는다. 있으면 `PROVIDERS`에 항목만 추가하면 끝이다.
3. 다른 시스템이면 새 transport 함수를 만들고, `parse_*_html`을 **순수 함수**로 분리해 브라우저 없이 테스트 가능하게 둔다.
4. `tests/fixtures/`에 실제 캡처를 저장하고 파서 테스트를 추가한다.
5. **운영기관이 공공인지 먼저 확인한다.** 민간 플랫폼에 입점했어도 운영 주체가 지자체·공단·공사면 대상이고, 사설 캠핑장은 대상이 아니다.
6. 로그인·캡차·본인인증이 필요하면 **조회 경로로 넣지 말고** `delegate`로 표시하거나 아예 넣지 않는다.
7. `npm run generate:skill-stubs && npm run migrate:cli-assets && npm run sync:cli-skills && npm run ci`
