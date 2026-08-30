#!/usr/bin/env python3
"""Read-only foresttrip.go.kr vacancy lookup helper.

The script logs in with Playwright to obtain a CSRF token and session cookies,
extracts forest IDs from the official monthly reservation status page, then
queries the read-only monthly availability JSON endpoint.

It intentionally does not click booking buttons, submit reservation forms,
handle payment, solve captcha, or bypass queues.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

LOGIN_URL = "https://www.foresttrip.go.kr/com/login.do"
RSRVT_PAGE = "https://www.foresttrip.go.kr/rep/or/sssn/monthRsrvtSmplStatus.do"
POST_URL = "https://www.foresttrip.go.kr/rep/or/selectRsrvtAvailInfoListForMonthRsrvtSmpl.do"
# The availability feed answers for goods that the official screen never offers,
# and for dates past the forest's booking window. Both gates below are what the
# real page applies before it draws a "예약가능" cell.
GOODS_URL = "https://www.foresttrip.go.kr/rep/or/sssn/selectRsrvtGoodsListForMonthRsrvtSmpl.do"
POLICY_URL = "https://www.foresttrip.go.kr/rep/or/selectSthngListForMonthRsrvt.do"
DEFAULT_CONCURRENCY = 4
MAX_CONCURRENCY = 5
DEFAULT_WEEK_RANGE = 1
CATEGORY_CODES = {"01", "02"}
RESERVE_ROOM_MARKER = "예비"


@dataclass
class Session:
    cookies: dict[str, str]
    csrf: str
    user_agent: str
    forests: dict[str, str]
    expires_at: float


def parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_categories(value: str) -> tuple[str, ...]:
    categories = parse_csv(value)
    if not categories:
        raise argparse.ArgumentTypeError("must include at least one category code")
    invalid = [category for category in categories if category not in CATEGORY_CODES]
    if invalid:
        raise argparse.ArgumentTypeError(
            "unknown category code(s): "
            + ", ".join(invalid)
            + " (allowed: 01=lodging, 02=camping)"
        )
    return tuple(dict.fromkeys(categories))


def parse_dates(value: str) -> tuple[str, ...]:
    dates = parse_csv(value)
    if not dates:
        raise argparse.ArgumentTypeError("must include at least one YYYYMMDD date")

    today = datetime.now().date()
    normalized: list[str] = []
    for raw_date in dates:
        try:
            parsed = datetime.strptime(raw_date, "%Y%m%d").date()
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid YYYYMMDD date: {raw_date}") from exc
        if parsed.strftime("%Y%m%d") != raw_date:
            raise argparse.ArgumentTypeError(f"invalid YYYYMMDD date: {raw_date}")
        if parsed < today:
            raise argparse.ArgumentTypeError(f"date is in the past: {raw_date}")
        normalized.append(raw_date)
    return tuple(sorted(dict.fromkeys(normalized)))


def parse_concurrency(value: str) -> int:
    try:
        concurrency = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_CONCURRENCY}")
    return concurrency


def parse_week_range(value: str) -> int:
    try:
        week_range = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if week_range < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return week_range


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only foresttrip.go.kr vacancy lookup.",
    )
    target = parser.add_argument_group("target selection")
    target.add_argument("--all", action="store_true", help="Scan all extracted forest IDs.")
    target.add_argument(
        "--forest-id",
        action="append",
        help="ForestTrip insttId. Can be passed multiple times or comma-separated.",
    )
    target.add_argument(
        "--forest-name",
        action="append",
        help="Substring to match against official forest names.",
    )

    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="Print JSON output.")
    output.add_argument("--text", action="store_true", help="Print human-readable output.")
    parser.add_argument("--dates", type=parse_dates, help="Comma-separated YYYYMMDD dates.")
    parser.add_argument(
        "--categories",
        type=parse_categories,
        default=("01", "02"),
        help="Comma-separated category codes: 01=lodging, 02=camping.",
    )
    parser.add_argument(
        "--concurrency",
        type=parse_concurrency,
        default=DEFAULT_CONCURRENCY,
        help=f"Parallel POST workers, 1-{MAX_CONCURRENCY}.",
    )
    parser.add_argument("--week-range", type=parse_week_range, help="Weeks ahead to scan when --dates is omitted.")
    parser.add_argument(
        "--nights",
        type=parse_nights,
        default=1,
        help="Only keep rooms free for this many consecutive nights from the listed date.",
    )
    parser.add_argument("--refresh-session", action="store_true", help="Ignore session cache.")
    parser.add_argument("--check-deps", action="store_true", help="Check Python and Playwright runtime dependencies.")
    parser.add_argument(
        "--session-cache",
        default="~/.cache/k-skill/foresttrip-vacancy/session.json",
        help="Session cache path.",
    )
    args = parser.parse_args()
    if args.all and (args.forest_id or args.forest_name):
        parser.error("--all cannot be combined with --forest-id or --forest-name")
    if args.dates and args.week_range is not None:
        parser.error("--week-range cannot be combined with --dates; the lookup range is derived from --dates")
    return args


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def check_dependencies(*, launch_browser: bool = True) -> None:
    if sys.version_info < (3, 9):
        raise SystemExit("python 3.9+ is required")
    try:
        from playwright.sync_api import Error as PlaywrightError  # type: ignore[reportMissingImports]
        from playwright.sync_api import sync_playwright  # type: ignore[reportMissingImports]
    except ImportError as exc:
        raise SystemExit(
            "playwright is required. Install with: python3 -m pip install playwright"
        ) from exc

    if not launch_browser:
        return

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except PlaywrightError as exc:
        raise SystemExit(
            "playwright chromium browser is required. Install with: "
            "python3 -m playwright install chromium"
        ) from exc


def load_session_cache(path: Path) -> Session | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() > float(data.get("expires_at", 0)):
            return None
        return Session(
            cookies=dict(data["cookies"]),
            csrf=str(data["csrf"]),
            user_agent=str(data["user_agent"]),
            forests=dict(data["forests"]),
            expires_at=float(data["expires_at"]),
        )
    except Exception:
        return None


def save_session_cache(path: Path, session: Session) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(session), ensure_ascii=False), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def bootstrap_session(*, forest_id: str, forest_pw: str, ttl_sec: int = 600) -> Session:
    try:
        from playwright.sync_api import Error as PlaywrightError  # type: ignore[reportMissingImports]
        from playwright.sync_api import sync_playwright  # type: ignore[reportMissingImports]
    except ImportError as exc:
        raise SystemExit(
            "playwright is required. Install with: python3 -m pip install playwright "
            "&& python3 -m playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except PlaywrightError as exc:
            raise SystemExit(
                "playwright chromium browser is required. Install with: "
                "python3 -m playwright install chromium"
            ) from exc
        page = browser.new_page()
        page.goto(LOGIN_URL)
        page.fill("#mmberId", forest_id)
        page.fill("#gnrlMmberPssrd", forest_pw)
        page.click("input.loginBtn")
        page.wait_for_load_state("networkidle")
        page.goto(RSRVT_PAGE)
        page.wait_for_load_state("networkidle")

        csrf_locator = page.locator('input[name="_csrf"]')
        if csrf_locator.count() == 0:
            browser.close()
            raise SystemExit("login succeeded page did not expose a CSRF token")
        csrf = csrf_locator.first.get_attribute("value") or ""

        forests: dict[str, str] = {}
        regions = page.evaluate(
            """
            () => Array.from(document.querySelector('#srchSido').options)
              .slice(1)
              .map(o => ({ value: o.value, text: o.textContent.trim() }))
            """
        )
        for region in regions:
            value = region.get("value")
            if not value:
                continue
            page.select_option("#srchSido", value=value)
            page.wait_for_timeout(500)
            options = page.evaluate(
                """
                () => Array.from(document.querySelector('#srchInstt').options)
                  .slice(1)
                  .map(o => ({ value: o.value, text: o.textContent.trim() }))
                """
            )
            for opt in options:
                fid = str(opt.get("value") or "").strip()
                name = str(opt.get("text") or "").strip()
                if fid and name:
                    forests[fid] = name

        cookies = {cookie["name"]: cookie["value"] for cookie in page.context.cookies()}
        user_agent = page.evaluate("() => navigator.userAgent")
        browser.close()

    if not csrf or not cookies:
        raise SystemExit("failed to bootstrap foresttrip session")
    if not forests:
        raise SystemExit("failed to extract forest list from reservation page")
    return Session(
        cookies=cookies,
        csrf=csrf,
        user_agent=user_agent,
        forests=forests,
        expires_at=time.time() + ttl_sec,
    )


def get_session(args: argparse.Namespace) -> Session:
    cache_path = Path(args.session_cache).expanduser()
    if not args.refresh_session:
        cached = load_session_cache(cache_path)
        if cached is not None:
            return cached
    session = bootstrap_session(
        forest_id=require_env("KSKILL_FORESTTRIP_ID"),
        forest_pw=require_env("KSKILL_FORESTTRIP_PASSWORD"),
    )
    save_session_cache(cache_path, session)
    return session


def split_csv(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def resolve_targets(args: argparse.Namespace, forests: dict[str, str]) -> dict[str, str]:
    if args.all:
        return dict(sorted(forests.items(), key=lambda item: item[1]))

    requested_ids = split_csv(args.forest_id)
    requested_names = split_csv(args.forest_name)
    targets: dict[str, str] = {}
    for fid in requested_ids:
        targets[fid] = forests.get(fid, fid)
    for needle in requested_names:
        matches = {
            fid: name
            for fid, name in forests.items()
            if needle.replace(" ", "") in name.replace(" ", "")
        }
        targets.update(matches)

    if not targets:
        raise SystemExit("choose a target with --all, --forest-id, or --forest-name")
    return dict(sorted(targets.items(), key=lambda item: item[1]))


def build_headers(session: Session, *, ajax_call: bool = False) -> dict[str, str]:
    cookie_header = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Content-Type": "application/json; charset=UTF-8",
        "Cookie": cookie_header,
        "Origin": "https://www.foresttrip.go.kr",
        "Referer": RSRVT_PAGE,
        "User-Agent": session.user_agent,
        "X-CSRF-Token": session.csrf,
        "X-Requested-With": "XMLHttpRequest",
    }
    if ajax_call:
        # The goods and policy endpoints reject anything without this header.
        headers["X-Ajax-call"] = "true"
    return headers


def fetch_one(
    *,
    session: Session,
    forest_id: str,
    category: str,
    today: str,
    last_day: str,
) -> tuple[str, str, list[dict[str, Any]] | None, str | None]:
    payload = {
        "insttId": forest_id,
        "upperGoodsClsscCd": category,
        "srchDate": today,
        "lastDay": last_day,
        "inqurSctin": "02",
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        POST_URL,
        data=body,
        headers=build_headers(session),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                return forest_id, category, None, f"http_{response.status}"
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list):
                return forest_id, category, data, None
            return forest_id, category, None, "unexpected_payload"
    except urllib.error.HTTPError as exc:
        return forest_id, category, None, f"http_{exc.code}"
    except Exception as exc:
        return forest_id, category, None, str(exc)


def post_json(url: str, session: Session, payload: dict[str, Any]) -> Any:
    """POST one JSON body to an authenticated foresttrip endpoint."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=build_headers(session, ajax_call=True),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_offered_goods(
    *, session: Session, forest_id: str, category: str
) -> tuple[str, str, set[str] | None, str | None]:
    """Return the goods the official screen actually offers for this facility.

    The availability feed happily returns rows for products that are not on sale
    — 가리산's 야영데크 is one — and the real page renders nothing for them
    because it draws the goods list first. An empty set means "nothing offered",
    which is a valid answer, not a failure.
    """
    try:
        data = post_json(
            GOODS_URL,
            session,
            {
                "insttId": forest_id,
                "upperGoodsClsscCd": category,
                "srchDate": datetime.now().strftime("%Y%m%d"),
                "inqurSctin": "02",
            },
        )
    except urllib.error.HTTPError as exc:
        return forest_id, category, None, f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        return forest_id, category, None, str(exc)

    if not isinstance(data, dict):
        return forest_id, category, None, "unexpected_payload"
    goods = data.get("rsrvtGoodsList") or []
    return forest_id, category, {str(item.get("goodsId") or "") for item in goods}, None


