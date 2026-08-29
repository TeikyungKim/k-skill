# 정부지원 전수조사 가이드

`government-support-survey`는 K-Startup, 기업마당, 정보통신산업진흥원(NIPA),
한국콘텐츠진흥원(KOCCA), 중소기업기술개발사업 종합관리시스템(SMTECH)의 공개
지원사업 공고를 `k-skill-proxy`를 통해 하나의 형식으로 조회한다.

## 사용 목적

- 창업지원, 사업화 자금, R&D, 바우처, 입주공간, 경진대회 공고를 여러 포털에서 함께 찾기
- 소스별 수집 성공 여부를 확인해 조사 누락을 명시적으로 파악하기
- 회사·팀·프로젝트 조건에 따라 지원 가능성을 보수적으로 검토하기
- 후보 공고의 공식 URL에서 신청대상과 제외조건을 최종 확인하기

## 조회 방법

```bash
npx -y @nomadamas/k-skill@0 exec government-support-survey scripts/run_survey.py -- \
  --sources kstartup bizinfo nipa kocca smtech \
  --keyword "AI 바우처" \
  --max-pages 3
```

`--keyword`를 생략하면 요청한 소스의 공고를 넓게 수집한다. 응답의
`complete`가 `false`이면 일부 소스가 누락된 부분 결과이므로 소스별 `error`를
확인하고 공식 포털에서 수동 보완해야 한다.

## 결과

각 공고는 다음 필드를 제공한다.

- 출처와 공고 식별자
- 공고명과 지원 분야
- 주관기관
- 접수 시작일과 마감일
- 등록일
- 공식 상세 URL

제목과 목록 메타데이터만으로 지원 자격을 확정하지 않는다. 실제 신청 전에는
공식 상세 페이지와 공고문에서 업력, 지역, 기업 형태, 대표자 조건, 중복수혜
제한, 제출서류를 확인한다.

## 출처와 재배포 범위

구현은 MIT 라이선스인
[`djfksjd/ir-search`](https://github.com/djfksjd/ir-search)의 공개 포털 접근
경로와 fail-closed 원칙을 참고해 k-skill 관례로 재작성했다. 자세한 attribution은
`government-support-survey/references/NOTICE.md`에 기록되어 있다.

k-skill-proxy는 제목, 기관, 날짜, 식별자, 공식 URL 등 사실 메타데이터만
구조화한다. 기관별 이용조건과 제3자 권리가 다를 수 있는 공고 본문과
첨부파일은 저장하거나 미러링하지 않는다.
