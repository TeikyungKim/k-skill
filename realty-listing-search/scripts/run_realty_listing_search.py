#!/usr/bin/env python3
"""Read-only listing (호가) search across Korean realty portals.

Each portal exposes a different public surface, so this helper keeps one
*provider adapter* per portal and normalises every result into a single item
shape. The same structure as ``korean-campsite-vacancy`` and the carrier
adapters in ``delivery-tracking``.

Adapters implemented today:

``zigbang``
    Fully open JSON API on ``apis.zigbang.com``. No auth, no custom headers.
    Region -> lat/lng via ``/v2/search``, lat/lng -> geohash(5), geohash ->
    item ids per property type, then one batched POST for the summaries.

``dabang``
    JSON API on ``www.dabangapp.com``. No auth, but the server rejects any
    request that omits the three static ``D-*`` headers the web client sends,
    and it requires a *fully populated* ``filters`` object -- a partial filter
    returns HTTP 400 listing the missing keys.

``naver``
    네이버페이 부동산 has no usable *plain-HTTP* read surface: every
    ``new.land.naver.com/api/*`` path answers ``429 TOO_MANY_REQUESTS`` on the
    first request, and the ``m.land.naver.com`` JSON endpoints answer ``200``
    with ``null`` / empty ``result``. That is a bot block and this skill does
    not defeat it. With ``--naver-browser`` it instead attaches to a browser the
    user has already opened (documented CDP endpoint), lets the page make its
    own authenticated request, and reads the response body -- see
    ``naver_cdp.js``. Without a browser it falls back to emitting the official
    deep link.

The helper is read-only: it never logs in, never contacts an agent, never
places an inquiry, and never solves a captcha or bot check.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):  # pragma: no cover - platform guard
    sys.stdout.reconfigure(encoding="utf-8")

USER_AGENT = "Mozilla/5.0 (compatible; k-skill realty-listing-search; +https://github.com/NomaDamas/k-skill)"
DEFAULT_TIMEOUT = 25
PYEONG_PER_M2 = 3.305785
# apis.zigbang.com rejects >15: "itemIds must contain no more than 15 elements"
MAX_DETAIL_BATCH = 15

TRADE_TYPES = ("전세", "월세", "매매")
PROPERTY_TYPES = ("원룸", "빌라", "오피스텔", "아파트")

# ---------------------------------------------------------------------------
# provider registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provider:
    """One realty portal entry in the adapter registry."""

    id: str
    name: str
    operator: str
    entrypoint: str
    transport: str
    auth: str
    property_types: tuple[str, ...]
    note: str = ""
    scrapes: bool = True


PROVIDERS: dict[str, Provider] = {
    "zigbang": Provider(
        id="zigbang",
        name="직방",
        operator="주식회사 직방",
        entrypoint="https://www.zigbang.com",
        transport="zigbang-public-json",
        auth="none",
        property_types=("원룸", "빌라", "오피스텔"),
        note="apis.zigbang.com 공개 JSON. 헤더·키 불필요. 아파트는 별도 단지 API라 미지원.",
    ),
    "dabang": Provider(
        id="dabang",
        name="다방",
        operator="주식회사 스테이션3",
        entrypoint="https://www.dabangapp.com",
        transport="dabang-web-json",
        auth="none (static D-* headers required)",
        property_types=("원룸", "빌라", "오피스텔", "아파트"),
        note="D-Api-Version/D-App-Version/D-Call-Type 헤더와 완전한 filters 객체가 필수.",
    ),
    "naver": Provider(
        id="naver",
        name="네이버페이 부동산",
        operator="네이버",
        entrypoint="https://new.land.naver.com",
        transport="browser-cdp (fallback: link-only)",
        auth="사용자가 연 브라우저 세션",
        property_types=("원룸", "빌라", "오피스텔", "아파트"),
        note=(
            "스크립트 HTTP는 전 경로 429로 차단된다. 우회하지 않고, 사용자가 CDP로 연 "
            "브라우저에서 페이지 자신의 응답을 읽는다. 브라우저가 없으면 공식 딥링크만 만든다."
        ),
        scrapes=True,
    ),
}

DEFAULT_PROVIDERS = ("zigbang", "dabang")


# ---------------------------------------------------------------------------
# http helpers
# ---------------------------------------------------------------------------


def _request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    hdr = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _to_pyeong(m2: float | None) -> float | None:
    if not m2:
        return None
    return round(float(m2) / PYEONG_PER_M2, 2)


def _num(value: Any) -> float | None:
    """Portal fields arrive as str or int depending on the endpoint."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# geohash (stdlib only -- no external dependency)
