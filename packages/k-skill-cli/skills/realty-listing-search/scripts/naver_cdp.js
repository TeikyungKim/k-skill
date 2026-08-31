#!/usr/bin/env node
/**
 * Naver 부동산(new.land) listing reader over a browser the user already opened.
 *
 * Why this exists: every `new.land.naver.com/api/*` path answers 429 to a plain
 * scripted HTTP client, and the `m.land` JSON endpoints answer 200 with null.
 * That is a bot block and this skill does not defeat it. What it does instead is
 * read the page the user is already allowed to see: attach to their browser over
 * the documented CDP endpoint, let the SPA make its own authenticated request,
 * and read the response body it received.
 *
 * Paging reuses the Authorization header the page itself attached, because the
 * article API returns 20 rows per page and the SPA only fetches more on scroll.
 * That header belongs to the same session that is already open on screen; it is
 * never minted, forged, or persisted.
 *
 * Requires Node 18+ for global fetch and Node 22+ for global WebSocket. No npm
 * dependencies, matching the rest of this skill.
 */
"use strict";

const CDP_URL = process.env.KSKILL_CHROME_CDP_URL || "http://127.0.0.1:9222";
const ORIGIN = "https://new.land.naver.com";
const SETTLE_MS = 14000;
const PAGE_LIMIT_DEFAULT = 3;

const TRADE_CODE = { 매매: "A1", 전세: "B1", 월세: "B2" };
const TYPE_CODE = {
  원룸: "VL:DDDGG:JWJT",
  빌라: "VL:DDDGG:JWJT",
  오피스텔: "OPST",
  아파트: "APT:PRE:ABYG:JGC",
};

function fail(reason, extra) {
  process.stdout.write(JSON.stringify({ status: "unavailable", reason, ...extra }, null, 1));
  process.exit(2);
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) out[argv[i].replace(/^--/, "")] = argv[i + 1];
  return out;
}

/** "2억 1,500" / "3억" / "9,500" -> 만원 단위 숫자 */
function parseManwon(text) {
  if (!text) return null;
  const s = String(text).replace(/,/g, "").trim();
  const m = s.match(/^(?:(\d+)억)?\s*(\d+)?$/);
  if (!m) return null;
  const eok = m[1] ? Number(m[1]) * 10000 : 0;
  const rest = m[2] ? Number(m[2]) : 0;
  if (!m[1] && !m[2]) return null;
  return eok + rest;
}