def reservation_last_day(policy: dict[str, Any]) -> str | None:
    """Last bookable date for a facility, the way the official page computes it."""
    rsrvt_polcy = policy.get("rsrvtPolcy") or {}
    if not rsrvt_polcy:
        return None
    if rsrvt_polcy.get("rsrvtCycleTpeCd") == "WEEK":
        last_day = rsrvt_polcy.get("weekLastDay")
    else:
        last_day = rsrvt_polcy.get("monthLastDay")
    general = policy.get("gnrlRsrvtTrnseDtm")
    if general and last_day and str(general) > str(last_day):
        last_day = general
    return str(last_day) if last_day else None


def fetch_booking_window(
    *, session: Session, forest_id: str
) -> tuple[str, str | None, str | None]:
    """Return the facility's 예약가능기간 end date (the page's '금일 ~ N까지')."""
    try:
        data = post_json(POLICY_URL, session, {"insttId": forest_id})
    except urllib.error.HTTPError as exc:
        return forest_id, None, f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        return forest_id, None, str(exc)

    if not isinstance(data, dict):
        return forest_id, None, "unexpected_payload"
    return forest_id, reservation_last_day(data), None


def is_available(row: dict[str, Any]) -> bool:
    count_value = row.get("rsrvtCnt")
    if count_value is None:
        return False
    try:
        reserved_count = int(count_value)
    except ValueError:
        return False
    return row.get("rsrvtAvail") == "Y" and reserved_count == 0