# ---------------------------------------------------------------------------

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_encode(lat: float, lon: float, precision: int = 5) -> str:
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    bit = 0
    ch = 0
    even = True
    out: list[str] = []
    while len(out) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon > mid:
                ch |= 1 << (4 - bit)
                lon_range[0] = mid
            else:
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat > mid:
                ch |= 1 << (4 - bit)
                lat_range[0] = mid
            else:
                lat_range[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_B32[ch])
            bit = 0
            ch = 0
    return "".join(out)


# ---------------------------------------------------------------------------
# region resolution
# ---------------------------------------------------------------------------


@dataclass
class Region:
    query: str
    name: str
    full_name: str
    lat: float
    lng: float
    source: str
    code: str | None = None


def resolve_region_zigbang(query: str) -> list[Region]:
    url = "https://apis.zigbang.com/v2/search?" + urllib.parse.urlencode(
        {"leaseYn": "N", "q": query, "serviceType": "원룸"}
    )
    payload = _request(url, headers={"Referer": "https://www.zigbang.com/"})
    out: list[Region] = []
    for item in payload.get("items") or []:
        if item.get("type") != "address":
            continue
        lat, lng = _num(item.get("lat")), _num(item.get("lng"))
        if lat is None or lng is None:
            continue
        src = item.get("_source") or {}
        out.append(
            Region(
                query=query,
                name=item.get("name") or query,
                full_name=item.get("description") or item.get("name") or query,
                lat=lat,
                lng=lng,
                source="zigbang",
                code=src.get("법정동코드"),
            )
        )
    return out


DABANG_HEADERS = {
    "D-Api-Version": "5.0.0",
    "D-App-Version": "1",
    "D-Call-Type": "web",
    "Referer": "https://www.dabangapp.com/map/onetwo",
}


def resolve_region_dabang(query: str) -> list[Region]:
    url = "https://www.dabangapp.com/api/v5/loc/search/region?" + urllib.parse.urlencode(
        {"searchKeyword": query}
    )
    payload = _request(url, headers=DABANG_HEADERS)
    result = payload.get("result") or {}
    out: list[Region] = []
    for item in result.get("list") or []:
        loc = item.get("location") or []
        if len(loc) < 2:
            continue
        out.append(
            Region(
                query=query,
                name=item.get("name") or query,
                full_name=item.get("fullName") or item.get("name") or query,
                lat=_num(loc[1]) or 0.0,
                lng=_num(loc[0]) or 0.0,
                source="dabang",
                code=item.get("code"),
            )
        )
    return out


def pick_region(query: str, prefer: str | None = None) -> tuple[Region | None, list[Region], list[str]]:
    """Resolve a Korean place name to coordinates.

    Both geocoders are public and key-free, so try zigbang first and fall back
    to dabang. ``prefer`` narrows same-name 동 across cities (e.g. "성남").
    """
    errors: list[str] = []
    candidates: list[Region] = []
    for fn in (resolve_region_zigbang, resolve_region_dabang):
        try:
            candidates.extend(fn(query))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
            errors.append(f"{fn.__name__}: {exc}")
    if not candidates:
        return None, [], errors
    if prefer:
        narrowed = [c for c in candidates if prefer in c.full_name]
        if narrowed:
            return narrowed[0], candidates, errors
    exact = [c for c in candidates if c.name == query] or list(candidates)
    # Same tie-break as daangn-realty-search: exact name match, then the
    # metropolitan areas, then whatever the portal returned first. Without this
    # "문정동" resolves to 경상북도 영주시 문정동 instead of 서울 송파구.
    exact.sort(key=lambda c: _metro_rank(c.full_name))
    return exact[0], candidates, errors


