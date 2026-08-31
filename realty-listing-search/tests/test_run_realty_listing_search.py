"""Offline tests for the realty-listing-search adapter registry.

No network. Fixtures are trimmed captures of the real portal responses taken
during discovery on 2026-08-30.
"""
from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path

import run_realty_listing_search as mod

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_opts(**overrides) -> argparse.Namespace:
    base = dict(
        region="신흥동",
        prefer="성남",
        trade_types=["전세"],
        property_types=["원룸", "빌라"],
        deposit_max=None,
        deposit_min=None,
        rent_max=None,
        area_min_m2=None,
        providers=["zigbang", "dabang"],
        limit=30,
        radius_km=1.5,
        pages=2,
        geohash_precision=5,
        naver_zoom=15,
        naver_browser=False,
        node_bin="node",
        naver_timeout=120,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class GeohashTest(unittest.TestCase):
    def test_known_points(self):
        # 성남 신흥동 / 송파 문정동 -- both fall in the wydm* cell block.
        self.assertEqual(mod.geohash_encode(37.4432, 127.1470, 5), "wydmj")
        self.assertEqual(mod.geohash_encode(37.4855, 127.1223, 5), "wydmk")

    def test_precision_is_a_prefix_chain(self):
        six = mod.geohash_encode(37.4432, 127.1470, 6)
        self.assertTrue(six.startswith("wydmj"))
        self.assertEqual(len(six), 6)


class PriceParsingTest(unittest.TestCase):
    def test_plain_deposit(self):
        self.assertEqual(mod.parse_dabang_price("6500"), (6500.0, None))

    def test_deposit_and_rent(self):
        self.assertEqual(mod.parse_dabang_price("1000/50"), (1000.0, 50.0))

    def test_eok_notation(self):
        self.assertEqual(mod.parse_dabang_price("3억 2,000"), (32000.0, None))
        self.assertEqual(mod.parse_dabang_price("2억"), (20000.0, None))

    def test_eok_with_rent(self):
        # Real labels seen on 문정동 월세: "1억/30", "1억5000/3", "1억6800/45".
        self.assertEqual(mod.parse_dabang_price("1억/30"), (10000.0, 30.0))
        self.assertEqual(mod.parse_dabang_price("1억5000/3"), (15000.0, 3.0))
        self.assertEqual(mod.parse_dabang_price("1억6800/45"), (16800.0, 45.0))

    def test_deposit_free_listing(self):
        # "보증금없음" listings really are posted as 1만원.
        self.assertEqual(mod.parse_dabang_price("1/210"), (1.0, 210.0))

    def test_empty(self):
        self.assertEqual(mod.parse_dabang_price(None), (None, None))
        self.assertEqual(mod.parse_dabang_price(""), (None, None))


class FloorFormatTest(unittest.TestCase):
    def test_numeric_floors(self):
        self.assertEqual(mod.format_floor("4", "5"), "4층/5층")
        self.assertEqual(mod.format_floor("4", None), "4층")

    def test_label_floors_are_not_suffixed(self):
        self.assertEqual(mod.format_floor("반지하", "2"), "반지하/2층")
        self.assertEqual(mod.format_floor("옥탑", None), "옥탑")

    def test_missing(self):
        self.assertIsNone(mod.format_floor(None))
        self.assertIsNone(mod.format_floor(""))


class NormaliseZigbangTest(unittest.TestCase):
    def setUp(self):
        self.raw = load("zigbang_item_list.json")["items"][0]

    def test_core_fields(self):
        item = mod.normalise_zigbang(self.raw)
        self.assertEqual(item["provider"], "zigbang")
        self.assertEqual(item["id"], "49648622")
        self.assertEqual(item["sales_type"], "전세")
        self.assertEqual(item["deposit_manwon"], 25000)
        self.assertIsNone(item["price_manwon"])
        self.assertEqual(item["area_m2"], 52.8)
        self.assertEqual(item["area_pyeong"], 15.97)
        self.assertEqual(item["floor"], "4층/4층")
        self.assertEqual(item["address"], "경기도 성남시 수정구 태평동")

    def test_carries_approximate_location(self):
        item = mod.normalise_zigbang(self.raw)
        self.assertAlmostEqual(item["lat"], 37.44372, places=3)
        self.assertAlmostEqual(item["lng"], 127.137432, places=3)

    def test_url_uses_service_segment(self):
        item = mod.normalise_zigbang(self.raw)
        self.assertEqual(item["url"], "https://www.zigbang.com/home/villa/items/49648622")

    def test_sale_moves_deposit_into_price(self):
        raw = dict(self.raw, sales_type="매매", deposit=48000)
        item = mod.normalise_zigbang(raw)
        self.assertEqual(item["price_manwon"], 48000)
        self.assertIsNone(item["deposit_manwon"])


class NormaliseDabangTest(unittest.TestCase):
    def setUp(self):
        self.raw = load("dabang_room_list.json")["result"]["roomList"][0]

    def test_core_fields(self):
        item = mod.normalise_dabang(self.raw)
        self.assertEqual(item["provider"], "dabang")
        self.assertEqual(item["sales_type"], "전세")
        self.assertEqual(item["deposit_manwon"], 6500)
        self.assertEqual(item["area_m2"], 31.03)
        self.assertEqual(item["floor"], "2층")
        self.assertEqual(item["address"], "태평동")

    def test_url(self):
        item = mod.normalise_dabang(self.raw)
        self.assertTrue(item["url"].startswith("https://www.dabangapp.com/room/"))

    def test_carries_approximate_location(self):
        item = mod.normalise_dabang(self.raw)
        self.assertAlmostEqual(item["lat"], 37.448528, places=3)
        self.assertAlmostEqual(item["lng"], 127.133016, places=3)


class DabangFiltersTest(unittest.TestCase):
    """A partial filters object makes the portal answer 400."""

    COMMON = {
        "sellingTypeList",
        "depositRange",
        "priceRange",
        "isIncludeMaintenance",
        "pyeongRange",
        "useApprovalDateRange",
        "isShortLease",
    }

    def test_one_two_required_keys(self):
        keys = set(mod.dabang_filters("one-two", ["전세"]))
        self.assertTrue(self.COMMON <= keys)
        self.assertTrue(
            {"roomFloorList", "roomTypeList", "canParking", "hasElevator", "hasPano", "isDivision", "isDuplex"} <= keys
        )

    def test_apt_required_keys(self):
        keys = set(mod.dabang_filters("apt", ["매매"]))
        self.assertTrue({"tradeRange", "roomCountList", "householdNumRange", "parkingNumRange", "hasTakeTenant"} <= keys)

    def test_officetel_required_keys(self):
        keys = set(mod.dabang_filters("officetel", ["월세"]))
        self.assertTrue({"tradeRange", "roomCountList", "parkingNumRange", "canParking"} <= keys)

    def test_trade_type_mapping(self):
        self.assertEqual(mod.dabang_filters("one-two", ["전세"])["sellingTypeList"], ["LEASE"])
        self.assertEqual(
            mod.dabang_filters("one-two", ["월세", "매매"])["sellingTypeList"],
            ["MONTHLY_RENT", "SELL"],
        )

    def test_bbox_is_centred(self):
        bbox = mod.dabang_bbox(37.44, 127.14, 1.5)
        self.assertLess(bbox["sw"]["lat"], 37.44)
        self.assertGreater(bbox["ne"]["lat"], 37.44)
        self.assertLess(bbox["sw"]["lng"], 127.14)
        self.assertGreater(bbox["ne"]["lng"], 127.14)


class FilterTest(unittest.TestCase):
    ITEMS = [
        {"deposit_manwon": 5000, "rent_manwon": None, "area_m2": 20.0},
        {"deposit_manwon": 20000, "rent_manwon": None, "area_m2": 60.0},
        {"deposit_manwon": 1000, "rent_manwon": 70, "area_m2": 15.0},
        {"deposit_manwon": None, "rent_manwon": None, "area_m2": None},
    ]

    def test_deposit_max(self):
        got = mod.apply_filters(self.ITEMS, make_opts(deposit_max=10000))
        self.assertEqual([i["deposit_manwon"] for i in got], [5000, 1000, None])

    def test_rent_max(self):
        got = mod.apply_filters(self.ITEMS, make_opts(rent_max=50))
        self.assertNotIn(70, [i["rent_manwon"] for i in got])

    def test_area_min(self):
        got = mod.apply_filters(self.ITEMS, make_opts(area_min_m2=40.0))
        self.assertEqual([i["area_m2"] for i in got], [60.0, None])

    def test_sort_puts_unknown_deposit_last(self):
        items = list(self.ITEMS)
        items.sort(key=mod.sort_key)
        self.assertIsNone(items[-1]["deposit_manwon"])
        self.assertEqual(items[0]["deposit_manwon"], 1000)


class NaverLinkTest(unittest.TestCase):
    REGION = mod.Region(
        query="신흥동",
        name="신흥동",
        full_name="경기도 성남시 수정구 신흥동",
        lat=37.4431,
        lng=127.1411,
        source="zigbang",
    )

    def test_oneroom_and_villa_collapse_to_one_link(self):
        links = mod.naver_links(self.REGION, make_opts(property_types=["원룸", "빌라"]))
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["property_type"], "원룸/빌라")

    def test_apartment_uses_complexes_page(self):
        links = mod.naver_links(self.REGION, make_opts(property_types=["아파트"]))
        self.assertIn("new.land.naver.com/complexes", links[0]["url"])
        self.assertIn("APT", links[0]["url"])

    def test_trade_code(self):
        links = mod.naver_links(self.REGION, make_opts(property_types=["아파트"], trade_types=["매매"]))
        self.assertIn("tradTp=A1", links[0]["url"])

    def test_naver_reads_through_a_real_browser(self):
        p = mod.PROVIDERS["naver"]
        self.assertTrue(p.scrapes)
        self.assertIn("browser-cdp", p.transport)
        self.assertIn("link-only", p.transport)  # fallback stays documented


