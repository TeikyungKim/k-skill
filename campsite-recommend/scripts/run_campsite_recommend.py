#!/usr/bin/env python3
"""Rank campground vacancy results with a reproducible recommendation score.

Takes the JSON output of ``foresttrip-vacancy`` and/or ``korean-campsite-vacancy``,
joins each facility to a curated Kakao Map place id (``references/place-map.json``),
fetches the public rating snapshot for exactly those facilities, and sorts them by
the frozen scoring formula documented in ``references/SCORING.md``:

    adjusted = (n_ratings * rating + 10 * 4.1603) / (n_ratings + 10)
    score    = 0.7 * (adjusted / 5 * 100)
             + 0.3 * (ln(1 + n_ratings + n_reviews) / ln(1 + 979) * 100)

Facilities without a curated mapping are never guessed at by name search; they are
reported in a separate ``unranked`` list sorted by available-site count.

Read-only. Ratings come from the public Kakao place panel endpoint (no API key);
driving distance/toll (optional ``--origin``) goes through the k-skill-proxy
Kakao Mobility route. The helper only queries facilities present in the input and
caches responses, so it never mass-crawls.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

# --- frozen scoring constants (see references/SCORING.md for provenance) ---
PRIOR_MEAN = 4.1603
PRIOR_WEIGHT = 10
REVIEW_LOG_NORM = 979
W_RATING = 0.7
W_REVIEW = 0.3

PLACE_API = "https://place-api.map.kakao.com/places/panel3/"
# 2026-09-01 확인: place-api는 브라우저형 헤더 세트가 없으면 406을 돌려준다.
# pf/Accept만으로는 부족하고 Origin·Referer·sec-fetch-* 까지 있어야 200이 나온다.
PLACE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "pf": "web",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://place.map.kakao.com",
    "Referer": "https://place.map.kakao.com/",
    "sec-fetch-site": "same-site",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
}
DEFAULT_PROXY_BASE = "https://k-skill-proxy.nomadamas.org"
HTTP_TIMEOUT = 20
RATINGS_TTL_SECONDS = 24 * 3600
ROUTES_TTL_SECONDS = 7 * 24 * 3600
PLACE_FETCH_SLEEP_SECONDS = 0.5
MAX_PLACE_FETCHES_PER_RUN = 120

_LEADING_TAGS = re.compile(r"^\s*(?:\[[^\]]*\]|\([^)]*\))+")
_WS = re.compile(r"\s+")


def default_cache_path() -> Path:
    return Path.home() / ".cache" / "k-skill" / "campsite-recommend.json"


def place_map_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "place-map.json"


def load_place_map(path: Path | None = None) -> dict[str, Any]:
    with open(path or place_map_path(), encoding="utf-8") as fh:
        return json.load(fh)


def normalize_name(name: str) -> str:
    """Strip leading [지역](운영주체) style tags and all whitespace."""
    return _WS.sub("", _LEADING_TAGS.sub("", name or ""))


def compute_score(rating: float, rating_count: int, review_count: int) -> dict[str, float]:
    adjusted = (rating_count * rating + PRIOR_WEIGHT * PRIOR_MEAN) / (rating_count + PRIOR_WEIGHT)
    rating_term = adjusted / 5 * 100
    review_term = math.log1p(rating_count + review_count) / math.log1p(REVIEW_LOG_NORM) * 100
    return {
        "score": round(W_RATING * rating_term + W_REVIEW * review_term, 2),
        "adjusted_rating": round(adjusted, 4),
        "rating_term": round(rating_term, 2),
        "review_term": round(review_term, 2),
    }


# --------------------------------------------------------------------------
# vacancy input parsing
# --------------------------------------------------------------------------

def detect_input_kind(payload: dict[str, Any]) -> str:
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("not a vacancy result: missing 'results' list")
    if not results:
        return "empty"
    first = results[0]
    if "provider" in first:
        return "campsite"
    dates = first.get("dates")
    if isinstance(dates, list) and (not dates or "rooms" in dates[0]):
        return "foresttrip"
    raise ValueError("unrecognized vacancy result shape")


def aggregate_foresttrip(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One facility entry per forest; sites available on *every* input date."""
    facilities: list[dict[str, Any]] = []
    for forest in payload.get("results", []):
        goods_by_date: dict[str, set[str]] = {}
        room_info: dict[str, dict[str, Any]] = {}
        forest_id = None
        for day in forest.get("dates", []):
            bucket = goods_by_date.setdefault(day["use_dt"], set())
            for room in day.get("rooms", []):
                bucket.add(room["goods_id"])
                room_info.setdefault(room["goods_id"], room)
                forest_id = forest_id or room.get("forest_id")
        if not room_info:
            continue
        date_sets = list(goods_by_date.values())
        common = set.intersection(*date_sets) if date_sets else set()
        rooms = [room_info[g] for g in common]
        facilities.append(
            {
                "source": "foresttrip",
                "id": forest_id,
                "name": forest.get("forest") or next(iter(room_info.values()))["forest"],
                "dates": sorted(goods_by_date),
                "available_sites": len(common),
                "site_types": dict(Counter(r.get("category") or "?" for r in rooms)),
                "capacities": sorted({r.get("capacity") for r in rooms if r.get("capacity")}),
                "max_stay_nights": max((r.get("max_stay_nights") or 0) for r in rooms) if rooms else None,
                "confirmed": bool(common),
                "status_note": None if common else "입력한 모든 날짜에 공통으로 비어 있는 사이트 없음",
            }
        )
    return facilities


