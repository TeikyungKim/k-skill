import argparse
import importlib.util
import os
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock


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
JARASEOM_HTML = (FIXTURES_DIR / "thankq_jaraseom_20260905.html").read_text(encoding="utf-8")
GMUC_HTML = (FIXTURES_DIR / "gmuc_dodeoksan.html").read_text(encoding="utf-8")
MAKETICKET_HTML = (FIXTURES_DIR / "maketicket_jangho_202609.html").read_text(encoding="utf-8")
JARASEOM_VIEW_HTML = (FIXTURES_DIR / "thankq_jaraseom_view.html").read_text(encoding="utf-8")


def maketicket_fetcher(_entrypoint, _gd_seq, _month):
    return MAKETICKET_HTML


def gmuc_fetcher(_entrypoint):
    return GMUC_HTML


def fixture_fetcher(_entrypoint, _month):
    return YEONGOK_HTML


def thankq_fetcher(_entrypoint, _camp_seq, _use_dt):
    return JARASEOM_HTML


def thankq_view_fetcher(_entrypoint, _camp_seq):
    return JARASEOM_VIEW_HTML


DZSMART_FETCHERS = {"dzsmart": fixture_fetcher}
THANKQ_FETCHERS = {"thankq": thankq_fetcher, "thankq_view": thankq_view_fetcher}
ALL_FETCHERS = {"dzsmart": fixture_fetcher, **THANKQ_FETCHERS}


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
            fetchers=DZSMART_FETCHERS,
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
            fetchers=DZSMART_FETCHERS,
        )
        zones = payload["results"][0]["dates"][0]["zones"]
        self.assertEqual(len(zones), 4)
        self.assertEqual(payload["filter_hits"], 1)

    def test_zone_filter_narrows_results(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260830",),
            zone_filter="글램핑",
            fetchers=DZSMART_FETCHERS,
        )
        zones = payload["results"][0]["dates"][0]["zones"]
        self.assertEqual([zone["zone"] for zone in zones], ["G-글램핑"])

    def test_dates_outside_the_request_are_dropped(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260831",),
            fetchers=DZSMART_FETCHERS,
        )
        self.assertEqual([day["use_dt"] for day in payload["results"][0]["dates"]], ["20260831"])

    def test_provider_with_no_vacancy_is_omitted_not_faked(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260829",),
            zone_filter="없는존이름",
            fetchers=DZSMART_FETCHERS,
        )
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["filter_hits"], 0)

    def test_date_missing_from_the_calendar_is_reported_not_dropped(self):
        # 20260901 is outside the fixture's 2026-08 calendar. Dropping it would
        # read as "no vacancy" when the truth is "that month is not open yet".
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260901",),
            fetchers=DZSMART_FETCHERS,
        )
        day = payload["results"][0]["dates"][0]
        self.assertEqual(day["use_dt"], "20260901")
        self.assertEqual(day["booking_status"], "not_open")
        self.assertIn("예약 달력", day["status_note"])
        self.assertEqual(day["zones"], [])
        self.assertEqual(payload["filter_hits"], 0)

    def test_fetch_failure_is_reported_not_swallowed(self):
        def boom(_entrypoint, _month):
            raise RuntimeError("upstream 503")

        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260829",),
            fetchers={"dzsmart": boom},
        )
        self.assertEqual(payload["fetch_failures"], 1)
        self.assertIn("upstream 503", payload["failures"][0]["error"])
        self.assertEqual(payload["results"], [])

    def test_multiple_providers_are_scanned(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok", "gtdc-badanaeum"),
            dates=("20260830",),
            fetchers=DZSMART_FETCHERS,
        )
        self.assertEqual(payload["providers_scanned"], 2)
        self.assertEqual(
            [site["provider"] for site in payload["results"]],
            ["gtdc-yeongok", "gtdc-badanaeum"],
        )


