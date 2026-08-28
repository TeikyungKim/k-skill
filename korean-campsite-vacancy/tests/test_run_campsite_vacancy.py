import argparse
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
HELPER_PATH = TESTS_DIR.parent / "scripts" / "run_campsite_vacancy.py"
FIXTURES_DIR = TESTS_DIR / "fixtures"


def load_helper():
    spec = importlib.util.spec_from_file_location("run_campsite_vacancy", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper from {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_campsite_vacancy"] = module
    spec.loader.exec_module(module)
    return module


helper = load_helper()

YEONGOK_HTML = (FIXTURES_DIR / "gtdc_yeongok_202608.html").read_text(encoding="utf-8")


def fixture_fetcher(_entrypoint, _month):
    return YEONGOK_HTML


class ParseMonthHtmlTest(unittest.TestCase):
    def setUp(self):
        self.days = helper.parse_month_html(YEONGOK_HTML)
        self.by_date = {day["use_dt"]: day for day in self.days}

    def test_days_are_sorted_and_skip_empty_cells(self):
        self.assertEqual([day["use_dt"] for day in self.days], ["20260829", "20260830", "20260831"])

    def test_two_digit_year_expands_from_the_button_value(self):
        self.assertIn("20260829", self.by_date)

    def test_season_is_carried_per_day(self):
        self.assertEqual(self.by_date["20260829"]["season"], "준성수기주말")
        self.assertEqual(self.by_date["20260830"]["season"], "준성수기주중")

    def test_disabled_zone_reads_as_sold_out(self):
        zones = {zone["zone"]: zone for zone in self.by_date["20260829"]["zones"]}
        self.assertIsNone(zones["A-대형데크"]["remaining"])
        self.assertFalse(zones["A-대형데크"]["available"])

    def test_enabled_zone_keeps_the_remaining_count(self):
        zones = {zone["zone"]: zone for zone in self.by_date["20260830"]["zones"]}
        self.assertEqual(zones["A-대형데크"]["remaining"], 17)
        self.assertTrue(zones["A-대형데크"]["available"])
        self.assertEqual(zones["G-글램핑"]["remaining"], 6)

    def test_zone_id_comes_from_the_slot_value(self):
        zones = {zone["zone"]: zone for zone in self.by_date["20260831"]["zones"]}
        self.assertEqual(zones["I-희망하우스"]["zone_id"], "9")

    def test_unparsable_html_yields_no_days(self):
        self.assertEqual(helper.parse_month_html("<html><body>점검중</body></html>"), [])


class ParseRemainingTest(unittest.TestCase):
    def test_sold_out_markers_are_none(self):
        for marker in ("마감", "예약마감", "-", "", "   "):
            self.assertIsNone(helper.parse_remaining(marker))

    def test_digits_are_extracted(self):
        self.assertEqual(helper.parse_remaining("17"), 17)
        self.assertEqual(helper.parse_remaining(" 3 "), 3)


class ArgumentParsingTest(unittest.TestCase):
    def test_dates_are_normalized_deduped_and_sorted(self):
        self.assertEqual(
            helper.parse_dates("20260831,20260829,20260829"), ("20260829", "20260831")
        )

    def test_invalid_date_is_rejected(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            helper.parse_dates("2026-08-29")
        with self.assertRaises(argparse.ArgumentTypeError):
            helper.parse_dates("20260230")

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            helper.parse_providers("nope")

    def test_delegated_provider_points_at_the_other_skill(self):
        with self.assertRaises(argparse.ArgumentTypeError) as ctx:
            helper.parse_providers("foresttrip")
        self.assertIn("foresttrip-vacancy", str(ctx.exception))

    def test_default_providers_exclude_delegates(self):
        self.assertNotIn("foresttrip", helper.LOOKUP_PROVIDER_IDS)
        self.assertIn("gtdc-yeongok", helper.LOOKUP_PROVIDER_IDS)

    def test_day_range_bounds(self):
        self.assertEqual(helper.parse_day_range("7"), 7)
        with self.assertRaises(argparse.ArgumentTypeError):
            helper.parse_day_range("0")
        with self.assertRaises(argparse.ArgumentTypeError):
            helper.parse_day_range("91")

    def test_resolve_dates_walks_forward_from_today(self):
        args = argparse.Namespace(dates=None, day_range=3)
        self.assertEqual(
            helper.resolve_dates(args, today=date(2026, 8, 29)),
            ("20260829", "20260830", "20260831"),
        )

    def test_months_for_rejects_too_wide_a_span(self):
        with self.assertRaises(SystemExit):
            helper.months_for(tuple(f"2026{month:02d}01" for month in range(1, 9)))


class CollectResultsTest(unittest.TestCase):
    def test_available_only_by_default(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260829",),
            fetcher=fixture_fetcher,
        )
        zones = payload["results"][0]["dates"][0]["zones"]
        self.assertEqual([zone["zone"] for zone in zones], ["B-일반형데크"])
        self.assertEqual(payload["filter_hits"], 1)
        self.assertEqual(payload["fetch_failures"], 0)

    def test_include_full_keeps_sold_out_zones(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260829",),
            include_full=True,
            fetcher=fixture_fetcher,
        )
        zones = payload["results"][0]["dates"][0]["zones"]
        self.assertEqual(len(zones), 4)
        self.assertEqual(payload["filter_hits"], 1)

    def test_zone_filter_narrows_results(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260830",),
            zone_filter="글램핑",
            fetcher=fixture_fetcher,
        )
        zones = payload["results"][0]["dates"][0]["zones"]
        self.assertEqual([zone["zone"] for zone in zones], ["G-글램핑"])

    def test_dates_outside_the_request_are_dropped(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260831",),
            fetcher=fixture_fetcher,
        )
        self.assertEqual([day["use_dt"] for day in payload["results"][0]["dates"]], ["20260831"])

    def test_provider_with_no_vacancy_is_omitted_not_faked(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260901",),
            fetcher=fixture_fetcher,
        )
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["filter_hits"], 0)

    def test_fetch_failure_is_reported_not_swallowed(self):
        def boom(_entrypoint, _month):
            raise RuntimeError("upstream 503")

        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260829",),
            fetcher=boom,
        )
        self.assertEqual(payload["fetch_failures"], 1)
        self.assertIn("upstream 503", payload["failures"][0]["error"])
        self.assertEqual(payload["results"], [])

    def test_multiple_providers_are_scanned(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok", "gtdc-badanaeum"),
            dates=("20260830",),
            fetcher=fixture_fetcher,
        )
        self.assertEqual(payload["providers_scanned"], 2)
        self.assertEqual(
            [site["provider"] for site in payload["results"]],
            ["gtdc-yeongok", "gtdc-badanaeum"],
        )


class OutputTest(unittest.TestCase):
    def setUp(self):
        self.payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260830",),
            fetcher=fixture_fetcher,
        )

    def test_text_output_mentions_site_and_counts(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            helper.print_text(self.payload)
        output = buffer.getvalue()
        self.assertIn("연곡해변 솔향기캠핑장", output)
        self.assertIn("20260830", output)
        self.assertIn("17면", output)

    def test_empty_result_says_so_explicitly(self):
        empty = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260901",),
            fetcher=fixture_fetcher,
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            helper.print_text(empty)
        self.assertIn("no available sites", buffer.getvalue())

    def test_payload_is_json_serializable(self):
        json.dumps(self.payload, ensure_ascii=False)

    def test_list_providers_output_flags_the_delegate(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            helper.print_providers()
        output = buffer.getvalue()
        self.assertIn("gtdc-yeongok", output)
        self.assertIn("foresttrip-vacancy skill", output)


if __name__ == "__main__":
    unittest.main()