def aggregate_campsite(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One facility entry per provider; zones open+available on every input date."""
    requested = list(payload.get("dates") or [])
    facilities: list[dict[str, Any]] = []
    for entry in payload.get("results", []):
        by_date = {d["use_dt"]: d for d in entry.get("dates", [])}
        dates = requested or sorted(by_date)
        blockers: list[str] = []
        zone_sets: list[set[str]] = []
        zone_names: dict[str, str] = {}
        for use_dt in dates:
            day = by_date.get(use_dt)
            if day is None:
                blockers.append(f"{use_dt}: 조회 결과 없음(마감 또는 미오픈)")
                continue
            if day.get("booking_status") != "open":
                note = day.get("status_note") or day.get("booking_status")
                blockers.append(f"{use_dt}: {note}")
                continue
            avail = {z["zone_id"] for z in day.get("zones", []) if z.get("available")}
            for z in day.get("zones", []):
                zone_names.setdefault(z["zone_id"], z.get("zone") or z["zone_id"])
            zone_sets.append(avail)
        common = set.intersection(*zone_sets) if zone_sets and not blockers else set()
        facilities.append(
            {
                "source": "campsite",
                "id": entry.get("provider"),
                "name": entry.get("name"),
                "dates": dates,
                "available_sites": len(common),
                "site_types": {zone_names[z]: 1 for z in sorted(common)},
                "capacities": [],
                "max_stay_nights": None,
                "confirmed": bool(common),
                "status_note": " / ".join(blockers) if blockers else None,
            }
        )
    return facilities


def load_vacancy_inputs(paths: list[str]) -> list[dict[str, Any]]:
    facilities: list[dict[str, Any]] = []
    for raw_path in paths:
        if raw_path == "-":
            text = sys.stdin.read()
        else:
            data = Path(raw_path).read_bytes()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                # Windows shells sometimes save helper output as cp949
                text = data.decode("cp949")
        payload = json.loads(text)
        kind = detect_input_kind(payload)
        if kind == "foresttrip":
            facilities.extend(aggregate_foresttrip(payload))
        elif kind == "campsite":
            facilities.extend(aggregate_campsite(payload))
    return facilities


# --------------------------------------------------------------------------
# joining facilities to curated kakao place ids
# --------------------------------------------------------------------------

def match_place(facility: dict[str, Any], place_map: dict[str, Any]) -> dict[str, Any] | None:
    section = place_map.get("foresttrip" if facility["source"] == "foresttrip" else "providers", {})
    fid = facility.get("id")
    if fid and fid in section:
        return section[fid]
    wanted = normalize_name(facility.get("name") or "")
    if not wanted:
        return None
    hits = [v for v in section.values() if normalize_name(v["name"]) == wanted]
    return hits[0] if len(hits) == 1 else None


# --------------------------------------------------------------------------
# network: kakao place ratings + proxy directions (both cached)
# --------------------------------------------------------------------------

def _http_get_json(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_place(place_id: str) -> dict[str, Any]:
    data = _http_get_json(PLACE_API + urllib.parse.quote(str(place_id)), PLACE_HEADERS)
    summary = data.get("summary") or {}
    score_set = (data.get("kakaomap_review") or {}).get("score_set") or {}
    point = summary.get("point") or {}
    return {
        "place_name": summary.get("name"),
        "address": (summary.get("address") or {}).get("disp"),
        "lon": point.get("lon"),
        "lat": point.get("lat"),
        "rating": score_set.get("average_score"),
        "rating_count": score_set.get("review_count") or 0,
        "review_count": (data.get("blog_review") or {}).get("review_count") or 0,
    }


class Cache:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("ratings", {})
        self.data.setdefault("routes", {})

    def get(self, section: str, key: str, ttl: int) -> Any | None:
        row = self.data[section].get(key)
        if row and time.time() - row.get("at", 0) < ttl:
            return row["value"]
        return None

    def put(self, section: str, key: str, value: Any) -> None:
        self.data[section][key] = {"at": time.time(), "value": value}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")


def geocode_origin(query: str, proxy_base: str) -> dict[str, Any]:
    url = f"{proxy_base}/v1/kakao-map/search/keyword?" + urllib.parse.urlencode({"q": query, "size": 1})
    data = _http_get_json(url, {"Accept": "application/json"})
    docs = data.get("documents") or []
    if not docs:
        raise ValueError(f"origin not found on Kakao Local: {query!r}")
    doc = docs[0]
    return {"query": query, "matched": doc.get("place_name"), "lon": float(doc["x"]), "lat": float(doc["y"])}


def fetch_route(origin: dict[str, Any], lon: float, lat: float, proxy_base: str) -> dict[str, Any] | None:
    params = urllib.parse.urlencode(
        {"origin": f"{origin['lon']},{origin['lat']}", "destination": f"{lon},{lat}", "priority": "RECOMMEND"}
    )
    data = _http_get_json(f"{proxy_base}/v1/kakao-mobility/directions?{params}", {"Accept": "application/json"})
    routes = data.get("routes") or []
    if not routes or routes[0].get("result_code") not in (0, None):
        return None
    summary = routes[0].get("summary") or {}
    fare = summary.get("fare") or {}
    return {
        "distance_km": round((summary.get("distance") or 0) / 1000, 1),
        "duration_min": round((summary.get("duration") or 0) / 60),
        "toll_won": fare.get("toll"),
    }


# --------------------------------------------------------------------------
# report assembly (pure; network results injected for testability)
# --------------------------------------------------------------------------

def build_report(
    facilities: list[dict[str, Any]],
    place_map: dict[str, Any],
    ratings_by_place_id: dict[str, dict[str, Any]],
    routes_by_place_id: dict[str, dict[str, Any] | None] | None = None,
    origin: dict[str, Any] | None = None,
    failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = []
    unranked: list[dict[str, Any]] = []
    for facility in facilities:
        if not facility.get("confirmed"):
            unranked.append({**facility, "unranked_reason": facility.get("status_note") or "가용 사이트 없음"})
            continue
        mapping = match_place(facility, place_map)
        rating = ratings_by_place_id.get((mapping or {}).get("kakao_place_id") or "")
        if not mapping or not rating or rating.get("rating") is None:
            reason = "place-map.json에 매핑 없음" if not mapping else "카카오 평점 조회 실패"
            unranked.append({**facility, "unranked_reason": reason})
            continue
        row = {
            **facility,
            "kakao_place_id": mapping["kakao_place_id"],
            "region": mapping.get("region"),
            "kakao_place_name": rating.get("place_name"),
            "address": rating.get("address"),
            "rating": rating["rating"],
            "rating_count": rating["rating_count"],
            "review_count": rating["review_count"],
            **compute_score(rating["rating"], rating["rating_count"], rating["review_count"]),
        }
        if routes_by_place_id is not None:
            row["route"] = routes_by_place_id.get(mapping["kakao_place_id"])
        ranked.append(row)
    ranked.sort(key=lambda r: (-r["score"], -r["available_sites"], r["name"]))
    for i, row in enumerate(ranked, 1):
        row["rank"] = i
    unranked.sort(key=lambda r: (-r["available_sites"], r["name"]))
    return {
        "scoring": {
            "prior_mean": PRIOR_MEAN,
            "prior_weight": PRIOR_WEIGHT,
            "review_log_norm": REVIEW_LOG_NORM,
            "weights": {"rating": W_RATING, "review": W_REVIEW},
        },
        "origin": origin,
        "ranked": ranked,
        "unranked": unranked,
        "fetch_failures": failures or [],
    }


def render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    origin = report.get("origin")
    if origin:
        lines.append(f"출발지: {origin['matched']} ({origin['query']})")
    lines.append(f"추천 순위 {len(report['ranked'])}곳 · 순위 미산정 {len(report['unranked'])}곳")
    for row in report["ranked"]:
        route = row.get("route")
        route_txt = ""
        if route:
            toll = f" · 통행료 {route['toll_won']:,}원" if route.get("toll_won") is not None else ""
            route_txt = f" · {route['distance_km']}km/{route['duration_min']}분{toll}"
        types = ", ".join(f"{k} {v}" for k, v in row["site_types"].items())
        lines.append(
            f"{row['rank']}. {row['name']} ({row.get('region') or '?'}) — {row['score']}점"
            f" · 평점 {row['rating']}({row['rating_count']}) · 리뷰 {row['review_count']}"
            f" · 가용 {row['available_sites']}면 [{types}]{route_txt}"
        )
    if report["unranked"]:
        lines.append("")
        lines.append("순위 미산정 (가용 사이트 수 순):")
        for row in report["unranked"]:
            lines.append(f"- {row['name']} — 가용 {row['available_sites']}면 · {row['unranked_reason']}")
    for failure in report["fetch_failures"]:
        lines.append(f"! {failure['scope']}: {failure['error']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", action="append", default=[],
                        help="vacancy JSON path ('-'=stdin). 반복 지정으로 여러 결과 병합")
    parser.add_argument("--origin", help="자동차 거리 계산용 출발지 키워드 (예: 신대방삼거리역)")
    parser.add_argument("--origin-coords", help="출발지 좌표 LON,LAT (WGS84; --origin 대신)")
    parser.add_argument("--proxy-base", default=None, help="k-skill-proxy base URL override")
    parser.add_argument("--cache", default=None, help="cache file path override")
    parser.add_argument("--refresh-ratings", action="store_true", help="평점 캐시 무시하고 재조회")
    parser.add_argument("--text", action="store_true", help="사람용 요약 출력 (기본 JSON)")
    parser.add_argument("--check-deps", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check_deps:
        print("campsite-recommend dependencies look ready (stdlib only)")
        return 0
    if not args.input:
        print("error: --input 이 최소 1개 필요하다 (foresttrip-vacancy / korean-campsite-vacancy JSON)", file=sys.stderr)
        return 2

    import os

    proxy_base = (args.proxy_base or os.environ.get("KSKILL_PROXY_BASE_URL") or DEFAULT_PROXY_BASE).rstrip("/")
    facilities = load_vacancy_inputs(args.input)
    place_map = load_place_map()
    cache = Cache(Path(args.cache) if args.cache else default_cache_path())
    failures: list[dict[str, str]] = []

    origin = None
    if args.origin_coords:
        lon, lat = (float(v) for v in args.origin_coords.split(","))
        origin = {"query": args.origin_coords, "matched": "(좌표 직접 입력)", "lon": lon, "lat": lat}
    elif args.origin:
        try:
            origin = geocode_origin(args.origin, proxy_base)
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            failures.append({"scope": f"origin:{args.origin}", "error": str(exc)})

    # fetch ratings only for facilities present in the input (bounded, cached)
    ratings: dict[str, dict[str, Any]] = {}
    fetched = 0
    for facility in facilities:
        if not facility.get("confirmed"):
            continue
        mapping = match_place(facility, place_map)
        if not mapping:
            continue
        pid = mapping["kakao_place_id"]
        if pid in ratings:
            continue
        cached = None if args.refresh_ratings else cache.get("ratings", pid, RATINGS_TTL_SECONDS)
        if cached is not None:
            ratings[pid] = cached
            continue
        if fetched >= MAX_PLACE_FETCHES_PER_RUN:
            failures.append({"scope": f"place:{pid}", "error": "run 당 조회 상한 초과, 캐시 후 재실행 필요"})
            continue
        try:
            value = fetch_place(pid)
            ratings[pid] = value
            cache.put("ratings", pid, value)
            fetched += 1
            time.sleep(PLACE_FETCH_SLEEP_SECONDS)
        except Exception as exc:  # noqa: BLE001
            failures.append({"scope": f"place:{pid}", "error": str(exc)})

    routes: dict[str, dict[str, Any] | None] | None = None
    if origin:
        routes = {}
        for pid, rating in ratings.items():
            if rating.get("lon") is None:
                routes[pid] = None
                continue
            key = f"{origin['lon']:.6f},{origin['lat']:.6f}->{pid}"
            cached = cache.get("routes", key, ROUTES_TTL_SECONDS)
            if cached is not None:
                routes[pid] = cached
                continue
            try:
                value = fetch_route(origin, rating["lon"], rating["lat"], proxy_base)
                routes[pid] = value
                cache.put("routes", key, value)
            except Exception as exc:  # noqa: BLE001
                routes[pid] = None
                failures.append({"scope": f"route:{pid}", "error": str(exc)})

    cache.save()
    report = build_report(facilities, place_map, ratings, routes, origin, failures)
    if args.text:
        print(render_text(report))
    else:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
        print()
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