METRO_ORDER = ("서울특별시", "경기도", "인천광역시")


def _metro_rank(full_name: str) -> int:
    for idx, metro in enumerate(METRO_ORDER):
        if full_name.startswith(metro):
            return idx
    return len(METRO_ORDER)


# ---------------------------------------------------------------------------
# normalised item
# ---------------------------------------------------------------------------


def make_item(
    *,
    provider: str,
    item_id: Any,
    sales_type: str | None,
    deposit: float | None,
    rent: float | None,
    price: float | None,
    area_m2: float | None,
    floor: str | None,
    title: str | None,
    address: str | None,
    url: str,
    property_type: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "provider": provider,
        "id": str(item_id),
        "sales_type": sales_type,
        "property_type": property_type,
        "deposit_manwon": int(deposit) if deposit is not None else None,
        "rent_manwon": int(rent) if rent is not None else None,
        "price_manwon": int(price) if price is not None else None,
        "area_m2": round(area_m2, 2) if area_m2 is not None else None,
        "area_pyeong": _to_pyeong(area_m2),
        "floor": floor,
        "title": title,
        "address": address,
        # Both portals jitter the pin (~100m) until you contact the agent, so
        # treat this as approximate -- good enough to rank by station distance.
        "lat": round(lat, 6) if lat is not None else None,
        "lng": round(lng, 6) if lng is not None else None,
        "url": url,
    }
    if extra:
        item.update(extra)
    return item


# ---------------------------------------------------------------------------
# zigbang adapter
# ---------------------------------------------------------------------------

ZIGBANG_ENDPOINT = {
    "원룸": "onerooms",
    "빌라": "villas",
    "오피스텔": "officetels",
}
ZIGBANG_URL_SEGMENT = {
    "원룸": "oneroom",
    "빌라": "villa",
    "오피스텔": "officetel",
    "아파트": "apartment",
}


def zigbang_item_ids(geohash: str, property_type: str, trade_types: list[str]) -> list[int]:
    endpoint = ZIGBANG_ENDPOINT[property_type]
    params: list[tuple[str, str]] = [("geohash", geohash), ("domain", "zigbang")]
    for idx, trade in enumerate(trade_types):
        params.append((f"salesTypes[{idx}]", trade))
    url = f"https://apis.zigbang.com/house/property/v1/items/{endpoint}?" + urllib.parse.urlencode(params)
    payload = _request(url, headers={"Referer": "https://www.zigbang.com/"})
    return [i["id"] for i in (payload.get("items") or []) if i.get("id") is not None]


