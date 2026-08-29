# 동물약국·동물용의약품 취급 약국 조회 가이드

`animal-pharmacy-search`는 홍익메디케어의 공개 Streamable HTTP MCP 서버를
직접 호출하는 읽기 전용 스킬이다.

- MCP endpoint: <https://hkmedi.co.kr/pharmacy-mcp>
- 인증/API key: 불필요
- proxy: 사용하지 않음
- 제공 기능: 지역별 동물약국, 동물용의약품 키워드 검색, 제품 취급 약국

## 데이터 출처와 한계

이 서버는 민간 동물용의약품 유통사 홍익메디케어가 운영한다.

- `find_animal_pharmacies`는 지역별 동물약국 디렉터리다.
- `find_pharmacies_by_product`는 **최근 6개월 안에 홍익메디케어에서 해당
  제품을 구매한 이력이 있는 약국**을 반환한다.
- 구매 이력은 과거 취급 근거이지 현재 재고·판매 가능 여부 보장이 아니다.
- 다른 유통사를 이용한 약국이나 전국 모든 동물약국을 포괄하지 않을 수 있다.
- 방문 전 약국에 전화해 제품명과 현재 재고를 확인해야 한다.

공공기관의 인허가 원장이나 공식 행정상태 확인 용도로 사용하지 않는다.

## 사용법

도구 목록:

```bash
npx -y @nomadamas/k-skill@0 exec animal-pharmacy-search scripts/animal_pharmacy_mcp.py -- tools
```

서울 강남구 동물약국:

```bash
npx -y @nomadamas/k-skill@0 exec animal-pharmacy-search scripts/animal_pharmacy_mcp.py -- \
  call find_animal_pharmacies \
  --arg city=서울 \
  --arg gu=강남구 \
  --arg limit=5
```

동물용의약품 키워드 검색:

```bash
npx -y @nomadamas/k-skill@0 exec animal-pharmacy-search scripts/animal_pharmacy_mcp.py -- \
  call search_product \
  --arg keyword=항생제
```

특정 제품 취급 약국:

```bash
npx -y @nomadamas/k-skill@0 exec animal-pharmacy-search scripts/animal_pharmacy_mcp.py -- \
  call find_pharmacies_by_product \
  --arg product_name=오리더밀 \
  --arg city=서울 \
  --arg limit=5
```

제품명이 중복되거나 정확 조회가 필요하면 `search_product` 결과의
`item_srl`을 사용한다.

## MCP 도구

| 도구 | 용도 | 주요 입력 |
| --- | --- | --- |
| `find_animal_pharmacies` | 지역별 동물약국 목록 | `city`, `gu`, `keyword`, `limit` |
| `search_product` | 제품명·분류·증상 태그 검색 | `keyword` |
| `find_pharmacies_by_product` | 최근 6개월 구매 이력 기반 취급 약국 | `item_srl` 또는 `product_name`, `city`, `gu`, `limit` |

## 안전 원칙

- 이 스킬은 동물약국과 제품 취급 근거를 조회할 뿐 진단·처방하지 않는다.
- 약의 선택, 용량, 투여 주기, 병용 여부는 수의사와 약사에게 확인한다.
- 증상이 위급하면 검색보다 동물병원 진료를 우선한다.
- 약국 전화번호와 주소는 공개 사업장 조회 목적에만 사용한다.

## 실패 대응

- 키워드는 2글자 이상 입력한다.
- 지역 결과가 없으면 `gu`를 빼고 시·도 단위로 넓힌다.
- 제품 결과가 없으면 제품명, 분류, 증상 태그를 바꾼다.
- 서버 연결 실패나 5xx는 민간 MCP의 일시 장애로 보고 무한 재시도하지 않는다.
- 현재 재고는 서버 응답으로 확정하지 않고 전화 확인을 안내한다.

## 검증 기록

2026-08-25 KST 라이브 스모크에서 다음을 확인했다.

- MCP server: `hkmedi-pharmacy-mcp` `1.0.0`
- `find_animal_pharmacies(city="서울", gu="강남구", limit=3)` 정상 응답
- `search_product(keyword="항생제")` 정상 응답
- `find_pharmacies_by_product(product_name="항생제", city="서울", limit=3)` 정상 응답
- 빈 제품 키워드는 JSON-RPC `-32602` 오류로 거부