def is_reserve_room(row: dict[str, Any]) -> bool:
    return RESERVE_ROOM_MARKER in (row.get("goodsNm") or "")


def normalize_row(row: dict[str, Any], forests: dict[str, str]) -> dict[str, Any]:
    instt_id = str(row.get("insttId") or "")
    return {
        "forest_id": instt_id,
        "forest": forests.get(instt_id, row.get("insttNm") or instt_id),
        "use_dt": row.get("useDt") or "",
        "day": row.get("dywkDtTpcd"),
        "name": row.get("goodsNm") or "",
        "area": row.get("insttArea"),
        "capacity": row.get("mxmmAccptCnt"),
        "category": row.get("goodsClsscNm"),
        "region": row.get("insttAreaNm"),
        "waiting_possible": row.get("wtngPssblYn"),
        "goods_id": row.get("goodsId"),
        # 휴양림별 최대 숙박일수. A 3-night request against a 2-night forest is
        # rejected at booking time with "최대 숙박일수를 초과하여 신청하셨습니다".
        "max_stay_nights": row.get("mxmmStngDayCnt"),
    }


def parse_nights(value: str) -> int:
    try:
        nights = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--nights must be an integer") from exc
    if nights < 1:
        raise argparse.ArgumentTypeError("--nights must be 1 or more")
    return nights