class ParseThankqHtmlTest(unittest.TestCase):
    def setUp(self):
        self.zones = helper.parse_thankq_html(JARASEOM_HTML)
        self.by_name = {zone["zone"]: zone for zone in self.zones}

    def test_commented_duplicate_blocks_are_not_counted_twice(self):
        self.assertEqual(len(self.zones), 4)
        self.assertEqual(
            [zone["zone"] for zone in self.zones],
            ["사이트 A", "사이트 B", "카라반 B", "카라반 C"],
        )

    def test_og_badge_keeps_the_remaining_count(self):
        self.assertEqual(self.by_name["사이트 A"]["remaining"], 34)
        self.assertTrue(self.by_name["사이트 A"]["available"])

    def test_sold_out_badge_reads_as_unavailable(self):
        self.assertIsNone(self.by_name["사이트 B"]["remaining"])
        self.assertFalse(self.by_name["사이트 B"]["available"])

    def test_red_badge_reads_as_unavailable(self):
        self.assertIsNone(self.by_name["카라반 B"]["remaining"])
        self.assertFalse(self.by_name["카라반 B"]["available"])

    def test_price_is_captured(self):
        self.assertEqual(self.by_name["사이트 A"]["price"], "45,000원")
        self.assertEqual(self.by_name["카라반 C"]["price"], "160,000원")

    def test_unparsable_fragment_yields_no_zones(self):
        self.assertEqual(helper.parse_thankq_html("<html><body>점검중</body></html>"), [])


class ThankqCollectTest(unittest.TestCase):
    def test_one_request_per_date_and_available_only(self):
        payload = helper.collect_results(
            provider_ids=("thankq-jaraseom",),
            dates=("20260905", "20260906"),
            fetchers=ALL_FETCHERS,
        )
        site = payload["results"][0]
        self.assertEqual(site["operator"], "가평군시설관리공단")
        self.assertEqual(site["transport"], "thankq")
        self.assertEqual([day["use_dt"] for day in site["dates"]], ["20260905", "20260906"])
        self.assertEqual(
            [zone["zone"] for zone in site["dates"][0]["zones"]], ["사이트 A", "카라반 C"]
        )

    def test_thankq_has_no_season(self):
        payload = helper.collect_results(
            provider_ids=("thankq-jaraseom",),
            dates=("20260905",),
            fetchers=ALL_FETCHERS,
        )
        self.assertIsNone(payload["results"][0]["dates"][0]["season"])

    def test_include_full_keeps_sold_out_zones(self):
        payload = helper.collect_results(
            provider_ids=("thankq-jaraseom",),
            dates=("20260905",),
            include_full=True,
            fetchers=ALL_FETCHERS,
        )
        self.assertEqual(len(payload["results"][0]["dates"][0]["zones"]), 4)

    def test_failure_scope_is_the_date_not_the_month(self):
        def boom(_entrypoint, _camp_seq, _use_dt):
            raise RuntimeError("upstream 500")

        payload = helper.collect_results(
            provider_ids=("thankq-jaraseom",),
            dates=("20260905",),
            fetchers={"thankq": boom, "thankq_view": thankq_view_fetcher},
        )
        self.assertEqual(payload["fetch_failures"], 1)
        self.assertEqual(payload["failures"][0]["scope"], "20260905")

    def test_mixed_transports_share_one_payload(self):
        payload = helper.collect_results(
            provider_ids=("gtdc-yeongok", "thankq-jaraseom"),
            dates=("20260830",),
            fetchers=ALL_FETCHERS,
        )
        self.assertEqual(
            [site["transport"] for site in payload["results"]], ["dzsmart", "thankq"]
        )

    def test_unknown_transport_is_reported_not_crashed(self):
        bogus = helper.Provider(
            id="bogus",
            name="테스트",
            operator="테스트공단",
            entrypoint="https://example.invalid",
            transport="nope",
            requires_login=False,
            kind="camping",
        )
        with mock.patch.dict(helper.PROVIDERS, {"bogus": bogus}):
            payload = helper.collect_results(
                provider_ids=("bogus",),
                dates=("20260830",),
                fetchers=ALL_FETCHERS,
            )
        self.assertEqual(payload["fetch_failures"], 1)
        self.assertIn("no adapter for transport", payload["failures"][0]["error"])
        self.assertEqual(payload["results"], [])


DONGHAE_VALUE = (
    "전통한옥:6|^|캐빈하우스:예약완료|^|든바다:예약완료|^|난바다:1"
    "|^|허허바다:예약완료|^|자동차캠핑장:24|^|글램핑(4인):예약완료"
)


