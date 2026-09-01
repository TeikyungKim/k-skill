# 직방·다방 매물 검색 가이드

직방·다방의 **공개 JSON 데이터 표면**으로 한국 부동산 매물(호가)을 지역·거래유형·
보증금 기준으로 통합 검색하는 read-only 스킬이다. 봇 차단이 걸린 네이버페이
부동산은 스크래핑하지 않고 **공식 딥링크**를 만들어 준다.

## 이 기능으로 할 수 있는 일

- 지역 키워드로 직방·다방 매물을 한 번에 검색 (전세·월세·매매, 원룸·빌라·오피스텔·아파트)
- 보증금·월세 상한 등 예산 조건 필터
- provider 선택 (`--providers zigbang,dabang`)
- 네이버페이 부동산 공식 딥링크 생성, 브라우저 조회 시 입주가능일(`--naver-move-in`) 확인
- JSON 또는 사람용 텍스트 출력

## 사용 예

```bash
# 어댑터 레지스트리 확인
npx -y @nomadamas/k-skill@0 exec realty-listing-search scripts/run_realty_listing_search.py -- providers

# 기본 검색 (전세, 원룸+빌라, 직방+다방)
npx -y @nomadamas/k-skill@0 exec realty-listing-search scripts/run_realty_listing_search.py -- \
  search --region "서울 동작구 상도동" --deal 전세 --deposit-max 30000
```

자세한 입력값·데이터 표면·실패 모드는 스킬 instruction을 따른다:

```bash
npx -y @nomadamas/k-skill@0 instruct realty-listing-search
```

## 경계

- 조회 전용이다. 문의 발송, 예약, 계약 진행은 하지 않는다.
- 관리비 단위는 provider마다 다르며 어댑터가 만원 단위로 정규화한다.
- 네이버페이 부동산은 봇 차단 표면이라 직접 크롤링하지 않는다. 딥링크와
  (사용자가 띄운 브라우저를 통한) 화면 확인까지만 지원한다.
- 사용자 시크릿 불필요.