def next_day(use_dt: str) -> str:
    return (datetime.strptime(use_dt, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def filter_consecutive_stays(rows: list[dict[str, Any]], nights: int) -> list[dict[str, Any]]:
    """Keep only rows that can actually start an ``nights``-night stay.

    Per-night vacancy does not imply a multi-night booking: the same room has to
    be free every night, and the forest's own 최대 숙박일수 caps the run. Both are
    enforced at booking time, so enforcing them here is what keeps a multi-night
    answer honest.
    """
    if nights <= 1:
        return rows

    free: dict[tuple[str, str, str], set[str]] = {}
    for row in rows:
        key = (row["forest_id"], row["source_category"], row.get("goods_id") or row["name"])
        free.setdefault(key, set()).add(row["use_dt"])

    kept: list[dict[str, Any]] = []
    for row in rows:
        try:
            max_nights = int(row.get("max_stay_nights") or 0)
        except (TypeError, ValueError):
            max_nights = 0
        if max_nights and nights > max_nights:
            continue
        key = (row["forest_id"], row["source_category"], row.get("goods_id") or row["name"])
        nights_free = free[key]
        run = row["use_dt"]
        for _ in range(nights - 1):
            run = next_day(run)
            if run not in nights_free:
                break
        else:
            kept.append({**row, "stay_nights": nights})
    return kept


def collect_results(
    *,
    session: Session,
    targets: dict[str, str],
    categories: tuple[str, ...],
    dates: tuple[str, ...] | None,
    week_range: int | None,
    concurrency: int,
    nights: int = 1,
) -> dict[str, Any]:
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    last_day = (
        max(dates)
        if dates
        else (now + timedelta(weeks=week_range or DEFAULT_WEEK_RANGE)).strftime("%Y%m%d")
    )
    date_filter = set(dates) if dates else None
    failures: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []

    jobs = [
        (forest_id, category)
        for forest_id in targets
        for category in categories
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [
            pool.submit(
                fetch_one,
                session=session,
                forest_id=forest_id,
                category=category,
                today=today,
                last_day=last_day,
            )
            for forest_id, category in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            forest_id, category, data, error = future.result()
            if error is not None or data is None:
                failures.append({"forest_id": forest_id, "category": category, "error": error or "unknown"})
                continue
            for row in data:
                if not is_available(row):
                    continue
                if is_reserve_room(row):
                    continue
                use_dt = row.get("useDt") or ""
                if use_dt < today or use_dt > last_day:
                    continue
                normalized = normalize_row(row, session.forests)
                normalized["source_category"] = category
                if date_filter is not None and normalized["use_dt"] not in date_filter:
                    continue
                rows.append(normalized)

    # --- official gates -------------------------------------------------
    # Only forests that produced candidate rows are gated, so a full scan does
    # not pay for 186 facilities that had nothing to begin with.
    candidate_pairs = sorted({(row["forest_id"], row["source_category"]) for row in rows})
    candidate_forests = sorted({forest_id for forest_id, _ in candidate_pairs})

    offered: dict[tuple[str, str], set[str]] = {}
    windows: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        goods_futures = [
            pool.submit(fetch_offered_goods, session=session, forest_id=forest_id, category=category)
            for forest_id, category in candidate_pairs
        ]
        window_futures = [
            pool.submit(fetch_booking_window, session=session, forest_id=forest_id)
            for forest_id in candidate_forests
        ]
        for future in concurrent.futures.as_completed(goods_futures):
            forest_id, category, goods, error = future.result()
            if error is not None or goods is None:
                failures.append(
                    {"forest_id": forest_id, "category": category, "error": f"goods:{error or 'unknown'}"}
                )
                continue
            offered[(forest_id, category)] = goods
        for future in concurrent.futures.as_completed(window_futures):
            forest_id, last_bookable, error = future.result()
            if error is not None:
                failures.append({"forest_id": forest_id, "category": "-", "error": f"window:{error}"})
                continue
            if last_bookable:
                windows[forest_id] = last_bookable

    gated: list[dict[str, Any]] = []
    for row in rows:
        key = (row["forest_id"], row["source_category"])
        goods = offered.get(key)
        # A gate that failed to load must not silently drop rows; only a loaded
        # goods list is allowed to exclude one.
        if goods is not None and str(row.get("goods_id") or "") not in goods:
            continue
        last_bookable = windows.get(row["forest_id"])
        if last_bookable and row["use_dt"] > last_bookable:
            continue
        gated.append(row)
    rows = gated

    rows = filter_consecutive_stays(rows, nights)

    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (row["forest_id"], row["use_dt"], row["source_category"], row["name"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    rows = deduped

    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in sorted(rows, key=lambda item: (item["forest"], item["use_dt"], item["name"])):
        grouped.setdefault(row["forest"], {}).setdefault(row["use_dt"], []).append(row)

    return {
        "forests_scanned": len(targets),
        "filter_hits": len(rows),
        "fetch_failures": len(failures),
        "failures": failures[:20],
        "concurrency": concurrency,
        "nights": nights,
        "date_range": {"from": today, "to": last_day},
        "results": [
            {
                "forest": forest_name,
                "dates": [
                    {"use_dt": use_dt, "rooms": rooms}
                    for use_dt, rooms in sorted(rows_by_date.items())
                ],
            }
            for forest_name, rows_by_date in sorted(grouped.items())
        ],
    }


def print_text(payload: dict[str, Any]) -> None:
    print("=== ForestTrip Vacancy Lookup ===")
    print(
        f"filter_hits: {payload['filter_hits']}   "
        f"fetch_failures: {payload['fetch_failures']}   "
        f"forests_scanned: {payload['forests_scanned']}"
    )
    if not payload["results"]:
        print("(no available rooms at lookup time)")
        return
    for forest in payload["results"]:
        print(f"\n{forest['forest']}")
        for date_group in forest["dates"]:
            rooms = date_group["rooms"]
            print(f"  {date_group['use_dt']} - {len(rooms)} slot(s)")
            for room in rooms[:8]:
                capacity = room["capacity"] if room["capacity"] is not None else "?"
                area = room["area"] if room["area"] is not None else "?"
                print(f"    - {room['name']} / {room['category']} / {area}sqm / max {capacity}")


def main() -> int:
    args = parse_args()
    if args.check_deps:
        check_dependencies()
        print("foresttrip-vacancy dependencies look ready")
        return 0
    session = get_session(args)
    targets = resolve_targets(args, session.forests)
    payload = collect_results(
        session=session,
        targets=targets,
        categories=args.categories,
        dates=args.dates,
        week_range=args.week_range,
        concurrency=args.concurrency,
        nights=args.nights,
    )

    if args.text and not args.json:
        print_text(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["fetch_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
