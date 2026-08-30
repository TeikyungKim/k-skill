import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
HELPER_PATH = SCRIPT_DIR.parent / "scripts" / "run_foresttrip_vacancy.py"
FIXTURES_DIR = SCRIPT_DIR / "fixtures"


def load_helper():
    spec = importlib.util.spec_from_file_location("run_foresttrip_vacancy", HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper from {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_foresttrip_vacancy"] = module
    spec.loader.exec_module(module)
    return module


helper = load_helper()


def load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


GEOJE_ROWS = load_fixture("geoje_window.json")
GUJAEBONG_ROWS = load_fixture("gujaebong_window.json")

GEOJE_FOREST_ID = "ID02030059"
GEOJE_FOREST_NAME = "[공립](거제시)거제자연휴양림"
GUJAEBONG_FOREST_ID = "ID02030072"
GUJAEBONG_FOREST_NAME = "[공립](하동군)구재봉자연휴양림"

FIXED_NOW = datetime(2026, 5, 12, 0, 0, 0)


def make_session(forests):
    return helper.Session(
        cookies={},
        csrf="dummy-csrf",
        user_agent="test-ua",
        forests=forests,
        expires_at=FIXED_NOW.timestamp() + 3600,
    )


def stub_fetch(rows):
    def _stub(*, forest_id, category, **_):
        matched = [r for r in rows if r.get("insttId") == forest_id]
        return forest_id, category, matched, None
    return _stub


def stub_goods(rows):
    """Offer every goods id the fixture rows carry, so the gate stays inert."""

    def _stub(*, forest_id, category, **_):
        offered = {
            str(r.get("goodsId") or "")
            for r in rows
            if r.get("insttId") == forest_id
        }
        return forest_id, category, offered, None

    return _stub


def stub_window(last_day=None):
    def _stub(*, forest_id, **_):
        return forest_id, last_day, None

    return _stub


def run_collect(
    session,
    targets,
    rows,
    *,
    dates=None,
    week_range=None,
    categories=("01",),
    nights=1,
    goods_stub=None,
    window_stub=None,
):
    with mock.patch.object(helper, "fetch_one", side_effect=stub_fetch(rows)):
        with mock.patch.object(
            helper, "fetch_offered_goods", side_effect=goods_stub or stub_goods(rows)
        ):
            with mock.patch.object(
                helper, "fetch_booking_window", side_effect=window_stub or stub_window()
            ):
                with mock.patch.object(helper, "datetime", wraps=datetime) as mock_dt:
                    mock_dt.now.return_value = FIXED_NOW
                    return helper.collect_results(
                        session=session,
                        targets=targets,
                        categories=categories,
                        dates=tuple(dates) if dates else None,
                        week_range=week_range,
                        concurrency=1,
                        nights=nights,
                    )


class IsReserveRoomTest(unittest.TestCase):
    def test_parens_with_suffix(self):
        self.assertTrue(helper.is_reserve_room({"goodsNm": "201호 배꽃방(예비용)"}))

    def test_parens_prefix(self):
        self.assertTrue(helper.is_reserve_room({"goodsNm": "(예비) 201호"}))

    def test_predicate_with_simple_suffix(self):
        self.assertTrue(helper.is_reserve_room({"goodsNm": "편백나무2호(예비용)"}))

    def test_normal_room_passes(self):
        self.assertFalse(helper.is_reserve_room({"goodsNm": "동백1"}))

    def test_empty_name(self):
        self.assertFalse(helper.is_reserve_room({"goodsNm": ""}))

    def test_missing_name_key(self):
        self.assertFalse(helper.is_reserve_room({}))


class IsAvailableTest(unittest.TestCase):
    def test_y_and_zero_count(self):
        self.assertTrue(helper.is_available({"rsrvtAvail": "Y", "rsrvtCnt": 0}))

    def test_y_and_string_zero_count(self):
        self.assertTrue(helper.is_available({"rsrvtAvail": "Y", "rsrvtCnt": "0"}))

    def test_y_but_already_booked(self):
        self.assertFalse(helper.is_available({"rsrvtAvail": "Y", "rsrvtCnt": 1}))

    def test_y_but_string_booked_count(self):
        self.assertFalse(helper.is_available({"rsrvtAvail": "Y", "rsrvtCnt": "1"}))

    def test_not_available(self):
        self.assertFalse(helper.is_available({"rsrvtAvail": "N", "rsrvtCnt": 0}))


class CollectResultsFilterTest(unittest.TestCase):
    def setUp(self):
        self.session = make_session({GEOJE_FOREST_ID: GEOJE_FOREST_NAME})
        self.targets = {GEOJE_FOREST_ID: GEOJE_FOREST_NAME}

    def test_geoje_5_13_three_unique_rooms_after_dedup_and_reserve_filter(self):
        payload = run_collect(self.session, self.targets, GEOJE_ROWS, dates=["20260513"])
        self.assertEqual(payload["filter_hits"], 3)
        names = {
            room["name"]
            for forest in payload["results"]
            for date in forest["dates"]
            for room in date["rooms"]
        }
        self.assertEqual(names, {"동백1", "해송2", "고로쇠1"})

    def test_geoje_5_16_returns_zero_when_only_reserved_or_booked(self):
        payload = run_collect(self.session, self.targets, GEOJE_ROWS, dates=["20260516"])
        self.assertEqual(payload["filter_hits"], 0)
        self.assertEqual(payload["results"], [])

    def test_geoje_5_17_two_rooms(self):
        payload = run_collect(self.session, self.targets, GEOJE_ROWS, dates=["20260517"])
        self.assertEqual(payload["filter_hits"], 2)
        names = {
            room["name"]
            for forest in payload["results"]
            for date in forest["dates"]
            for room in date["rooms"]
        }
        self.assertEqual(names, {"중산막2", "동백3"})

    def test_dates_outside_request_filtered_out(self):
        payload = run_collect(self.session, self.targets, GEOJE_ROWS, dates=["20260513"])
        observed_dates = {
            room["use_dt"]
            for forest in payload["results"]
            for date in forest["dates"]
            for room in date["rooms"]
        }
        self.assertEqual(observed_dates, {"20260513"})

    def test_reserve_rooms_excluded_across_all_dates(self):
        payload = run_collect(
            self.session, self.targets, GEOJE_ROWS,
            dates=["20260513", "20260516", "20260517"],
        )
        for forest in payload["results"]:
            for date in forest["dates"]:
                for room in date["rooms"]:
                    self.assertNotIn("예비", room["name"])

    def test_dedup_collapses_duplicate_room_with_different_goods_id(self):
        payload = run_collect(self.session, self.targets, GEOJE_ROWS, dates=["20260513"])
        donbaek_count = sum(
            1
            for forest in payload["results"]
            for date in forest["dates"]
            for room in date["rooms"]
            if room["name"] == "동백1"
        )
        self.assertEqual(donbaek_count, 1)

    def test_dedup_keeps_same_room_name_from_distinct_categories(self):
        rows_by_category = {
            "01": [
                {
                    "insttId": GEOJE_FOREST_ID,
                    "insttNm": GEOJE_FOREST_NAME,
                    "useDt": "20260513",
                    "goodsNm": "같은이름",
                    "goodsClsscNm": "숙박",
                    "rsrvtAvail": "Y",
                    "rsrvtCnt": 0,
                }
            ],
            "02": [
                {
                    "insttId": GEOJE_FOREST_ID,
                    "insttNm": GEOJE_FOREST_NAME,
                    "useDt": "20260513",
                    "goodsNm": "같은이름",
                    "goodsClsscNm": "야영",
                    "rsrvtAvail": "Y",
                    "rsrvtCnt": 0,
                }
            ],
        }

        def fetch_category(*, forest_id, category, **_):
            return forest_id, category, rows_by_category[category], None

        all_rows = [row for rows in rows_by_category.values() for row in rows]
        with mock.patch.object(helper, "fetch_one", side_effect=fetch_category):
            with mock.patch.object(
                helper, "fetch_offered_goods", side_effect=stub_goods(all_rows)
            ):
                with mock.patch.object(
                    helper, "fetch_booking_window", side_effect=stub_window()
                ):
                    with mock.patch.object(helper, "datetime", wraps=datetime) as mock_dt:
                        mock_dt.now.return_value = FIXED_NOW
                        payload = helper.collect_results(
                            session=self.session,
                            targets=self.targets,
                            categories=("01", "02"),
                            dates=("20260513",),
                            week_range=None,
                            concurrency=1,
                        )

        self.assertEqual(payload["filter_hits"], 2)
        observed = [
            (room["name"], room["category"])
            for forest in payload["results"]
            for date in forest["dates"]
            for room in date["rooms"]
        ]
        self.assertEqual(observed, [("같은이름", "숙박"), ("같은이름", "야영")])


class StrictUseDtGateTest(unittest.TestCase):
    """Bug 1 regression: API returns 5-day window even when single-day requested."""

    def test_useDt_before_today_blocked_even_if_available(self):
        past_row = dict(GEOJE_ROWS[0])
        past_row["useDt"] = "20260101"
        rows = [past_row]
        session = make_session({GEOJE_FOREST_ID: GEOJE_FOREST_NAME})
        payload = run_collect(
            session, {GEOJE_FOREST_ID: GEOJE_FOREST_NAME}, rows,
            week_range=1,
        )
        self.assertEqual(payload["filter_hits"], 0)

    def test_useDt_after_last_day_blocked(self):
        far_future = dict(GEOJE_ROWS[0])
        far_future["useDt"] = "20300101"
        rows = [far_future]
        session = make_session({GEOJE_FOREST_ID: GEOJE_FOREST_NAME})
        payload = run_collect(
            session, {GEOJE_FOREST_ID: GEOJE_FOREST_NAME}, rows,
            week_range=1,
        )
        self.assertEqual(payload["filter_hits"], 0)


class PrintTextTest(unittest.TestCase):
    """print_text is the user-facing output path — guard against format regressions."""

    def test_renders_forest_and_rooms(self):
        session = make_session({GEOJE_FOREST_ID: GEOJE_FOREST_NAME})
        payload = run_collect(
            session, {GEOJE_FOREST_ID: GEOJE_FOREST_NAME}, GEOJE_ROWS,
            dates=["20260513"],
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            helper.print_text(payload)
        output = buffer.getvalue()
        self.assertIn(GEOJE_FOREST_NAME, output)
        self.assertIn("20260513", output)
        self.assertIn("slot(s)", output)
        self.assertIn("동백1", output)

    def test_empty_results_message(self):
        session = make_session({GEOJE_FOREST_ID: GEOJE_FOREST_NAME})
        payload = run_collect(
            session, {GEOJE_FOREST_ID: GEOJE_FOREST_NAME}, GEOJE_ROWS,
            dates=["20260516"],
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            helper.print_text(payload)
        self.assertIn("(no available rooms at lookup time)", buffer.getvalue())


class OfficialGateTest(unittest.TestCase):
    """The availability feed is not the same thing as what the site offers."""

    def setUp(self):
        self.session = make_session({GEOJE_FOREST_ID: GEOJE_FOREST_NAME})
        self.targets = {GEOJE_FOREST_ID: GEOJE_FOREST_NAME}

    def collect(self, **kwargs):
        return run_collect(self.session, self.targets, GEOJE_ROWS, dates=["20260513"], **kwargs)

    def test_goods_the_site_does_not_offer_are_dropped(self):
        # 가리산's 야영데크 shows up in the feed with rsrvtAvail=Y / rsrvtCnt=0 while
        # the official screen offers no camping goods at all and renders nothing.
        def only_one(*, forest_id, category, **_):
            return forest_id, category, {"GID-A1"}, None

        payload = self.collect(goods_stub=only_one)
        names = [
            room["name"]
            for forest in payload["results"]
            for day in forest["dates"]
            for room in day["rooms"]
        ]
        self.assertEqual(names, ["동백1"])

    def test_a_forest_offering_nothing_yields_nothing(self):
        def offers_nothing(*, forest_id, category, **_):
            return forest_id, category, set(), None

        payload = self.collect(goods_stub=offers_nothing)
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["filter_hits"], 0)

    def test_goods_gate_failure_reports_and_keeps_rows(self):
        def boom(*, forest_id, category, **_):
            return forest_id, category, None, "http_403"

        payload = self.collect(goods_stub=boom)
        self.assertTrue(payload["results"])
        self.assertEqual(payload["fetch_failures"], 1)
        self.assertIn("goods:http_403", payload["failures"][0]["error"])

    def test_dates_past_the_booking_window_are_dropped(self):
        payload = run_collect(
            self.session,
            self.targets,
            GEOJE_ROWS,
            dates=["20260513", "20260514"],
            window_stub=stub_window("20260513"),
        )
        seen = [day["use_dt"] for forest in payload["results"] for day in forest["dates"]]
        self.assertEqual(seen, ["20260513"])

    def test_window_gate_failure_is_reported(self):
        def boom(*, forest_id, **_):
            return forest_id, None, "http_403"

        payload = self.collect(window_stub=boom)
        self.assertEqual(payload["fetch_failures"], 1)
        self.assertIn("window:http_403", payload["failures"][0]["error"])


class ReservationLastDayTest(unittest.TestCase):
    def test_week_cycle_uses_week_last_day(self):
        policy = {"rsrvtPolcy": {"rsrvtCycleTpeCd": "WEEK", "weekLastDay": "20261006", "monthLastDay": "20260930"}}
        self.assertEqual(helper.reservation_last_day(policy), "20261006")

    def test_month_cycle_uses_month_last_day(self):
        policy = {"rsrvtPolcy": {"rsrvtCycleTpeCd": "MON", "weekLastDay": "20261006", "monthLastDay": "20260930"}}
        self.assertEqual(helper.reservation_last_day(policy), "20260930")

    def test_general_transfer_date_extends_the_window(self):
        policy = {
            "rsrvtPolcy": {"rsrvtCycleTpeCd": "MON", "monthLastDay": "20260930"},
            "gnrlRsrvtTrnseDtm": "20261010",
        }
        self.assertEqual(helper.reservation_last_day(policy), "20261010")

    def test_missing_policy_means_no_window(self):
        self.assertIsNone(helper.reservation_last_day({}))


class ConsecutiveStayTest(unittest.TestCase):
    """Per-night vacancy is not a multi-night booking."""

    def rows(self, **overrides):
        base = {"forest_id": "F1", "source_category": "02", "goods_id": "G1", "name": "데크1", "max_stay_nights": "3"}
        return [{**base, "use_dt": use_dt, **overrides} for use_dt in ("20261002", "20261003", "20261004")]

    def test_three_free_nights_survive(self):
        kept = helper.filter_consecutive_stays(self.rows(), 3)
        self.assertEqual([row["use_dt"] for row in kept], ["20261002"])
        self.assertEqual(kept[0]["stay_nights"], 3)

    def test_a_gap_in_the_middle_breaks_the_run(self):
        rows = [row for row in self.rows() if row["use_dt"] != "20261003"]
        self.assertEqual(helper.filter_consecutive_stays(rows, 3), [])

    def test_max_stay_nights_caps_the_request(self):
        # 금원산 answers "휴양림의 최대 숙박일수를 초과하여 신청하셨습니다" for 3 nights
        # even though all three nights look free one at a time.
        rows = self.rows(max_stay_nights="2")
        self.assertEqual(helper.filter_consecutive_stays(rows, 3), [])
        self.assertEqual(len(helper.filter_consecutive_stays(rows, 2)), 2)

    def test_a_different_room_each_night_does_not_count(self):
        rows = [
            {"forest_id": "F1", "source_category": "02", "goods_id": f"G{i}", "name": f"데크{i}", "max_stay_nights": "3", "use_dt": use_dt}
            for i, use_dt in enumerate(("20261002", "20261003", "20261004"))
        ]
        self.assertEqual(helper.filter_consecutive_stays(rows, 3), [])

    def test_single_night_is_a_passthrough(self):
        rows = self.rows()
        self.assertEqual(helper.filter_consecutive_stays(rows, 1), rows)


class MainOutputTest(unittest.TestCase):
    def run_main(self, argv, payload):
        session = make_session({GEOJE_FOREST_ID: GEOJE_FOREST_NAME})
        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", ["run_foresttrip_vacancy.py", *argv]):
            with mock.patch.object(helper, "get_session", return_value=session):
                with mock.patch.object(helper, "resolve_targets", return_value={GEOJE_FOREST_ID: GEOJE_FOREST_NAME}):
                    with mock.patch.object(helper, "collect_results", return_value=payload):
                        with redirect_stdout(buffer):
                            exit_code = helper.main()
        return exit_code, buffer.getvalue()

    def test_main_text_output_returns_success_when_fetches_succeed(self):
        payload = run_collect(
            make_session({GEOJE_FOREST_ID: GEOJE_FOREST_NAME}),
            {GEOJE_FOREST_ID: GEOJE_FOREST_NAME},
            GEOJE_ROWS,
            dates=["20260513"],
        )
        exit_code, output = self.run_main(["--forest-id", GEOJE_FOREST_ID, "--text"], payload)

        self.assertEqual(exit_code, 0)
        self.assertIn("ForestTrip Vacancy Lookup", output)
        self.assertIn("filter_hits: 3", output)
        self.assertIn("동백1", output)

    def test_main_json_output_reports_failure_and_returns_nonzero(self):
        payload = {
            "forests_scanned": 1,
            "filter_hits": 0,
            "fetch_failures": 1,
            "failures": [{"forest_id": GEOJE_FOREST_ID, "category": "01", "error": "http_401"}],
            "concurrency": 1,
            "date_range": {"from": "20260512", "to": "20260513"},
            "results": [],
        }
        exit_code, output = self.run_main(["--forest-id", GEOJE_FOREST_ID, "--json"], payload)

        self.assertEqual(exit_code, 1)
        rendered = json.loads(output)
        self.assertEqual(rendered["fetch_failures"], 1)
        self.assertEqual(rendered["failures"][0]["error"], "http_401")


class GroundTruthTest(unittest.TestCase):
    """Anchored to user-verified counts from foresttrip.go.kr on 2026-05-12.
    Fixtures are simplified; tests assert the per-(forest, date) shape matches."""

    def test_gujaebong_5_16_one_room_named_쑥부쟁이방(self):
        session = make_session({GUJAEBONG_FOREST_ID: GUJAEBONG_FOREST_NAME})
        payload = run_collect(
            session, {GUJAEBONG_FOREST_ID: GUJAEBONG_FOREST_NAME}, GUJAEBONG_ROWS,
            dates=["20260516"],
        )
        self.assertEqual(payload["filter_hits"], 1)
        names = [
            room["name"]
            for forest in payload["results"]
            for date in forest["dates"]
            for room in date["rooms"]
        ]
        self.assertEqual(names, ["206호 쑥부쟁이방"])


if __name__ == "__main__":
    unittest.main()
