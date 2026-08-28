# 보이는 브라우저 예약 준비

`prepare_foresttrip_booking.py`는 특정 휴양림 전용이 아니다. 숲나들e의 휴양림 ID, 날짜, 시설 유형, 정확한 객실/사이트명을 받아 공식 예약 화면을 연다.

## 자동화 범위

- helper가 소유한 보이는 Playwright 브라우저 실행
- 공식 로그인과 NetFunnel 대기열
- 휴양림·날짜·시설 유형 검색
- 정확히 하나로 식별되는 시설 선택
- CAPTCHA/약관 수동 단계 표시
- 사용자가 직접 예약을 제출한 뒤 결제 화면 도달 감지

helper는 CAPTCHA를 해석하거나 입력하지 않고, 약관에 동의하거나 `예약`을 제출하지 않는다. 결제수단 선택, 결제 버튼, 결제 API, 본인확인, 전자서명도 자동화하지 않는다.

## 사전 확인

실행 직전에 read-only 조회를 다시 수행한다. 2박이면 체크인일과 그 다음 날에 같은 시설명이 모두 예약 가능해야 한다. 다음 입력을 최신 조회 결과에서 확정한다.

- 공식 휴양림 ID (`ID...`)
- 체크인과 체크아웃 (`YYYYMMDD`)
- 상품 유형 label 또는 option code
- 정확한 객실/사이트명

## 실행

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/prepare_foresttrip_booking.py -- \
  --forest-id ID02030054 \
  --check-in 20260906 \
  --check-out 20260907 \
  --facility-type "국민여가오토캠핑장" \
  --room-name "데크 01"
```

다른 휴양림은 네 입력만 바꿔 실행한다. 시설 label이 중복될 때만 `--facility-code`를 사용한다. 기본 브라우저는 helper가 소유하는 Playwright Chromium이며, `--browser-channel chrome` 또는 `--browser-channel msedge`로 바꿀 수 있다.

계정은 이미 주입된 `KSKILL_FORESTTRIP_ID`, `KSKILL_FORESTTRIP_PASSWORD`를 우선한다. 둘 중 하나가 없으면 `~/.config/k-skill/secrets.env`를 읽는다. 계정을 명령행 인자로 전달하거나 출력하지 않는다.

설치 상태와 입력만 확인하려면:

```bash
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/prepare_foresttrip_booking.py -- --check-deps
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/prepare_foresttrip_booking.py -- <필수 인자> --dry-run
```

## 수동 인계

시설 선택 후 `자동예약 방지숫자`가 보이면 정상 정지 상태다.

1. 휴양림, 이용일, 시설명, 금액을 확인한다.
2. CAPTCHA를 직접 입력한다.
3. 약관을 직접 읽고 동의 여부를 선택한다.
4. `예약`은 사용자가 직접 누른다. 이 단계에서 결제대기 예약이 만들어질 수 있다.
5. 결제 화면이 열리면 상단 안내와 터미널의 `PRE_PAYMENT_READY`를 확인한다.
6. helper는 결제를 누르지 않는다. 결제 여부는 사용자가 최종 확인 후 직접 결정한다.

창을 닫거나 터미널에서 `Ctrl+C`를 누르면 helper가 소유한 브라우저 세션이 종료된다.

## 실패 처리

- 객실 없음: 임의의 다른 시설을 선택하지 않고 새로 조회한다.
- 객실명 중복: 더 정확한 전체 이름으로 다시 실행한다.
- 공식 대기열 timeout: 우회하지 않고 열린 브라우저에서 기다리거나 종료한다.
- CAPTCHA/본인확인: 수동으로 처리하거나 중단한다.
- 화면 변경: `SAFE_STOP`으로 멈추고 payment endpoint를 추측해 직접 호출하지 않는다.
- 로그 URL: query string을 제거해 CSRF/NetFunnel token을 노출하지 않는다.
