#!/usr/bin/env python3
"""Read-only vacancy lookup for Korean municipal / public campgrounds.

Each campground operator runs its own reservation system, so this helper keeps
one *provider adapter* per system and shares a single output shape across them.

The only transport implemented today is ``dzsmart``: the dzSmart (denobiz)
reservation plugin used by 강릉관광개발공사 sites. Its month calendar is rendered
client-side, so the adapter loads the official reservation page with Playwright
and parses the rendered DOM.

The helper never logs in, never clicks a reservation button, never touches
payment, and never solves the captcha / SMS verification that guards the
booking path.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

DEFAULT_TIMEOUT_MS = 30000
MAX_MONTHS = 6
SOLD_OUT_MARKERS = ("마감", "예약마감", "-")


@dataclass(frozen=True)
class Provider:
    """One reservation system entry in the adapter registry."""

    id: str
    name: str
    operator: str
    entrypoint: str
    transport: str
    requires_login: bool
    kind: str
    note: str = ""
    delegate: str | None = None


PROVIDERS: dict[str, Provider] = {
    "gtdc-yeongok": Provider(
        id="gtdc-yeongok",
        name="연곡해변 솔향기캠핑장",
        operator="강릉관광개발공사",
        entrypoint="https://camping.gtdc.or.kr",
        transport="dzsmart",
        requires_login=False,
        kind="camping",
    ),
    "gtdc-badanaeum": Provider(
        id="gtdc-badanaeum",
        name="강릉바다내음캠핑장",
        operator="강릉관광개발공사",
        entrypoint="https://autocamping.gtdc.or.kr",
        transport="dzsmart",
        requires_login=False,
        kind="camping",
    ),
    "gtdc-ojuk": Provider(
        id="gtdc-ojuk",
        name="강릉오죽한옥마을",
        operator="강릉관광개발공사",
        entrypoint="https://ojuk.gtdc.or.kr",
        transport="dzsmart",
        requires_login=False,
        kind="lodging",
        note="캠핑장이 아니라 한옥 숙박이다. 같은 dzSmart 예약 시스템을 쓴다.",
    ),
    "foresttrip": Provider(
        id="foresttrip",
        name="국립자연휴양림 (숲나들e)",
        operator="산림청",
        entrypoint="https://www.foresttrip.go.kr",
        transport="delegate",
        requires_login=True,
        kind="camping+lodging",
        note="로그인이 필요하다. 이 helper가 아니라 foresttrip-vacancy 스킬로 조회한다.",
        delegate="foresttrip-vacancy",
    ),
}

LOOKUP_PROVIDER_IDS = tuple(
    pid for pid, provider in PROVIDERS.items() if provider.transport != "delegate"
)

# Rendered slot button on a dzSmart month calendar:
# <button value="1-26-08-29-1" class="R-1-26-08-29" disabled="">
#   <span class="tit">A-대형데크</span><span class="num">마감</span></button>
BUTTON_RE = re.compile(
    r"<button\b(?P<attrs>[^>]*)>\s*"
    r'<span class="tit">(?P<title>.*?)</span>\s*'
    r'<span class="num">(?P<num>.*?)</span>\s*'
    r"</button>",
    re.IGNORECASE | re.DOTALL,
)
VALUE_RE = re.compile(r'value="(?P<value>[^"]*)"', re.IGNORECASE)
SEASON_RE = re.compile(r'<div class="season">(?P<season>.*?)</div>', re.IGNORECASE | re.DOTALL)
SLOT_VALUE_RE = re.compile(r"^(?P<zone>\d+)-(?P<yy>\d{2})-(?P<mm>\d{2})-(?P<dd>\d{2})\b")
TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", value)).strip()


def parse_remaining(raw: str) -> int | None:
    """Return the remaining site count, or None when the zone is sold out."""
    text = strip_tags(raw)
    if not text or text in SOLD_OUT_MARKERS:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return None
    return int(digits)


def parse_month_html(html: str) -> list[dict[str, Any]]:
    """Parse a dzSmart month calendar page into day records.

    Kept as a pure function so the parser is testable without a browser.
    """
    days: dict[str, dict[str, Any]] = {}

    for block in html.split("<dl")[1:]:
        season_match = SEASON_RE.search(block)
        season = strip_tags(season_match.group("season")) if season_match else None

        for match in BUTTON_RE.finditer(block):
            attrs = match.group("attrs")
            value_match = VALUE_RE.search(attrs)
            if not value_match:
                continue
            slot_match = SLOT_VALUE_RE.match(value_match.group("value"))
            if not slot_match:
                continue

            use_dt = f"20{slot_match.group('yy')}{slot_match.group('mm')}{slot_match.group('dd')}"
            disabled = re.search(r"\bdisabled\b", attrs, re.IGNORECASE) is not None
            remaining = None if disabled else parse_remaining(match.group("num"))

            day = days.setdefault(use_dt, {"use_dt": use_dt, "season": season, "zones": []})
            if day["season"] is None:
                day["season"] = season
            day["zones"].append(
                {
                    "zone_id": slot_match.group("zone"),
                    "zone": strip_tags(match.group("title")),
                    "remaining": remaining,
                    "available": remaining is not None and remaining > 0,
                }
            )

    return [days[key] for key in sorted(days)]


def fetch_month_html(entrypoint: str, month: str, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    """Load the official reservation page and return its rendered HTML.

    The month calendar is drawn client-side from a JSON procedure call, and that
    procedure returns 503 when replayed out-of-band, so a real page load is the
    only reliable read path.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError  # type: ignore[reportMissingImports]
        from playwright.sync_api import sync_playwright  # type: ignore[reportMissingImports]
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "playwright is required. Install with: python3 -m pip install playwright "
            "&& python3 -m playwright install chromium"
        ) from exc

    url = f"{entrypoint.rstrip('/')}/pub/reserv.do?tmonth={month}"
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except PlaywrightError as exc:  # pragma: no cover - environment dependent
            raise SystemExit(
                "playwright chromium browser is required. Install with: "
                "python3 -m playwright install chromium"
            ) from exc
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms)
            page.wait_for_selector("dl button span.num", timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()


def check_dependencies(*, launch_browser: bool = True) -> None:
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
            p.chromium.launch(headless=True).close()
    except PlaywrightError as exc:
        raise SystemExit(
            "playwright chromium browser is required. Install with: "
            "python3 -m playwright install chromium"
        ) from exc


def parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_dates(value: str) -> tuple[str, ...]:
    dates = parse_csv(value)
    if not dates:
        raise argparse.ArgumentTypeError("must include at least one YYYYMMDD date")
    normalized: list[str] = []
    for raw_date in dates:
        try:
            parsed = datetime.strptime(raw_date, "%Y%m%d").date()
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid YYYYMMDD date: {raw_date}") from exc
        normalized.append(parsed.strftime("%Y%m%d"))
    return tuple(sorted(dict.fromkeys(normalized)))


def parse_providers(value: str) -> tuple[str, ...]:
    ids = parse_csv(value)
    if not ids:
        raise argparse.ArgumentTypeError("must include at least one provider id")
    unknown = [pid for pid in ids if pid not in PROVIDERS]
    if unknown:
        raise argparse.ArgumentTypeError(
            "unknown provider id(s): " + ", ".join(unknown) + " (see --list-providers)"
        )
    delegated = [pid for pid in ids if PROVIDERS[pid].transport == "delegate"]
    if delegated:
        target = PROVIDERS[delegated[0]].delegate
        raise argparse.ArgumentTypeError(
            f"provider '{delegated[0]}' is served by the '{target}' skill, not this helper"
        )
    return tuple(dict.fromkeys(ids))


def parse_day_range(value: str) -> int:
    try:
        days = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if days < 1 or days > 90:
        raise argparse.ArgumentTypeError("must be between 1 and 90")
    return days


def resolve_dates(args: argparse.Namespace, *, today: date | None = None) -> tuple[str, ...]:
    if args.dates:
        return args.dates
    start = today or date.today()
    return tuple(
        (start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(args.day_range)
    )


def months_for(dates: tuple[str, ...]) -> list[str]:
    months = sorted({value[:6] for value in dates})
    if len(months) > MAX_MONTHS:
        raise SystemExit(f"requested {len(months)} months, limit is {MAX_MONTHS}")
    return months


def collect_results(
    *,
    provider_ids: tuple[str, ...],
    dates: tuple[str, ...],
    include_full: bool = False,
    zone_filter: str | None = None,
    fetcher: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    fetch = fetcher or (lambda entrypoint, month: fetch_month_html(entrypoint, month))
    wanted = set(dates)
    months = months_for(dates)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    hits = 0

    for provider_id in provider_ids:
        provider = PROVIDERS[provider_id]
        day_rows: dict[str, dict[str, Any]] = {}

        for month in months:
            try:
                html = fetch(provider.entrypoint, month)
            except SystemExit:
                raise
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                failures.append(
                    {
                        "provider": provider_id,
                        "month": month,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue

            for day in parse_month_html(html):
                if day["use_dt"] not in wanted:
                    continue
                zones = day["zones"]
                if zone_filter:
                    needle = zone_filter.lower()
                    zones = [zone for zone in zones if needle in zone["zone"].lower()]
                if not include_full:
                    zones = [zone for zone in zones if zone["available"]]
                if not zones:
                    continue
                hits += sum(1 for zone in zones if zone["available"])
                day_rows[day["use_dt"]] = {
                    "use_dt": day["use_dt"],
                    "season": day["season"],
                    "zones": zones,
                }

        if day_rows:
            results.append(
                {
                    "provider": provider_id,
                    "name": provider.name,
                    "operator": provider.operator,
                    "entrypoint": provider.entrypoint,
                    "dates": [day_rows[key] for key in sorted(day_rows)],
                }
            )

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dates": list(dates),
        "providers_scanned": len(provider_ids),
        "filter_hits": hits,
        "fetch_failures": len(failures),
        "failures": failures,
        "results": results,
    }


def print_providers() -> None:
    print("=== Campsite provider registry ===")
    for provider in PROVIDERS.values():
        login = "login required" if provider.requires_login else "no login"
        target = f" -> {provider.delegate} skill" if provider.delegate else ""
        print(f"\n{provider.id}  ({provider.transport}, {login}){target}")
        print(f"  name      : {provider.name}")
        print(f"  operator  : {provider.operator}")
        print(f"  entrypoint: {provider.entrypoint}")
        print(f"  kind      : {provider.kind}")
        if provider.note:
            print(f"  note      : {provider.note}")


def print_text(payload: dict[str, Any]) -> None:
    print("=== Korean Campsite Vacancy Lookup ===")
    print(
        f"filter_hits: {payload['filter_hits']}   "
        f"fetch_failures: {payload['fetch_failures']}   "
        f"providers_scanned: {payload['providers_scanned']}"
    )
    if not payload["results"]:
        print("(no available sites at lookup time)")
    for site in payload["results"]:
        print(f"\n{site['name']}  ({site['operator']})")
        for day in site["dates"]:
            season = f" [{day['season']}]" if day["season"] else ""
            print(f"  {day['use_dt']}{season}")
            for zone in day["zones"]:
                remaining = "마감" if zone["remaining"] is None else f"{zone['remaining']}면"
                print(f"    - {zone['zone']} / {remaining}")
    for failure in payload["failures"]:
        print(f"\n! fetch failed: {failure['provider']} {failure['month']} — {failure['error']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only vacancy lookup for Korean municipal / public campgrounds.",
    )
    parser.add_argument("--list-providers", action="store_true", help="print the adapter registry")
    parser.add_argument("--check-deps", action="store_true", help="verify Playwright is usable")
    parser.add_argument(
        "--provider",
        type=parse_providers,
        default=LOOKUP_PROVIDER_IDS,
        help="comma-separated provider ids (default: every non-delegated provider)",
    )
    parser.add_argument("--dates", type=parse_dates, help="comma-separated YYYYMMDD dates")
    parser.add_argument(
        "--day-range",
        type=parse_day_range,
        default=7,
        help="used only when --dates is omitted: today plus N days (default 7)",
    )
    parser.add_argument("--zone", help="substring filter on the zone name, e.g. 글램핑")
    parser.add_argument(
        "--include-full", action="store_true", help="also list sold-out (마감) zones"
    )
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS)
    parser.add_argument("--text", action="store_true", help="human-readable summary")
    parser.add_argument("--json", action="store_true", help="structured JSON output (default)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_providers:
        print_providers()
        return 0
    if args.check_deps:
        check_dependencies()
        print("korean-campsite-vacancy dependencies look ready")
        return 0

    dates = resolve_dates(args)
    payload = collect_results(
        provider_ids=tuple(args.provider),
        dates=dates,
        include_full=args.include_full,
        zone_filter=args.zone,
        fetcher=lambda entrypoint, month: fetch_month_html(
            entrypoint, month, timeout_ms=args.timeout_ms
        ),
    )

    if args.text and not args.json:
        print_text(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["fetch_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