class NaverBrowserAdapterTest(unittest.TestCase):
    """The browser path must degrade to links, never to a crash."""

    def test_helper_script_ships_with_the_skill(self):
        self.assertTrue(mod.NAVER_CDP_SCRIPT.name.endswith("naver_cdp.js"))

    def test_missing_helper_reports_instead_of_raising(self):
        original = mod.NAVER_CDP_SCRIPT
        mod.NAVER_CDP_SCRIPT = original.with_name("does-not-exist.js")
        try:
            items, errors, sources = mod.naver_browser_search(NaverLinkTest.REGION, make_opts())
        finally:
            mod.NAVER_CDP_SCRIPT = original
        self.assertEqual(items, [])
        self.assertTrue(errors and "helper missing" in errors[0])

    def test_helper_failure_is_reported_not_swallowed(self):
        calls = []

        class FakeProc:
            stdout = json.dumps({"status": "unavailable", "reason": "browser_not_reachable"})
            stderr = ""

        original = subprocess_run = mod.subprocess.run
        mod.subprocess.run = lambda cmd, **kw: (calls.append(cmd), FakeProc())[1]
        try:
            items, errors, _ = mod.naver_browser_search(
                NaverLinkTest.REGION, make_opts(property_types=["오피스텔"])
            )
        finally:
            mod.subprocess.run = original
        self.assertEqual(items, [])
        self.assertTrue(any("browser_not_reachable" in e for e in errors))
        self.assertEqual(len(calls), 1)

    def test_rows_dedupe_across_property_types(self):
        """원룸/빌라 share one Naver type code, so the same rows come back twice."""
        row = {"id": "999", "provider": "naver", "deposit_manwon": 20000}

        class FakeProc:
            stdout = json.dumps({"status": "ok", "count": 1, "items": [row], "navigated": "u"})
            stderr = ""

        original = mod.subprocess.run
        mod.subprocess.run = lambda cmd, **kw: FakeProc()
        try:
            items, errors, sources = mod.naver_browser_search(
                NaverLinkTest.REGION, make_opts(property_types=["원룸", "빌라"])
            )
        finally:
            mod.subprocess.run = original
        self.assertEqual(len(items), 1)
        self.assertEqual(len(sources), 2)
        self.assertEqual(errors, [])


