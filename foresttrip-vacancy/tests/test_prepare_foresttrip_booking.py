import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
HELPER_PATH = SCRIPT_DIR.parent / "scripts" / "prepare_foresttrip_booking.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("prepare_foresttrip_booking", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper from {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["prepare_foresttrip_booking"] = module
    spec.loader.exec_module(module)
    return module


helper = load_helper()


def request(**overrides):
    values = {
        "forest_id": "ID02030054",
        "check_in": date(2026, 9, 6),
        "check_out": date(2026, 9, 7),
        "room_name": "데크 01",
        "facility_code": None,
        "facility_type": "국민여가오토캠핑장",
        "queue_timeout_sec": 180,
        "browser_channel": "chromium",
    }
    values.update(overrides)
    return helper.BookingRequest(**values)


class ValidationTest(unittest.TestCase):
    def test_valid_request_is_generalized(self):
        args = SimpleNamespace(
            forest_id="ID02030054",
            check_in=date(2026, 9, 6),
            check_out=date(2026, 9, 8),
            room_name="데크 26 (데크 옆 주차X)",
            facility_code=None,
            facility_type="국민여가오토캠핑장",
            queue_timeout=180,
            browser_channel="chromium",
        )
        result = helper.validate_request(args, today=date(2026, 8, 28))
        self.assertEqual(result.nights, 2)
        self.assertEqual(result.room_name, "데크 26 (데크 옆 주차X)")

    def test_past_check_in_is_rejected(self):
        args = SimpleNamespace(
            forest_id="ID02030054",
            check_in=date(2026, 8, 27),
            check_out=date(2026, 8, 29),
            room_name="데크 01",
            facility_code="02005",
            facility_type=None,
            queue_timeout=180,
            browser_channel="chromium",
        )
        with self.assertRaisesRegex(helper.BookingPreparationError, "past"):
            helper.validate_request(args, today=date(2026, 8, 28))

    def test_checkout_must_follow_checkin(self):
        args = SimpleNamespace(
            forest_id="ID02030054",
            check_in=date(2026, 9, 6),
            check_out=date(2026, 9, 6),
            room_name="데크 01",
            facility_code="02005",
            facility_type=None,
            queue_timeout=180,
            browser_channel="chromium",
        )
        with self.assertRaisesRegex(helper.BookingPreparationError, "after"):
            helper.validate_request(args, today=date(2026, 8, 28))


class SelectionTest(unittest.TestCase):
    OPTIONS = [
        {"value": "01001", "label": "숲속의집"},
        {"value": "02005", "label": "국민여가오토캠핑장"},
        {"value": "02008", "label": "캠핑하우스"},
    ]

    def test_facility_label_resolves_to_code(self):
        self.assertEqual(helper.select_facility_option(self.OPTIONS, request()), "02005")

    def test_facility_code_resolves_directly(self):
        target = request(facility_code="02008", facility_type=None)
        self.assertEqual(helper.select_facility_option(self.OPTIONS, target), "02008")

    def test_unknown_facility_reports_available_options(self):
        target = request(facility_type="없는시설")
        with self.assertRaisesRegex(helper.BookingPreparationError, "available"):
            helper.select_facility_option(self.OPTIONS, target)

    def test_room_selection_deduplicates_responsive_copies(self):
        candidates = [
            {"goods_id": "G001", "text": "[국민여가오토캠핑장] 데크 01 4인실"},
            {"goods_id": "G001", "text": "예약하기 데크 01"},
            {"goods_id": "G002", "text": "[국민여가오토캠핑장] 데크 02 4인실"},
        ]
        self.assertEqual(helper.choose_goods_id(candidates, "데크 01"), "G001")

    def test_ambiguous_room_name_is_rejected(self):
        candidates = [
            {"goods_id": "G001", "text": "데크 01"},
            {"goods_id": "G010", "text": "데크 010"},
        ]
        with self.assertRaisesRegex(helper.BookingPreparationError, "multiple"):
            helper.choose_goods_id(candidates, "데크 01")


class SafetyTest(unittest.TestCase):
    def test_url_redaction_removes_queue_and_csrf_tokens(self):
        value = "https://www.foresttrip.go.kr/rep/path.do?_csrf=secret&netfunnel_key=token"
        self.assertEqual(helper.redact_url(value), "https://www.foresttrip.go.kr/rep/path.do")

    def test_navigation_payment_links_do_not_trigger_false_positive(self):
        body = "결제대기내역 결제내역 결제관련 예약금액 20,000원"
        self.assertFalse(helper.is_pre_payment_page("https://www.foresttrip.go.kr/rep/or/sssn/page.do", body))

    def test_payment_form_is_detected(self):
        self.assertTrue(
            helper.is_pre_payment_page(
                "https://www.foresttrip.go.kr/rep/order/page.do",
                "결제수단 선택 카드 계좌이체",
            )
        )

    def test_dotenv_only_loads_expected_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "secrets.env"
            path.write_text(
                "KSKILL_FORESTTRIP_ID=test-user\n"
                "KSKILL_FORESTTRIP_PASSWORD=test-password\n"
                "UNRELATED=do-not-load\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                helper.load_dotenv(path)
                self.assertEqual(os.environ["KSKILL_FORESTTRIP_ID"], "test-user")
                self.assertEqual(os.environ["KSKILL_FORESTTRIP_PASSWORD"], "test-password")
                self.assertNotIn("UNRELATED", os.environ)


if __name__ == "__main__":
    unittest.main()
