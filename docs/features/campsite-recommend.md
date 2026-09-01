# 캠핑장 추천 순위 가이드

`foresttrip-vacancy`(숲나들e)와 `korean-campsite-vacancy`(지자체·공공)의 빈자리 조회
결과를 받아 **추천 순위로 정렬**하는 read-only 스킬이다. 조회는 vacancy 스킬이 하고,
이 스킬은 정렬만 한다.

## 왜 별도 스킬인가

- vacancy 스킬 둘은 사이트 단위 조회기라 크로스사이트 집계가 들어갈 자리가 없다.
- 순위 산식과 시설↔카카오 place id 매핑을 한 곳에서 관리해야 두 스킬 결과를 같은
  기준으로 비교할 수 있다.

## 순위 근거

카카오맵 공개 평점·평가수·리뷰수를 **베이지안 보정 평점 70% + 로그 정규화 리뷰
규모 30%**로 합산한다. 상수(사전평균 4.1603, 사전표본 10, 정규화 기준 979)는 판 간
비교를 위해 동결돼 있다. 자세한 산식·유래·한계는 스킬의
`npx -y @nomadamas/k-skill@0 read campsite-recommend references/SCORING.md` 참고.

카카오맵 순위는 자체 산정이며 공식 순위가 아니다. 사이트 크기, 전기, 샤워장 같은
시설 조건은 점수에 들어가지 않는다.

## 시설 매핑은 큐레이션만

시설 ↔ 카카오 place id 연결은 스킬에 동봉된 place-map.json(숲나들e 50곳 + 지자체
11곳에서 시작)에 사람이 확인해 넣은 항목만 쓴다. 자동 이름 검색 매칭은 하지
않는다 — 여수 봉황산휴양림에 충주 봉황휴양림 평점이 붙었던 오매핑이 계기다.
매핑에 없는 시설은 순위를 추측하지 않고 `unranked` 목록으로 분리된다.

## 사용 예

```bash
# 1) 빈자리 조회 (연박 필터 포함)
npx -y @nomadamas/k-skill@0 exec foresttrip-vacancy scripts/run_foresttrip_vacancy.py -- \
  --all --json --dates 20261002,20261003,20261004 --nights 3 --categories 02 > forest.json

# 2) 추천순 정렬 + 출발지 기준 자동차 거리·통행료
npx -y @nomadamas/k-skill@0 exec campsite-recommend scripts/run_campsite_recommend.py -- \
  --input forest.json --origin "신대방삼거리역" --text
```

## 데이터 경로와 한도

- 평점: `place-api.map.kakao.com/places/panel3/{id}` 공개 JSON (키 불필요, 브라우저형
  헤더 필요). 입력에 등장한 시설만 1회씩, 0.5초 간격, run 당 최대 120회, 24시간 캐시.
- 거리·통행료: k-skill-proxy의 Kakao Mobility route (`--origin` 지정 시에만), 7일 캐시.
- 사용자 시크릿 불필요.
