#!/usr/bin/env python3
"""Open a visible ForestTrip booking session and stop before payment.

The helper uses only the official rendered website and its own NetFunnel flow.
It can log in, run one reservation search, and select one exact facility. It
never solves CAPTCHA, accepts terms, submits the reservation, or clicks a
payment control. The browser remains open so the user can complete required
human-only steps. If a payment page appears, automation stays stopped there.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


LOGIN_URL = "https://www.foresttrip.go.kr/com/login.do"
FOREST_MAIN_URL = "https://www.foresttrip.go.kr/indvz/main.do?hmpgId={forest_id}"
RESULT_PATH = "/rep/or/sssn/fcfsRsrvtPssblGoodsDetls.do"
DEFAULT_DOTENV = "~/.config/k-skill/secrets.env"
DEFAULT_QUEUE_TIMEOUT_SEC = 180
PAYMENT_PATH_MARKERS = ("/pay", "payment", "sttlmform", "sttlminfo")
PAYMENT_TEXT_MARKERS = ("결제수단 선택", "결제정보 입력", "결제하기")


class BookingPreparationError(RuntimeError):
    """A safe, recoverable stop in the guided booking preparation."""


@dataclass(frozen=True)
class BookingRequest:
    forest_id: str
    check_in: date
    check_out: date
    room_name: str
    facility_code: str | None
    facility_type: str | None
    queue_timeout_sec: int
    browser_channel: str

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def parse_yyyymmdd(value: str) -> date:
    try:
        parsed = datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid YYYYMMDD date: {value}") from exc
    if parsed.strftime("%Y%m%d") != value:
        raise argparse.ArgumentTypeError(f"invalid YYYYMMDD date: {value}")
    return parsed


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open ForestTrip in a visible browser and prepare one exact booking up to the CAPTCHA/payment handoff.",
    )
    parser.add_argument("--forest-id", help="Official ForestTrip hmpgId/insttId, for example ID02030054.")
    parser.add_argument("--check-in", type=parse_yyyymmdd, help="Check-in date as YYYYMMDD.")
    parser.add_argument("--check-out", type=parse_yyyymmdd, help="Check-out date as YYYYMMDD.")
    parser.add_argument("--room-name", help="Exact visible room or campsite name.")
    facility = parser.add_mutually_exclusive_group()
    facility.add_argument("--facility-code", help="Official product-class option value, for example 02005.")
    facility.add_argument("--facility-type", help="Exact or unique partial product-class label, for example 국민여가오토캠핑장.")
    parser.add_argument(
        "--queue-timeout",
        type=positive_int,
        default=DEFAULT_QUEUE_TIMEOUT_SEC,
        help=f"Seconds to wait for the official queue (default: {DEFAULT_QUEUE_TIMEOUT_SEC}).",
    )
    parser.add_argument(
        "--browser-channel",
        choices=("chromium", "chrome", "msedge"),
        default="chromium",
        help="Visible browser channel to launch (default: bundled Playwright Chromium).",
    )
    parser.add_argument(
        "--dotenv",
        default=DEFAULT_DOTENV,
        help="Credential dotenv fallback; values are never printed.",
    )
    parser.add_argument("--check-deps", action="store_true", help="Check Python and Playwright dependencies, then exit.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and credentials without opening a browser.")
    args = parser.parse_args(argv)

    if not args.check_deps:
        missing = [
            flag
            for flag, value in (
                ("--forest-id", args.forest_id),
                ("--check-in", args.check_in),
                ("--check-out", args.check_out),
                ("--room-name", args.room_name),
            )
            if not value
        ]
        if missing:
            parser.error("required arguments: " + ", ".join(missing))
        if not (args.facility_code or args.facility_type):
            parser.error("one of --facility-code or --facility-type is required")
    return args


def validate_request(args: argparse.Namespace, *, today: date | None = None) -> BookingRequest:
    today = today or date.today()
    forest_id = str(args.forest_id).strip()
    room_name = str(args.room_name).strip()
    facility_code = str(args.facility_code).strip() if args.facility_code else None
    facility_type = str(args.facility_type).strip() if args.facility_type else None

    if not re.fullmatch(r"ID[0-9A-Za-z_-]{4,40}", forest_id):
        raise BookingPreparationError("--forest-id is not a valid ForestTrip ID")
    if args.check_in < today:
        raise BookingPreparationError("check-in date is in the past")
    if args.check_out <= args.check_in:
        raise BookingPreparationError("check-out must be after check-in")
    if not room_name:
        raise BookingPreparationError("--room-name must not be empty")

    return BookingRequest(
        forest_id=forest_id,
        check_in=args.check_in,
        check_out=args.check_out,
        room_name=room_name,
        facility_code=facility_code,
        facility_type=facility_type,
        queue_timeout_sec=args.queue_timeout,
        browser_channel=args.browser_channel,
    )


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if name in {"KSKILL_FORESTTRIP_ID", "KSKILL_FORESTTRIP_PASSWORD"}:
            os.environ.setdefault(name, value)


def require_credentials(dotenv_path: str) -> tuple[str, str]:
    load_dotenv(Path(dotenv_path).expanduser())
    user_id = os.getenv("KSKILL_FORESTTRIP_ID")
    password = os.getenv("KSKILL_FORESTTRIP_PASSWORD")
    if not user_id or not password:
        raise BookingPreparationError(
            "missing KSKILL_FORESTTRIP_ID or KSKILL_FORESTTRIP_PASSWORD; "
            "set environment variables or the protected dotenv file"
        )
    return user_id, password


def check_dependencies(*, launch: bool) -> None:
    if sys.version_info < (3, 9):
        raise BookingPreparationError("Python 3.9+ is required")
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BookingPreparationError(
            "Playwright is required: python -m pip install playwright"
        ) from exc
    if not launch:
        return
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
    except PlaywrightError as exc:
        raise BookingPreparationError(
            "Playwright Chromium is required: python -m playwright install chromium"
        ) from exc


def redact_url(value: str) -> str:
    split = urlsplit(value)
    return urlunsplit((split.scheme, split.netloc, split.path, "", ""))


def select_facility_option(options: Iterable[dict[str, str]], request: BookingRequest) -> str:
    normalized = [
        {"value": str(item.get("value", "")), "label": str(item.get("label", ""))}
        for item in options
        if item.get("value")
    ]
    if request.facility_code:
        matches = [item for item in normalized if item["value"] == request.facility_code]
    else:
        target = normalized_text(request.facility_type or "")
        exact = [item for item in normalized if normalized_text(item["label"]) == target]
        matches = exact or [item for item in normalized if target in normalized_text(item["label"])]
    if not matches:
        available = ", ".join(f"{item['label']}({item['value']})" for item in normalized)
        raise BookingPreparationError(f"facility type was not found; available: {available}")
    values = {item["value"] for item in matches}
    if len(values) != 1:
        labels = ", ".join(item["label"] for item in matches)
        raise BookingPreparationError(f"facility type is ambiguous: {labels}")
    return next(iter(values))


def choose_goods_id(candidates: Iterable[dict[str, str]], room_name: str) -> str:
    target = normalized_text(room_name)
    matches: dict[str, str] = {}
    for candidate in candidates:
        goods_id = str(candidate.get("goods_id", ""))
        text = str(candidate.get("text", ""))
        if goods_id and target in normalized_text(text):
            matches[goods_id] = text
    if not matches:
        raise BookingPreparationError(f"requested room is not available: {room_name}")
    if len(matches) != 1:
        raise BookingPreparationError(
            f"room name matched multiple facilities; use a more exact name: {room_name}"
        )
    return next(iter(matches))


def is_pre_payment_page(url: str, body_text: str) -> bool:
    path = urlsplit(url).path.casefold()
    if any(marker in path for marker in PAYMENT_PATH_MARKERS):
        return True
    compact = normalized_text(body_text)
    return any(normalized_text(marker) in compact for marker in PAYMENT_TEXT_MARKERS)


def login(page: Any, user_id: str, password: str) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
    if page.locator("#mmberId").count() == 0:
        raise BookingPreparationError("ForestTrip login form was not found")
    page.locator("#mmberId").fill(user_id)
    page.locator("#gnrlMmberPssrd").fill(password)
    page.locator("input.loginBtn").click()
    page.wait_for_load_state("domcontentloaded")
    if page.locator("#mmberId").count() and page.locator("#mmberId").is_visible():
        raise BookingPreparationError("ForestTrip login failed")


def open_availability(page: Any, request: BookingRequest) -> None:
    page.goto(
        FOREST_MAIN_URL.format(forest_id=request.forest_id),
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    if page.locator("#goodsClssCd").count() == 0:
        raise BookingPreparationError("official reservation search controls were not found")
    options = page.locator("#goodsClssCd option").evaluate_all(
        "els => els.map(e => ({value: e.value, label: (e.textContent || '').trim()}))"
    )
    facility_value = select_facility_option(options, request)
    page.select_option("#goodsClssCd", facility_value)
    page.evaluate(
        """
        ({checkIn, checkOut}) => {
          document.querySelector('#rsrvtBgDt').value = checkIn;
          document.querySelector('#rsrvtEdDt').value = checkOut;
          const picker = document.querySelector('#calPicker');
          if (picker) picker.value = `${checkIn.slice(0,4)}-${checkIn.slice(4,6)}-${checkIn.slice(6,8)} - ${checkOut.slice(0,4)}-${checkOut.slice(4,6)}-${checkOut.slice(6,8)}`;
          if (typeof fn_goRsvt !== 'function') throw new Error('official reservation function not found');
          fn_goRsvt();
        }
        """,
        {
            "checkIn": request.check_in.strftime("%Y%m%d"),
            "checkOut": request.check_out.strftime("%Y%m%d"),
        },
    )
    try:
        page.wait_for_url(
            f"**{RESULT_PATH}**",
            timeout=request.queue_timeout_sec * 1000,
            wait_until="domcontentloaded",
        )
    except Exception as exc:
        if RESULT_PATH not in urlsplit(page.url).path:
            raise BookingPreparationError(
                "official queue did not finish in time; continue manually in the open browser"
            ) from exc
    page.wait_for_timeout(1_500)


def select_room(page: Any, request: BookingRequest) -> None:
    candidates = page.evaluate(
        r"""
        () => {
          const result = [];
          for (const anchor of document.querySelectorAll('a[onclick*="click_go_mobileRsrvt"]')) {
            const onclick = anchor.getAttribute('onclick') || '';
            const match = onclick.match(/click_go_mobileRsrvt\('([^']+)'\)/);
            if (!match) continue;
            const box = anchor.closest('.list_box') || anchor.parentElement?.parentElement || anchor;
            result.push({goods_id: match[1], text: (box.innerText || anchor.innerText || '').trim()});
          }
          return result;
        }
        """
    )
    goods_id = choose_goods_id(candidates, request.room_name)
    page.evaluate(
        """
        goodsId => {
          if (typeof click_go_mobileRsrvt !== 'function') {
            throw new Error('official room-selection function not found');
          }
          click_go_mobileRsrvt(goodsId);
        }
        """,
        goods_id,
    )
    page.wait_for_timeout(1_000)


def page_body_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=2_000)
    except Exception:
        return ""


def add_status_banner(page: Any, message: str, color: str) -> None:
    try:
        page.evaluate(
            """
            ({message, color}) => {
              let banner = document.querySelector('#kskill-foresttrip-status');
              if (!banner) {
                banner = document.createElement('div');
                banner.id = 'kskill-foresttrip-status';
                Object.assign(banner.style, {
                  position: 'fixed', top: '0', left: '0', right: '0', zIndex: '2147483647',
                  padding: '10px 16px', color: '#fff', fontWeight: '700', textAlign: 'center',
                  boxShadow: '0 2px 8px rgba(0,0,0,.3)', pointerEvents: 'none'
                });
                document.documentElement.appendChild(banner);
              }
              banner.style.background = color;
              banner.textContent = message;
            }
            """,
            {"message": message, "color": color},
        )
    except Exception:
        pass


def wait_for_user(context: Any, initial_page: Any) -> None:
    print("BROWSER_READY: exact facility selected on the official ForestTrip page.")
    print("MANUAL_STEP: enter the displayed anti-bot number, review/accept the terms, and press 예약 yourself.")
    print("PAYMENT_STOP: this helper will not click reservation submission or any payment control.")
    add_status_banner(
        initial_page,
        "자동화 중지: 자동예약 방지숫자와 약관 동의는 직접 완료하세요. 결제는 자동 실행되지 않습니다.",
        "#b45309",
    )
    announced_payment = False
    while True:
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            return
        for page in pages:
            body = page_body_text(page)
            if is_pre_payment_page(page.url, body):
                if not announced_payment:
                    print(f"PRE_PAYMENT_READY: {redact_url(page.url)}")
                    print("Automation is stopped. Review the target and amount before any manual payment.")
                    announced_payment = True
                add_status_banner(
                    page,
                    "결제 직전 화면: 자동화가 멈췄습니다. 대상·날짜·금액을 직접 확인하세요.",
                    "#b91c1c",
                )
        time.sleep(1)


def run_browser(request: BookingRequest, user_id: str, password: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        launch_args: dict[str, Any] = {"headless": False}
        if request.browser_channel != "chromium":
            launch_args["channel"] = request.browser_channel
        browser = pw.chromium.launch(**launch_args)
        context = browser.new_context(locale="ko-KR", viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        try:
            login(page, user_id, password)
            open_availability(page, request)
            select_room(page, request)
            body = page_body_text(page)
            if "자동예약 방지숫자" not in body and "약관에 동의합니다" not in body:
                raise BookingPreparationError(
                    "room was selected, but the official CAPTCHA/terms handoff was not detected"
                )
        except BookingPreparationError as exc:
            print(f"SAFE_STOP: {exc}", file=sys.stderr)
            print(f"OPEN_PAGE: {redact_url(page.url)}", file=sys.stderr)
        try:
            wait_for_user(context, page)
        except KeyboardInterrupt:
            print("Browser session ended by user.")
        finally:
            if browser.is_connected():
                browser.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        check_dependencies(launch=args.check_deps)
        if args.check_deps:
            print("dependencies: ok")
            return 0
        request = validate_request(args)
        user_id, password = require_credentials(args.dotenv)
        print(
            "validated: "
            f"forest={request.forest_id} check_in={request.check_in:%Y%m%d} "
            f"check_out={request.check_out:%Y%m%d} nights={request.nights} "
            f"room={request.room_name}"
        )
        if args.dry_run:
            print("dry-run: browser not opened")
            return 0
        run_browser(request, user_id, password)
        return 0
    except BookingPreparationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