function normalise(a, region) {
  const trade = a.tradeTypeName || null;
  const deposit = parseManwon(a.dealOrWarrantPrc);
  const rent = parseManwon(a.rentPrc);
  const areaM2 = Number(a.area2 ?? a.area1) || null;
  return {
    provider: "naver",
    id: String(a.articleNo),
    sales_type: trade,
    property_type: a.realEstateTypeName || null,
    deposit_manwon: trade === "매매" ? null : deposit,
    rent_manwon: rent,
    price_manwon: trade === "매매" ? deposit : null,
    area_m2: areaM2 ? Math.round(areaM2 * 100) / 100 : null,
    area_pyeong: areaM2 ? Math.round((areaM2 / 3.305785) * 100) / 100 : null,
    floor: a.floorInfo || null,
    title: [a.articleName, a.articleFeatureDesc].filter(Boolean).join(" · ") || null,
    address: [region, a.buildingName].filter(Boolean).join(" ") || null,
    // Naver publishes the real pin, unlike 직방/다방 which jitter it ~100m.
    lat: a.latitude != null ? Number(a.latitude) : null,
    lng: a.longitude != null ? Number(a.longitude) : null,
    url: `${ORIGIN}/houses?articleNo=${a.articleNo}`,
    realtor: a.realtorName || null,
    confirmed_ymd: a.articleConfirmYmd || null,
    hug_safe_lessor: a.isSafeLessorOfHug ?? null,
    tags: a.tagList || [],
  };
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.onEvent = () => {};
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? reject(new Error(m.error.message)) : resolve(m.result);
      } else if (m.method) this.onEvent(m);
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const lat = Number(args.lat);
  const lng = Number(args.lng);
  const zoom = args.zoom || "15";
  const propertyType = args["property-type"] || "오피스텔";
  const tradeType = args["trade-type"] || "전세";
  const region = args.region || "";
  const maxPages = Number(args.pages || PAGE_LIMIT_DEFAULT);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) fail("missing_coordinates", { hint: "--lat/--lng 필요" });

  const a = TYPE_CODE[propertyType];
  const tradTp = TRADE_CODE[tradeType];
  if (!a || !tradTp) fail("unsupported_filter", { propertyType, tradeType });

  let targets;
  try {
    targets = await (await fetch(`${CDP_URL}/json/list`)).json();
  } catch (e) {
    fail("browser_not_reachable", {
      cdp_url: CDP_URL,
      hint: "CDP 포트를 연 Chrome이 필요하다. chrome.exe --remote-debugging-port=9222 --user-data-dir=<임시경로>",
      error: String(e.message || e),
    });
  }

  let target = targets.find((t) => t.type === "page" && t.url.includes("land.naver.com"));
  if (!target) target = targets.find((t) => t.type === "page");
  if (!target) fail("no_browser_page", { cdp_url: CDP_URL });

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = () => rej(new Error("ws open failed"));
  });
  const cdp = new Cdp(ws);

  let authHeader = null;
  let firstUrl = null;
  let firstReqId = null;
  cdp.onEvent = (m) => {
    if (m.method === "Network.requestWillBeSent" && m.params.request.url.includes("/api/articles?")) {
      const h = m.params.request.headers || {};
      authHeader = h.authorization || h.Authorization || authHeader;
      firstUrl = m.params.request.url;
    }
    if (m.method === "Network.responseReceived" && m.params.response.url.includes("/api/articles?")) {
      if (m.params.response.status === 200) firstReqId = m.params.requestId;
    }
  };

  await cdp.send("Network.enable");
  await cdp.send("Page.enable");
  const nav = `${ORIGIN}/houses?ms=${lat},${lng},${zoom}&a=${encodeURIComponent(a)}&e=RETAIL&tradTp=${tradTp}`;
  await cdp.send("Page.navigate", { url: nav });
  await new Promise((r) => setTimeout(r, SETTLE_MS));

  if (!firstReqId || !firstUrl) {
    ws.close();
    fail("no_article_request_observed", {
      navigated: nav,
      hint: "지도가 렌더될 때까지 기다렸는지, 해당 위치에 매물이 있는지 확인한다.",
    });
  }

  const items = [];
  let isMore = false;
  const regionName = region;
  const notes = [];

  // The SPA leaves `tradeType=` empty in its own request (the trade filter lives
  // in its client state), so replaying that URL verbatim returns 매매+전세+월세
  // mixed. Pin the trade code on the query instead -- same session, same auth,
  // just the filter the user actually asked for.
  const withTrade = (url, page) =>
    url.replace(/([?&]tradeType=)[^&]*/, `$1${tradTp}`).replace(/([?&]page=)\d+/, `$1${page}`);

  const fetchPage = async (page) => {
    const url = withTrade(firstUrl, page);
    const expr = `(async()=>{const r=await fetch(${JSON.stringify(url)},{headers:{accept:'application/json',authorization:${JSON.stringify(
      authHeader || ""
    )}}});if(!r.ok)return JSON.stringify({__err:r.status});return await r.text();})()`;
    const res = await cdp.send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    const raw = res.result && res.result.value;
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  };

  let page1 = authHeader ? await fetchPage(1) : null;
  if (!page1 || page1.__err) {
    // Fall back to the body the page already received (unfiltered by trade type).
    if (page1 && page1.__err) notes.push(`filtered_request_failed_http_${page1.__err}; fell back to page's own response`);
    const body = await cdp.send("Network.getResponseBody", { requestId: firstReqId });
    try {
      page1 = JSON.parse(body.body);
    } catch {
      ws.close();
      fail("article_body_unparseable", { navigated: nav });
    }
    notes.push("trade_type_filter_not_applied");
  }
  for (const row of page1.articleList || []) items.push(normalise(row, regionName));
  isMore = Boolean(page1.isMoreData);

  for (let page = 2; page <= maxPages && isMore && authHeader; page += 1) {
    const next = await fetchPage(page);
    if (!next || next.__err) break;
    for (const row of next.articleList || []) items.push(normalise(row, regionName));
    isMore = Boolean(next.isMoreData);
  }

  ws.close();
  process.stdout.write(
    JSON.stringify(
      {
        status: "ok",
        provider: "naver",
        transport: "browser-cdp",
        navigated: nav,
        cdp_url: CDP_URL,
        query: { region, property_type: propertyType, trade_type: tradeType, lat, lng, zoom },
        notes,
        count: items.length,
        has_more: isMore,
        items,
      },
      null,
      1
    )
  );
}

module.exports = { parseManwon, normalise, TRADE_CODE, TYPE_CODE };

if (require.main === module) {
  main().catch((e) => fail("naver_cdp_failed", { error: String((e && e.message) || e) }));
}