def zigbang_summaries(item_ids: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for start in range(0, len(item_ids), MAX_DETAIL_BATCH):
        chunk = item_ids[start : start + MAX_DETAIL_BATCH]
        body = json.dumps({"itemIds": chunk}).encode("utf-8")
        payload = _request(
            "https://apis.zigbang.com/house/property/v1/items/list",
            headers={"Content-Type": "application/json", "Referer": "https://www.zigbang.com/"},
            data=body,
        )
        out.extend(payload.get("items") or [])
    return out


def zigbang_search(region: Region, opts: argparse.Namespace) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    errors: list[str] = []
    sources: list[str] = []
    geohash = geohash_encode(region.lat, region.lng, opts.geohash_precision)
    types = [t for t in opts.property_types if t in ZIGBANG_ENDPOINT]
    ids: list[int] = []
    for ptype in types:
        try:
            found = zigbang_item_ids(geohash, ptype, opts.trade_types)
            ids.extend(found)
            sources.append(
                f"zigbang {ptype}: /house/property/v1/items/{ZIGBANG_ENDPOINT[ptype]}?geohash={geohash} -> {len(found)}건"
            )
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
            errors.append(f"zigbang {ptype}: {exc}")
    ids = list(dict.fromkeys(ids))
    if not ids:
        return [], errors, sources
    try:
        summaries = zigbang_summaries(ids)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
        errors.append(f"zigbang detail: {exc}")
        return [], errors, sources
    return [normalise_zigbang(s) for s in summaries], errors, sources


def format_floor(floor: Any, building_floor: Any = None) -> str | None:
    """Zigbang mixes numeric floors ("4") with labels ("반지하", "옥탑")."""
    if floor in (None, ""):
        return None
    text = str(floor)
    head = f"{text}층" if text.isdigit() else text
    if building_floor in (None, ""):
        return head
    top = str(building_floor)
    return f"{head}/{top}층" if top.isdigit() else f"{head}/{top}"


def normalise_zigbang(raw: dict[str, Any]) -> dict[str, Any]:
    service = raw.get("service_type") or ""
    segment = ZIGBANG_URL_SEGMENT.get(service, "oneroom")
    sales = raw.get("sales_type")
    deposit = _num(raw.get("deposit"))
    rent = _num(raw.get("rent"))
    exclusive = (raw.get("전용면적") or {}).get("m2")
    area = _num(exclusive) or _num(raw.get("size_m2"))
    floor_label = format_floor(raw.get("floor_string") or raw.get("floor"), raw.get("building_floor"))
    return make_item(
        provider="zigbang",
        item_id=raw.get("item_id"),
        sales_type=sales,
        deposit=deposit if sales != "매매" else None,
        rent=rent,
        price=deposit if sales == "매매" else None,
        area_m2=area,
        floor=floor_label,
        title=raw.get("title"),
        address=raw.get("address1") or raw.get("address"),
        url=f"https://www.zigbang.com/home/{segment}/items/{raw.get('item_id')}",
        property_type=service or None,
        lat=_num((raw.get("location") or {}).get("lat")),
        lng=_num((raw.get("location") or {}).get("lng")),
        extra={
            "manage_cost_manwon": _num(raw.get("manage_cost")),
            "registered_at": raw.get("reg_date"),
        },
    )


# ---------------------------------------------------------------------------
# dabang adapter
# ---------------------------------------------------------------------------

DABANG_CATEGORY = {
    "원룸": "one-two",
    "빌라": "one-two",
    "오피스텔": "officetel",
    "아파트": "apt",
}
DABANG_SELLING = {"전세": "LEASE", "월세": "MONTHLY_RENT", "매매": "SELL"}

_DABANG_COMMON = {
    "depositRange": {"min": 0, "max": 999999},
    "priceRange": {"min": 0, "max": 999999},
    "isIncludeMaintenance": False,
    "pyeongRange": {"min": 0, "max": 50},
    "useApprovalDateRange": {"min": 0, "max": 999999},
    "isShortLease": False,
}


def dabang_filters(category: str, trade_types: list[str]) -> dict[str, Any]:
    """Dabang rejects a partial filter object with HTTP 400.

    The defaults below mirror ``filter-init-chunk`` in the web bundle; each
    category has its own required key set.
    """
    selling = [DABANG_SELLING[t] for t in trade_types if t in DABANG_SELLING]
    base: dict[str, Any] = dict(_DABANG_COMMON)
    base["sellingTypeList"] = selling or ["LEASE", "MONTHLY_RENT"]
    if category == "one-two":
        base.update(
            {
                "roomFloorList": ["GROUND_FIRST", "GROUND_SECOND_OVER", "SEMI_BASEMENT", "ROOFTOP"],
                "roomTypeList": ["ONE_ROOM", "TWO_ROOM"],
                "canParking": False,
                "hasElevator": False,
                "hasPano": False,
                "isDivision": False,
                "isDuplex": False,
            }
        )
        return base
    base["tradeRange"] = {"min": 0, "max": 999999}
    base["roomCountList"] = ["ONE_ROOM", "TWO_ROOM", "THREE_ROOM", "FOUR_ROOM"]
    if category == "officetel":
        base.update(
            {
                "parkingNumRange": {"min": 0, "max": 999999},
                "canParking": False,
                "hasElevator": False,
                "hasPano": False,
            }
        )
    elif category == "apt":
        base.update(
            {
                "householdNumRange": {"min": 0, "max": 999999},
                "parkingNumRange": {"min": 0, "max": 999999},
                "hasTakeTenant": False,
            }
        )
    return base


def dabang_bbox(lat: float, lng: float, radius_km: float) -> dict[str, Any]:
    dlat = radius_km / 111.0
    dlng = radius_km / 88.0  # ~cos(37.5deg) corrected degrees-per-km for Korea
    return {
        "sw": {"lat": round(lat - dlat, 6), "lng": round(lng - dlng, 6)},
        "ne": {"lat": round(lat + dlat, 6), "lng": round(lng + dlng, 6)},
    }


def dabang_search(region: Region, opts: argparse.Namespace) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    errors: list[str] = []
    sources: list[str] = []
    items: list[dict[str, Any]] = []
    bbox = dabang_bbox(region.lat, region.lng, opts.radius_km)
    categories = list(dict.fromkeys(DABANG_CATEGORY[t] for t in opts.property_types if t in DABANG_CATEGORY))
    for category in categories:
        filters = dabang_filters(category, opts.trade_types)
        for page in range(1, opts.pages + 1):
            qs = urllib.parse.urlencode(
                {
                    "bbox": json.dumps(bbox, separators=(",", ":"), ensure_ascii=False),
                    "filters": json.dumps(filters, separators=(",", ":"), ensure_ascii=False),
                    "useMap": "naver",
                    "zoom": 15,
                    "page": page,
                }
            )
            url = f"https://www.dabangapp.com/api/v5/room-list/category/{category}/bbox?{qs}"
            try:
                payload = _request(url, headers=DABANG_HEADERS)
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
                errors.append(f"dabang {category} p{page}: {exc}")
                break
            result = payload.get("result") or {}
            rooms = result.get("roomList") or []
            items.extend(normalise_dabang(r) for r in rooms)
            if page == 1:
                sources.append(
                    f"dabang {category}: /api/v5/room-list/category/{category}/bbox -> total {result.get('total')}건"
                )
            if not result.get("hasMore"):
                break
    return items, errors, sources


def normalise_dabang(raw: dict[str, Any]) -> dict[str, Any]:
    """``priceTitle`` is display text: "6500" / "1000/50" / "3억 2,000"."""
    sales = raw.get("priceTypeName")
    deposit, rent = parse_dabang_price(raw.get("priceTitle"))
    desc = raw.get("roomDesc") or ""
    area = None
    floor = None
    for chunk in [c.strip() for c in desc.split(",")]:
        if chunk.endswith("m²"):
            area = _num(chunk[:-2])
        elif chunk.endswith("층") or chunk in ("반지하", "옥탑"):
            floor = chunk
    return make_item(
        provider="dabang",
        item_id=raw.get("id"),
        sales_type=sales,
        deposit=deposit if sales != "매매" else None,
        rent=rent,
        price=deposit if sales == "매매" else None,
        area_m2=area,
        floor=floor,
        title=raw.get("roomTitle"),
        address=raw.get("dongName"),
        url=f"https://www.dabangapp.com/room/{raw.get('id')}",
        property_type=raw.get("roomTypeName"),
        lat=_num((raw.get("randomLocation") or {}).get("lat")),
        lng=_num((raw.get("randomLocation") or {}).get("lng")),
        extra={"complex": raw.get("complexName"), "price_label": raw.get("priceTitle")},
    )


def parse_dabang_price(label: str | None) -> tuple[float | None, float | None]:
    """Return (deposit_manwon, rent_manwon) from a Dabang price label."""
    if not label:
        return None, None
    parts = [p.strip() for p in str(label).split("/")]
    values = [_parse_korean_manwon(p) for p in parts]
    if len(values) == 1:
        return values[0], None
    return values[0], values[1]


def _parse_korean_manwon(text: str) -> float | None:
    text = text.replace(",", "").strip()
    if not text:
        return None
    total = 0.0
    if "억" in text:
        head, _, tail = text.partition("억")
        head_val = _num(head)
        if head_val is None:
            return None
        total += head_val * 10000
        text = tail.strip()
        if not text:
            return total
    val = _num(text)
    if val is None:
        return total or None
    return total + val


# ---------------------------------------------------------------------------
# naver adapter (link-only)
# ---------------------------------------------------------------------------

NAVER_TRADE_CODE = {"전세": "B1", "월세": "B2", "매매": "A1"}
NAVER_TYPE_CODE = {
    "원룸": "VL:DDDGG:JWJT",
    "빌라": "VL:DDDGG:JWJT",
    "오피스텔": "OPST",
    "아파트": "APT:PRE:ABYG:JGC",
}


NAVER_CDP_SCRIPT = Path(__file__).with_name("naver_cdp.js")


def naver_browser_search(
    region: Region, opts: argparse.Namespace
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Read new.land through the browser the user already has open.

    The plain-HTTP surface is bot-blocked (429 everywhere); this does not try to
    defeat that. It shells out to ``naver_cdp.js``, which attaches to the
    documented CDP endpoint, lets the page issue its own authenticated request,
    and reads the response. No browser, no results -- we fall back to links.
    """
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    sources: list[str] = []
    if not NAVER_CDP_SCRIPT.exists():
        return [], [f"naver: helper missing ({NAVER_CDP_SCRIPT.name})"], []
    for ptype in opts.property_types:
        cmd = [
            opts.node_bin, str(NAVER_CDP_SCRIPT),
            "--lat", str(region.lat), "--lng", str(region.lng),
            "--zoom", str(opts.naver_zoom),
            "--property-type", ptype,
            "--trade-type", opts.trade_types[0],
            "--region", region.full_name,
            "--pages", str(opts.pages),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=opts.naver_timeout, encoding="utf-8")
        except (subprocess.TimeoutExpired, OSError) as exc:
            errors.append(f"naver {ptype}: {exc}")
            continue
        try:
            payload = json.loads(proc.stdout or "{}")
        except ValueError:
            errors.append(f"naver {ptype}: helper produced no JSON ({(proc.stderr or '')[:120]})")
            continue
        if payload.get("status") != "ok":
            errors.append(f"naver {ptype}: {payload.get('reason')} {payload.get('hint') or ''}".strip())
            continue
        items.extend(payload.get("items") or [])
        sources.append(f"naver {ptype}: browser-cdp {payload.get('navigated')} -> {payload.get('count')}건")
        for note in payload.get("notes") or []:
            errors.append(f"naver {ptype}: {note}")
    # 원룸/빌라 share one Naver type code, so the same rows can come back twice.
    deduped: dict[str, dict[str, Any]] = {}
    for it in items:
        deduped.setdefault(it["id"], it)
    return list(deduped.values()), errors, sources


def naver_links(region: Region, opts: argparse.Namespace) -> list[dict[str, Any]]:
    """Build official new.land deep links. No scraping -- see module docstring."""
    ms = f"{region.lat},{region.lng},{opts.naver_zoom}"
    trade = ":".join(NAVER_TRADE_CODE[t] for t in opts.trade_types if t in NAVER_TRADE_CODE)
    out: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for ptype in opts.property_types:
        code = NAVER_TYPE_CODE.get(ptype)
        if not code:
            continue
        page = "complexes" if ptype == "아파트" else "houses"
        qs = urllib.parse.urlencode({"ms": ms, "a": code, "e": "RETAIL", "tradTp": trade})
        url = f"https://new.land.naver.com/{page}?{qs}"
        # 원룸/빌라 share one Naver type code -- collapse into a single link.
        if url in seen:
            seen[url]["property_type"] += f"/{ptype}"
            continue
        entry = {
            "provider": "naver",
            "property_type": ptype,
            "label": f"네이버페이 부동산 {region.full_name} {'/'.join(opts.trade_types)}",
            "url": url,
        }
        seen[url] = entry
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# filtering / output
# ---------------------------------------------------------------------------


def apply_filters(items: list[dict[str, Any]], opts: argparse.Namespace) -> list[dict[str, Any]]:
    out = []
    for it in items:
        dep = it.get("deposit_manwon")
        if opts.deposit_max is not None and dep is not None and dep > opts.deposit_max:
            continue
        if opts.deposit_min is not None and dep is not None and dep < opts.deposit_min:
            continue
        rent = it.get("rent_manwon")
        if opts.rent_max is not None and rent is not None and rent > opts.rent_max:
            continue
        area = it.get("area_m2")
        if opts.area_min_m2 is not None and area is not None and area < opts.area_min_m2:
            continue
        out.append(it)
    return out


def sort_key(item: dict[str, Any]) -> tuple[int, float]:
    dep = item.get("deposit_manwon")
    return (0 if dep is not None else 1, float(dep) if dep is not None else 0.0)


def cmd_search(opts: argparse.Namespace) -> int:
    region, candidates, region_errors = pick_region(opts.region, opts.prefer)
    if region is None:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "region_not_resolved",
                    "query": opts.region,
                    "errors": region_errors,
                    "hint": "시/구를 붙여 다시 시도한다. 예: --region 신흥동 --prefer 성남",
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 2

    items: list[dict[str, Any]] = []
    errors: list[str] = list(region_errors)
    sources: list[str] = []
    links: list[dict[str, Any]] = []

    for pid in opts.providers:
        if pid == "naver":
            links.extend(naver_links(region, opts))
            if opts.naver_browser:
                got, errs, srcs = naver_browser_search(region, opts)
                items.extend(got)
                errors.extend(errs)
                sources.extend(srcs)
                if not got:
                    # Distinguish "the browser path broke" from "Naver simply has
                    # nothing here" -- collapsing them hides a real zero result.
                    reason = "조회 실패" if errs else "해당 조건 매물 0건"
                    sources.append(f"naver: {reason} -> 딥링크만 제공")
            else:
                sources.append("naver: link-only (--naver-browser 로 브라우저 조회 활성화)")
            continue
        fn = {"zigbang": zigbang_search, "dabang": dabang_search}[pid]
        got, errs, srcs = fn(region, opts)
        items.extend(got)
        errors.extend(errs)
        sources.extend(srcs)

    filtered = apply_filters(items, opts)
    filtered.sort(key=sort_key)
    if opts.limit:
        filtered = filtered[: opts.limit]

    payload = {
        "status": "ok",
        "query": {
            "region": opts.region,
            "trade_types": opts.trade_types,
            "property_types": opts.property_types,
            "deposit_max_manwon": opts.deposit_max,
            "deposit_min_manwon": opts.deposit_min,
            "rent_max_manwon": opts.rent_max,
            "area_min_m2": opts.area_min_m2,
            "providers": opts.providers,
        },
        "region": {
            "name": region.name,
            "full_name": region.full_name,
            "lat": region.lat,
            "lng": region.lng,
            "code": region.code,
            "resolved_by": region.source,
            "geohash": geohash_encode(region.lat, region.lng, opts.geohash_precision),
        },
        "region_candidates": [c.full_name for c in candidates[:8]],
        "count": len(filtered),
        "scanned": len(items),
        "items": filtered,
        "links": links,
        "sources": sources,
        "errors": errors,
        "disclaimer": "모두 호가(asking price)이며 실거래가가 아니다. 실거래는 real-estate-search 스킬을 쓴다.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0


def cmd_detail(opts: argparse.Namespace) -> int:
    if opts.provider in ("zigbang", "dabang"):
        if opts.provider == "zigbang":
            url = f"https://apis.zigbang.com/house/property/v1/items/{opts.id}/detail"
            headers = {"Referer": "https://www.zigbang.com/"}
        else:
            url = f"https://www.dabangapp.com/api/v5/room/{opts.id}"
            headers = dict(DABANG_HEADERS, Referer=f"https://www.dabangapp.com/room/{opts.id}")
        try:
            payload = _request(url, headers=headers)
        except urllib.error.HTTPError as exc:
            # Dabang gates single-room detail behind a session: 403 for anyone
            # not logged in. Report it instead of dying with an empty stdout.
            reason = "detail_requires_login" if exc.code in (401, 403) else "detail_http_error"
            print(
                json.dumps(
                    {
                        "status": "unavailable",
                        "reason": reason,
                        "provider": opts.provider,
                        "id": opts.id,
                        "http_status": exc.code,
                        "endpoint": url,
                        "hint": "목록 검색 결과의 필드를 쓰거나 url을 브라우저로 연다. 로그인 우회는 하지 않는다.",
                    },
                    ensure_ascii=False,
                    indent=1,
                )
            )
            return 2
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            print(
                json.dumps(
                    {"status": "unavailable", "reason": "detail_fetch_failed", "provider": opts.provider,
                     "id": opts.id, "endpoint": url, "error": str(exc)},
                    ensure_ascii=False,
                    indent=1,
                )
            )
            return 2
    else:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "provider_is_link_only",
                    "provider": opts.provider,
                    "note": PROVIDERS[opts.provider].note,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 2
    print(json.dumps({"status": "ok", "provider": opts.provider, "id": opts.id, "detail": payload}, ensure_ascii=False, indent=1))
    return 0


def cmd_providers(_: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "providers": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "operator": p.operator,
                        "entrypoint": p.entrypoint,
                        "transport": p.transport,
                        "auth": p.auth,
                        "property_types": list(p.property_types),
                        "scrapes": p.scrapes,
                        "note": p.note,
                    }
                    for p in PROVIDERS.values()
                ]
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


def _csv(value: str, allowed: tuple[str, ...], label: str) -> list[str]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    bad = [p for p in parts if p not in allowed]
    if bad:
        raise argparse.ArgumentTypeError(f"{label}: {bad} 는 지원하지 않는다. 허용: {list(allowed)}")
    return parts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="한국 부동산 포털 매물(호가) 통합 검색 — 조회 전용")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="지역 기준 매물 검색")
    s.add_argument("--region", required=True, help="동/지역명 (예: 신흥동)")
    s.add_argument("--prefer", help="동명이 여럿일 때 좁히는 힌트 (예: 성남)")
    s.add_argument(
        "--trade-type",
        default="전세",
        dest="trade_types",
        type=lambda v: _csv(v, TRADE_TYPES, "--trade-type"),
        help="전세|월세|매매 (콤마 구분, 기본 전세)",
    )
    s.add_argument(
        "--property-type",
        default="원룸,빌라",
        dest="property_types",
        type=lambda v: _csv(v, PROPERTY_TYPES, "--property-type"),
        help="원룸|빌라|오피스텔|아파트 (콤마 구분, 기본 원룸,빌라)",
    )
    s.add_argument("--deposit-max", type=int, help="보증금/전세금 상한 (만원)")
    s.add_argument("--deposit-min", type=int, help="보증금/전세금 하한 (만원)")
    s.add_argument("--rent-max", type=int, help="월세 상한 (만원)")
    s.add_argument("--area-min-m2", type=float, help="전용면적 하한 (m²)")
    s.add_argument(
        "--provider",
        default=",".join(DEFAULT_PROVIDERS),
        dest="providers",
        type=lambda v: _csv(v, tuple(PROVIDERS), "--provider"),
        help="zigbang|dabang|naver (콤마 구분, 기본 zigbang,dabang)",
    )
    s.add_argument("--limit", type=int, default=30, help="출력 매물 수 (기본 30)")
    s.add_argument("--radius-km", type=float, default=1.5, help="다방 bbox 반경 km (기본 1.5)")
    s.add_argument("--pages", type=int, default=2, help="다방 페이지 수 (기본 2)")
    s.add_argument("--geohash-precision", type=int, default=5, help="직방 geohash 자릿수 (기본 5, 약 5km)")
    s.add_argument("--naver-zoom", type=int, default=15, help="네이버 지도/딥링크 줌 레벨 (기본 15)")
    s.add_argument(
        "--naver-browser",
        action="store_true",
        help="네이버를 딥링크가 아니라 실제 브라우저(CDP)로 조회한다. KSKILL_CHROME_CDP_URL 필요.",
    )
    s.add_argument("--node-bin", default="node", help="naver_cdp.js 실행용 node 실행파일 (기본 node)")
    s.add_argument("--naver-timeout", type=int, default=120, help="네이버 브라우저 조회 타임아웃 초 (기본 120)")
    s.set_defaults(func=cmd_search)

    d = sub.add_parser("detail", help="매물 상세 조회")
    d.add_argument("--provider", required=True, choices=list(PROVIDERS))
    d.add_argument("--id", required=True)
    d.set_defaults(func=cmd_detail)

    p = sub.add_parser("providers", help="어댑터 레지스트리 출력")
    p.set_defaults(func=cmd_providers)
    return parser


def main(argv: list[str] | None = None) -> int:
    opts = build_parser().parse_args(argv)
    return opts.func(opts)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