class RegionTieBreakTest(unittest.TestCase):
    """동명이 여럿일 때 어느 후보가 뽑히는지 고정한다."""

    def setUp(self):
        self.original = (mod.resolve_region_zigbang, mod.resolve_region_dabang)
        names = [
            "경상북도 영주시 문정동",
            "대구광역시 남구 문정동",
            "서울특별시 송파구 문정동",
        ]
        fake = [
            mod.Region(query="문정동", name="문정동", full_name=n, lat=37.0, lng=127.0, source="test")
            for n in names
        ]
        mod.resolve_region_zigbang = lambda q: list(fake)
        mod.resolve_region_dabang = lambda q: []

    def tearDown(self):
        mod.resolve_region_zigbang, mod.resolve_region_dabang = self.original

    def test_seoul_wins_without_prefer(self):
        region, candidates, errors = mod.pick_region("문정동")
        self.assertEqual(region.full_name, "서울특별시 송파구 문정동")
        self.assertEqual(errors, [])
        self.assertEqual(len(candidates), 3)

    def test_prefer_overrides_metro_order(self):
        region, _, _ = mod.pick_region("문정동", prefer="대구")
        self.assertEqual(region.full_name, "대구광역시 남구 문정동")

    def test_metro_rank_order(self):
        self.assertLess(mod._metro_rank("서울특별시 송파구 문정동"), mod._metro_rank("경기도 성남시 수정구 신흥동"))
        self.assertLess(mod._metro_rank("경기도 성남시 수정구 신흥동"), mod._metro_rank("경상북도 영주시 문정동"))


