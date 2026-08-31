// Pure-function tests for the Naver browser adapter.
// Not picked up by `npm test` (CI discovers Node tests only under scripts/ and
// packages/k-skill-cli/test). Run directly:
//   node --test realty-listing-search/tests/naver_cdp.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { parseManwon, normalise, TRADE_CODE, TYPE_CODE } = require("../scripts/naver_cdp.js");

test("parseManwon reads Naver price strings", () => {
  assert.strictEqual(parseManwon("2억 1,500"), 21500);
  assert.strictEqual(parseManwon("3억"), 30000);
  assert.strictEqual(parseManwon("9,500"), 9500);
  assert.strictEqual(parseManwon("6억 5,000"), 65000);
  assert.strictEqual(parseManwon(null), null);
  assert.strictEqual(parseManwon(""), null);
});

test("normalise maps a 전세 article", () => {
  const row = {
    articleNo: "2646532380", articleName: "르피에드문정", tradeTypeName: "전세",
    realEstateTypeName: "오피스텔", dealOrWarrantPrc: "6억 5,000", rentPrc: null,
    area1: 84, area2: 42, floorInfo: "6/16", articleFeatureDesc: "전입신고가능",
    buildingName: "1동", latitude: "37.4854", longitude: "127.1221",
    realtorName: "가나공인중개사", articleConfirmYmd: "20260830", isSafeLessorOfHug: true,
    tagList: ["역세권"],
  };
  const it = normalise(row, "서울특별시 송파구 문정동");
  assert.strictEqual(it.provider, "naver");
  assert.strictEqual(it.sales_type, "전세");
  assert.strictEqual(it.deposit_manwon, 65000);
  assert.strictEqual(it.price_manwon, null);
  assert.strictEqual(it.area_m2, 42);          // 전용(area2), not 공급(area1)
  assert.strictEqual(it.area_pyeong, 12.71);
  assert.strictEqual(it.floor, "6/16");
  assert.strictEqual(it.confirmed_ymd, "20260830");
  assert.strictEqual(it.hug_safe_lessor, true);
  assert.match(it.url, /articleNo=2646532380/);
});

test("normalise moves 매매 price out of deposit", () => {
  const it = normalise(
    { articleNo: "1", tradeTypeName: "매매", dealOrWarrantPrc: "2억 1,500", area2: 27 }, "");
  assert.strictEqual(it.price_manwon, 21500);
  assert.strictEqual(it.deposit_manwon, null);
});

test("normalise keeps 월세 deposit and rent apart", () => {
  const it = normalise(
    { articleNo: "2", tradeTypeName: "월세", dealOrWarrantPrc: "3,000", rentPrc: "230", area2: 42 }, "");
  assert.strictEqual(it.deposit_manwon, 3000);
  assert.strictEqual(it.rent_manwon, 230);
});

test("filter codes match the documented Naver values", () => {
  assert.deepStrictEqual(TRADE_CODE, { 매매: "A1", 전세: "B1", 월세: "B2" });
  assert.strictEqual(TYPE_CODE["오피스텔"], "OPST");
  assert.strictEqual(TYPE_CODE["원룸"], TYPE_CODE["빌라"]);
});