def donghae_fetcher(_entrypoint, _code, dates, *, user, password):
    assert user and password
    return {use_dt: {"value": DONGHAE_VALUE, "status": "open"} for use_dt in dates}


def donghae_not_open_fetcher(_entrypoint, _code, dates, *, user, password):
    assert user and password
    return {use_dt: {"value": DONGHAE_VALUE, "status": "not_open"} for use_dt in dates}


class ThankqBookingWindowTest(unittest.TestCase):
    def test_window_is_read_off_the_reservation_page(self):
        first, last = helper.parse_thankq_window(JARASEOM_VIEW_HTML)
        self.assertEqual(first, "20260831")
        self.assertEqual(last, "20261001")

    def test_missing_markers_yield_no_window(self):
        self.assertEqual(helper.parse_thankq_window("<html></html>"), (None, None))

    def test_date_past_the_window_is_not_open_not_vacancy(self):
        # The site-list fragment answers with full capacity for 20261002, which is
        # past res_able_max_dt. Counting it as vacancy is the bug this guards.
        payload = helper.collect_results(
            provider_ids=("thankq-jaraseom",),
            dates=("20261002",),
            fetchers=THANKQ_FETCHERS,
        )
        day = payload["results"][0]["dates"][0]
        self.assertEqual(day["booking_status"], "not_open")
        self.assertIn("2026-10-01", day["status_note"])
        self.assertTrue(all(zone["available"] is False for zone in day["zones"]))
        self.assertEqual(payload["filter_hits"], 0)

    def test_date_inside_the_window_stays_open(self):
        payload = helper.collect_results(
            provider_ids=("thankq-jaraseom",),
            dates=("20260905",),
            fetchers=THANKQ_FETCHERS,
        )
        day = payload["results"][0]["dates"][0]
        self.assertEqual(day["booking_status"], "open")
        self.assertIsNone(day["status_note"])
        self.assertGreater(payload["filter_hits"], 0)

    def test_window_fetch_failure_is_reported(self):
        def boom(_entrypoint, _camp_seq):
            raise RuntimeError("view.hbb 503")

        payload = helper.collect_results(
            provider_ids=("thankq-jaraseom",),
            dates=("20260905",),
            fetchers={"thankq": thankq_fetcher, "thankq_view": boom},
        )
        self.assertEqual(payload["fetch_failures"], 1)
        self.assertEqual(payload["failures"][0]["scope"], "booking-window")


class ParseDonghaeValueTest(unittest.TestCase):
    def setUp(self):
        self.zones = helper.parse_donghae_value(DONGHAE_VALUE)
        self.by_name = {zone["zone"]: zone for zone in self.zones}

    def test_every_segment_becomes_a_zone(self):
        self.assertEqual(len(self.zones), 7)

    def test_numeric_state_is_the_remaining_count(self):
        self.assertEqual(self.by_name["전통한옥"]["remaining"], 6)
        self.assertTrue(self.by_name["자동차캠핑장"]["available"])

    def test_sold_out_state_reads_as_unavailable(self):
        self.assertIsNone(self.by_name["캐빈하우스"]["remaining"])
        self.assertFalse(self.by_name["캐빈하우스"]["available"])

    def test_zone_name_with_parentheses_survives_the_split(self):
        self.assertIn("글램핑(4인)", self.by_name)

    def test_empty_or_malformed_payload_yields_no_zones(self):
        self.assertEqual(helper.parse_donghae_value(""), [])
        self.assertEqual(helper.parse_donghae_value("쓰레기"), [])


class DonghaeCollectTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(
            os.environ,
            {"KSKILL_DONGHAE_ID": "tester", "KSKILL_DONGHAE_PASSWORD": "secret"},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_login_provider_returns_zones(self):
        payload = helper.collect_results(
            provider_ids=("donghae-mangsang",),
            dates=("20260830",),
            fetchers={"donghae": donghae_fetcher},
        )
        site = payload["results"][0]
        self.assertEqual(site["operator"], "동해시시설관리공단")
        self.assertEqual(
            [zone["zone"] for zone in site["dates"][0]["zones"]],
            ["전통한옥", "난바다", "자동차캠핑장"],
        )

    def test_missing_credentials_stop_the_run(self):
        with mock.patch.dict(os.environ, {"KSKILL_DONGHAE_ID": "", "KSKILL_DONGHAE_PASSWORD": ""}):
            with self.assertRaises(SystemExit) as ctx:
                helper.collect_results(
                    provider_ids=("donghae-mangsang",),
                    dates=("20260830",),
                    fetchers={"donghae": donghae_fetcher},
                )
        message = str(ctx.exception)
        self.assertIn("KSKILL_DONGHAE_ID", message)
        self.assertIn("never paste credentials", message)

    def test_placeholder_credential_is_rejected(self):
        with mock.patch.dict(os.environ, {"KSKILL_DONGHAE_ID": "replace-me"}):
            with self.assertRaises(SystemExit):
                helper.collect_results(
                    provider_ids=("donghae-mangsang",),
                    dates=("20260830",),
                    fetchers={"donghae": donghae_fetcher},
                )

    def test_nopass_surfaces_as_a_failure_not_a_captcha_attempt(self):
        def refuse(_entrypoint, _code, _dates, *, user, password):
            raise RuntimeError(
                "donghae refused the page-issued pass key; the site flow changed. "
                "This adapter does not solve the booking CAPTCHA."
            )

        payload = helper.collect_results(
            provider_ids=("donghae-mangsang",),
            dates=("20260830",),
            fetchers={"donghae": refuse},
        )
        self.assertEqual(payload["fetch_failures"], 1)
        self.assertIn("does not solve the booking CAPTCHA", payload["failures"][0]["error"])
        self.assertEqual(payload["results"], [])

    def test_unopened_date_is_reported_but_never_as_bookable(self):
        payload = helper.collect_results(
            provider_ids=("donghae-mangsang",),
            dates=("20261002",),
            fetchers={"donghae": donghae_not_open_fetcher},
        )
        day = payload["results"][0]["dates"][0]
        self.assertEqual(day["booking_status"], "not_open")
        self.assertIn("잔여로 읽지 않는다", day["status_note"])
        self.assertIn("연박", day["status_note"])
        self.assertTrue(day["zones"], "the day must still be shown, not silently dropped")
        self.assertTrue(all(not z["available"] for z in day["zones"]))
        self.assertEqual(payload["filter_hits"], 0)

    def test_unopened_day_survives_the_available_only_default(self):
        payload = helper.collect_results(
            provider_ids=("donghae-mangsang",),
            dates=("20261002",),
            include_full=False,
            fetchers={"donghae": donghae_not_open_fetcher},
        )
        self.assertTrue(payload["results"], "an unopened day must not vanish by default")

    def test_text_output_warns_the_unopened_number_is_not_vacancy(self):
        payload = helper.collect_results(
            provider_ids=("donghae-mangsang",),
            dates=("20261002",),
            fetchers={"donghae": donghae_not_open_fetcher},
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            helper.print_text(payload)
        self.assertIn("잔여로 읽지 않는다", buffer.getvalue())

    def test_open_day_still_counts_as_vacancy(self):
        payload = helper.collect_results(
            provider_ids=("donghae-mangsang",),
            dates=("20260830",),
            fetchers={"donghae": donghae_fetcher},
        )
        self.assertEqual(payload["results"][0]["dates"][0]["booking_status"], "open")
        self.assertEqual(payload["filter_hits"], 3)

    def test_all_four_donghae_sites_have_distinct_codes(self):
        codes = {
            pid: helper.PROVIDERS[pid].trrsrt_code
            for pid in helper.PROVIDERS
            if helper.PROVIDERS[pid].transport == "donghae"
        }
        self.assertEqual(len(codes), 4)
        self.assertEqual(len(set(codes.values())), 4)


class ParseMaketicketHtmlTest(unittest.TestCase):
    def setUp(self):
        self.days = helper.parse_maketicket_html(MAKETICKET_HTML)

    def test_date_comes_from_the_slot_not_from_position(self):
        self.assertEqual(sorted(self.days), ["20260901", "20260905"])

    def test_counts_and_names_are_parsed(self):
        zones = {z["zone"]: z for z in self.days["20260901"]}
        self.assertEqual(zones["컨테이너하우스(A동)"]["remaining"], 2)
        self.assertEqual(zones["일반야영장(D동)"]["remaining"], 8)

    def test_zero_is_not_available(self):
        zones = {z["zone"]: z for z in self.days["20260901"]}
        self.assertEqual(zones["오토캠핑장(C동)"]["remaining"], 0)
        self.assertFalse(zones["오토캠핑장(C동)"]["available"])

    def test_zone_name_keeps_its_parentheses(self):
        self.assertIn("카라반(B동)", {z["zone"] for z in self.days["20260901"]})

    def test_day_cell_without_slots_is_absent(self):
        self.assertNotIn("20260906", self.days)

    def test_unparsable_page_yields_no_days(self):
        self.assertEqual(helper.parse_maketicket_html("<html>점검중</html>"), {})


class MaketicketCollectTest(unittest.TestCase):
    def collect(self, dates):
        return helper.collect_maketicket(
            helper.PROVIDERS["maketicket-jangho"], dates, maketicket_fetcher
        )

    def test_days_present_in_the_calendar(self):
        days, failures = self.collect(("20260901",))
        self.assertEqual(failures, [])
        self.assertEqual(days["20260901"]["booking_status"], "open")
        self.assertEqual(len(days["20260901"]["zones"]), 4)

    def test_missing_date_is_an_explicit_failure_not_silence(self):
        days, failures = self.collect(("20260906",))
        self.assertEqual(days, {})
        self.assertIn("예약 달력에 없다", failures[0]["error"])

    def test_fetch_error_is_not_double_reported_per_date(self):
        def boom(_entrypoint, _gd_seq, _month):
            raise RuntimeError("upstream down")

        days, failures = helper.collect_maketicket(
            helper.PROVIDERS["maketicket-jangho"], ("20260901", "20260905"), boom
        )
        self.assertEqual(days, {})
        self.assertEqual(len(failures), 1, "one month failure, not one per date")

    def test_providers_pin_a_gd_seq_and_need_no_login(self):
        for pid in ("maketicket-jangho", "maketicket-hyangnam"):
            provider = helper.PROVIDERS[pid]
            self.assertTrue(provider.gd_seq)
            self.assertFalse(provider.requires_login)


class ParseGmucHtmlTest(unittest.TestCase):
    def setUp(self):
        self.days = helper.parse_gmuc_html(
            GMUC_HTML, first_month="202608", second_month="202609"
        )

    def test_day_rollover_switches_to_the_second_month(self):
        self.assertEqual(
            sorted(self.days), ["20260829", "20260830", "20260831", "20260901", "20260906"]
        )

    def test_area_done_reads_as_sold_out(self):
        zones = {z["zone"]: z for z in self.days["20260829"]}
        self.assertIsNone(zones["A구역"]["remaining"])
        self.assertFalse(zones["A구역"]["available"])

    def test_area_keeps_the_remaining_count(self):
        zones = {z["zone"]: z for z in self.days["20260830"]}
        self.assertEqual(zones["A구역"]["remaining"], 11)
        self.assertTrue(zones["A구역"]["available"])

    def test_mixed_cell_keeps_both_states(self):
        zones = {z["zone"]: z for z in self.days["20260831"]}
        self.assertEqual(zones["A구역"]["remaining"], 21)
        self.assertIsNone(zones["B구역"]["remaining"])

    def test_zero_remaining_is_not_available(self):
        zones = {z["zone"]: z for z in self.days["20260901"]}
        self.assertEqual(zones["A구역"]["remaining"], 0)
        self.assertFalse(zones["A구역"]["available"])
        self.assertTrue(zones["B구역"]["available"])

    def test_empty_cells_are_skipped(self):
        self.assertNotIn("20260800", self.days)

    def test_unparsable_page_yields_no_days(self):
        self.assertEqual(
            helper.parse_gmuc_html("<html>점검중</html>", first_month="202608", second_month="202609"),
            {},
        )


class GmucCollectTest(unittest.TestCase):
    """Pin `today` so these stay green after 2026-09; the page window moves."""

    ANCHOR = date(2026, 8, 29)

    def collect(self, dates):
        return helper.collect_gmuc(
            helper.PROVIDERS["gmuc-dodeoksan"], dates, gmuc_fetcher, today=self.ANCHOR
        )

    def test_days_inside_the_window_are_returned(self):
        days, failures = self.collect(("20260830", "20260906"))
        self.assertEqual(sorted(days), ["20260830", "20260906"])
        self.assertEqual(failures, [])
        self.assertEqual(days["20260830"]["booking_status"], "open")
        self.assertEqual(len(days["20260830"]["zones"]), 2)

    def test_date_outside_the_two_month_window_is_an_explicit_failure(self):
        days, failures = self.collect(("20261002",))
        self.assertEqual(days, {})
        self.assertEqual(len(failures), 1)
        self.assertIn("당월+익월", failures[0]["error"])
        self.assertEqual(failures[0]["scope"], "20261002")

    def test_page_error_is_reported_not_swallowed(self):
        def boom(_entrypoint):
            raise RuntimeError("upstream down")

        days, failures = helper.collect_gmuc(
            helper.PROVIDERS["gmuc-dodeoksan"], ("20260830",), boom, today=self.ANCHOR
        )
        self.assertEqual(days, {})
        self.assertIn("upstream down", failures[0]["error"])

    def test_year_rollover_is_handled(self):
        html = GMUC_HTML.replace('class="date">29<', 'class="date">31<')
        days = helper.parse_gmuc_html(html, first_month="202612", second_month="202701")
        self.assertTrue(any(k.startswith("2027") for k in days), sorted(days))

    def test_needs_no_credentials(self):
        self.assertFalse(helper.PROVIDERS["gmuc-dodeoksan"].requires_login)
        self.assertIsNone(helper.PROVIDERS["gmuc-dodeoksan"].credential_env)


class ClassifyDonghaeLabelTest(unittest.TestCase):
    def test_known_labels(self):
        self.assertEqual(helper.classify_donghae_label("예약현황보기"), "open")
        self.assertEqual(helper.classify_donghae_label("예약마감"), "full")
        self.assertEqual(helper.classify_donghae_label("예약종료"), "closed")

    def test_empty_label_means_the_window_has_not_opened(self):
        self.assertEqual(helper.classify_donghae_label(""), "not_open")
        self.assertEqual(helper.classify_donghae_label("   "), "not_open")

    def test_unknown_label_is_not_assumed_open(self):
        self.assertEqual(helper.classify_donghae_label("점검중"), "unknown")


class RegistryScopeTest(unittest.TestCase):
    def test_every_lookup_provider_names_a_public_operator(self):
        for pid in helper.LOOKUP_PROVIDER_IDS:
            provider = helper.PROVIDERS[pid]
            self.assertTrue(
                provider.operator.endswith(("공사", "공단", "시", "군", "구", "청")),
                f"{pid} operator '{provider.operator}' must be a public body",
            )

    def test_thankq_provider_pins_a_camp_seq(self):
        self.assertEqual(helper.PROVIDERS["thankq-jaraseom"].camp_seq, "1")

    def test_dzsmart_providers_do_not_need_a_camp_seq(self):
        self.assertIsNone(helper.PROVIDERS["gtdc-yeongok"].camp_seq)

    def test_login_providers_declare_their_credential_env(self):
        for pid in helper.LOOKUP_PROVIDER_IDS:
            provider = helper.PROVIDERS[pid]
            if provider.requires_login:
                self.assertIsNotNone(
                    provider.credential_env, f"{pid} must declare credential_env"
                )

    def test_no_credential_value_is_hardcoded(self):
        source = HELPER_PATH.read_text(encoding="utf-8")
        for pid in helper.LOOKUP_PROVIDER_IDS:
            provider = helper.PROVIDERS[pid]
            if provider.credential_env:
                for key in provider.credential_env:
                    self.assertNotIn(f'{key} = "', source)


class OutputTest(unittest.TestCase):
    def setUp(self):
        self.payload = helper.collect_results(
            provider_ids=("gtdc-yeongok",),
            dates=("20260830",),
            fetchers=DZSMART_FETCHERS,
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
            dates=("20260829",),
            zone_filter="없는존이름",
            fetchers=DZSMART_FETCHERS,
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