class RegionUnresolvedTest(unittest.TestCase):
    def setUp(self):
        self.original = (mod.resolve_region_zigbang, mod.resolve_region_dabang)
        mod.resolve_region_zigbang = lambda q: []
        mod.resolve_region_dabang = lambda q: []

    def tearDown(self):
        mod.resolve_region_zigbang, mod.resolve_region_dabang = self.original

    def test_returns_none(self):
        region, candidates, _ = mod.pick_region("존재하지않는동")
        self.assertIsNone(region)
        self.assertEqual(candidates, [])


class CliTest(unittest.TestCase):
    def test_rejects_unknown_trade_type(self):
        with self.assertRaises(SystemExit):
            mod.build_parser().parse_args(["search", "--region", "신흥동", "--trade-type", "반전세"])

    def test_rejects_unknown_provider(self):
        with self.assertRaises(SystemExit):
            mod.build_parser().parse_args(["search", "--region", "신흥동", "--provider", "peterpan"])

    def test_defaults(self):
        opts = mod.build_parser().parse_args(["search", "--region", "신흥동"])
        self.assertFalse(opts.naver_browser)  # browser path is opt-in
        self.assertEqual(opts.trade_types, ["전세"])
        self.assertEqual(opts.property_types, ["원룸", "빌라"])
        self.assertEqual(opts.providers, ["zigbang", "dabang"])

    def test_zigbang_batch_stays_within_portal_limit(self):
        self.assertLessEqual(mod.MAX_DETAIL_BATCH, 15)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
