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

## transport: `delegate`

다른 스킬이 이미 담당하는 시스템이다. 레지스트리에는 **사용자를 올바른 스킬로 보내기 위해** 남긴다.

| provider id | 담당 스킬 | 이유 |
| --- | --- | --- |
| `foresttrip` | `foresttrip-vacancy` | 로그인·CSRF가 필요하고 조회 endpoint가 완전히 다르다 |

---

## 새 어댑터 추가 절차

1. **discovery 먼저.** 방법을 고정하기 전에 공개 입구, 브라우저에서 보이는 데이터 흐름, RSS/정적 JSON/모바일 페이지, 차단·빈 응답·로그인벽 실패 모드를 확인한다.
2. 예약 페이지 HTML에서 `/dzSmart/plugins/Reserv/`를 찾는다. 있으면 `PROVIDERS`에 항목만 추가하면 끝이다.
3. 다른 시스템이면 새 transport 함수를 만들고, `parse_*_html`을 **순수 함수**로 분리해 브라우저 없이 테스트 가능하게 둔다.
4. `tests/fixtures/`에 실제 캡처를 저장하고 파서 테스트를 추가한다.
5. **운영기관이 공공인지 먼저 확인한다.** 민간 플랫폼에 입점했어도 운영 주체가 지자체·공단·공사면 대상이고, 사설 캠핑장은 대상이 아니다.
6. 로그인·캡차·본인인증이 필요하면 **조회 경로로 넣지 말고** `delegate`로 표시하거나 아예 넣지 않는다.
7. `npm run generate:skill-stubs && npm run migrate:cli-assets && npm run sync:cli-skills && npm run ci`
