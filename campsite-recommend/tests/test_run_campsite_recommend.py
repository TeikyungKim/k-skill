"""Offline tests for campsite-recommend (no network access)."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "run_campsite_recommend.py"

spec = importlib.util.spec_from_file_location("run_campsite_recommend", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def foresttrip_payload() -> dict:
    def room(goods_id: str, use_dt: str, forest_id: str = "ID0001") -> dict:
        return {
            "forest_id": forest_id,
            "forest": "[공립](테스트군)테스트자연휴양림",
            "use_dt": use_dt,
            "name": f"데크{goods_id[-2:]}",
            "capacity": "4",
            "category": "야영데크",
            "goods_id": goods_id,
            "max_stay_nights": 3,
            "stay_nights": 3,
        }

    return {
        "results": [
            {
                "forest": "[공립](테스트군)테스트자연휴양림",
                "dates": [
                    {"use_dt": "20261002", "rooms": [room("G01", "20261002"), room("G02", "20261002")]},
                    {"use_dt": "20261003", "rooms": [room("G01", "20261003")]},
                ],
            }
        ]
    }


def campsite_payload(status: str = "open") -> dict:
    def day(use_dt: str, booking_status: str) -> dict:
        return {
            "use_dt": use_dt,
            "booking_status": booking_status,
            "status_note": None if booking_status == "open" else "아직 열리지 않음",
            "zones": [
                {"zone_id": "z1", "zone": "사이트 A", "remaining": 3, "available": True},
                {"zone_id": "z2", "zone": "사이트 B", "remaining": 0, "available": False},
            ],
        }

    return {
        "dates": ["20261002", "20261003"],
        "results": [
            {
                "provider": "test-provider",
                "name": "테스트캠핑장",
                "dates": [day("20261002", "open"), day("20261003", status)],
            }
        ],
    }


class ScoreFormulaTest(unittest.TestCase):
    def test_reproduces_jangtaesan_snapshot(self):
        # 2026-08-29 스냅샷: 평점 4.5 · 평가 235 · 리뷰 744 → 92.81 (SCORING.md 검산 예시)
        result = mod.compute_score(4.5, 235, 744)
        self.assertEqual(result["score"], 92.81)
        self.assertEqual(result["review_term"], 100.0)

    def test_low_sample_pulls_toward_prior(self):
        high_small = mod.compute_score(5.0, 2, 0)
        high_large = mod.compute_score(5.0, 200, 0)
        self.assertLess(high_small["adjusted_rating"], high_large["adjusted_rating"])


class NormalizeNameTest(unittest.TestCase):
    def test_strips_leading_tags_and_whitespace(self):
        self.assertEqual(mod.normalize_name("[공립](합천군)오도산자연휴양림"), "오도산자연휴양림")
        self.assertEqual(mod.normalize_name(" 연곡해변 솔향기캠핑장 "), "연곡해변솔향기캠핑장")


class PlaceMapIntegrityTest(unittest.TestCase):
    def test_place_map_is_well_formed(self):
        data = mod.load_place_map()
        entries = {**data["foresttrip"], **data["providers"]}
        self.assertGreaterEqual(len(entries), 61)
        place_ids = [v["kakao_place_id"] for v in entries.values()]
        self.assertEqual(len(place_ids), len(set(place_ids)), "kakao place id must be unique")
        for key, value in entries.items():
            self.assertTrue(value["name"], key)
            self.assertTrue(value["region"], key)
            self.assertRegex(value["kakao_place_id"], r"^\d+$", key)


class AggregationTest(unittest.TestCase):
    def test_foresttrip_counts_only_all_date_sites(self):
        facilities = mod.aggregate_foresttrip(foresttrip_payload())
        self.assertEqual(len(facilities), 1)
        facility = facilities[0]
        self.assertEqual(facility["available_sites"], 1)  # G01만 두 날짜 모두
        self.assertTrue(facility["confirmed"])
        self.assertEqual(facility["id"], "ID0001")

    def test_campsite_open_dates_intersect_zones(self):
        facilities = mod.aggregate_campsite(campsite_payload("open"))
        self.assertEqual(facilities[0]["available_sites"], 1)
        self.assertTrue(facilities[0]["confirmed"])

    def test_campsite_not_open_date_blocks_confirmation(self):
        facilities = mod.aggregate_campsite(campsite_payload("not_open"))
        self.assertFalse(facilities[0]["confirmed"])
        self.assertIn("20261003", facilities[0]["status_note"])

    def test_detect_input_kind(self):
        self.assertEqual(mod.detect_input_kind(foresttrip_payload()), "foresttrip")
        self.assertEqual(mod.detect_input_kind(campsite_payload()), "campsite")
        with self.assertRaises(ValueError):
            mod.detect_input_kind({"rows": []})


class BuildReportTest(unittest.TestCase):
    def test_ranked_sorted_and_unmapped_separated(self):
        place_map = {
            "foresttrip": {
                "F-HIGH": {"name": "높은휴양림", "region": "A", "kakao_place_id": "111"},
                "F-LOW": {"name": "낮은휴양림", "region": "B", "kakao_place_id": "222"},
            },
            "providers": {},
        }
        facilities = [
            {"source": "foresttrip", "id": "F-LOW", "name": "낮은휴양림", "dates": [],
             "available_sites": 9, "site_types": {}, "capacities": [], "max_stay_nights": 3,
             "confirmed": True, "status_note": None},
            {"source": "foresttrip", "id": "F-HIGH", "name": "높은휴양림", "dates": [],
             "available_sites": 2, "site_types": {}, "capacities": [], "max_stay_nights": 3,
             "confirmed": True, "status_note": None},
            {"source": "foresttrip", "id": "F-UNMAPPED", "name": "미지의휴양림", "dates": [],
             "available_sites": 5, "site_types": {}, "capacities": [], "max_stay_nights": 3,
             "confirmed": True, "status_note": None},
        ]
        ratings = {
            "111": {"place_name": "높은휴양림", "address": "a", "lon": 127.0, "lat": 37.0,
                    "rating": 4.8, "rating_count": 200, "review_count": 500},
            "222": {"place_name": "낮은휴양림", "address": "b", "lon": 127.1, "lat": 37.1,
                    "rating": 3.5, "rating_count": 50, "review_count": 20},
        }
        report = mod.build_report(facilities, place_map, ratings)
        self.assertEqual([r["name"] for r in report["ranked"]], ["높은휴양림", "낮은휴양림"])
        self.assertEqual(report["ranked"][0]["rank"], 1)
        self.assertEqual(len(report["unranked"]), 1)
        self.assertEqual(report["unranked"][0]["name"], "미지의휴양림")
        self.assertIn("매핑 없음", report["unranked"][0]["unranked_reason"])

    def test_unconfirmed_facility_goes_unranked_even_if_mapped(self):
        place_map = {"foresttrip": {"F1": {"name": "x", "region": "r", "kakao_place_id": "1"}}, "providers": {}}
        facilities = [{"source": "foresttrip", "id": "F1", "name": "x", "dates": [],
                       "available_sites": 0, "site_types": {}, "capacities": [], "max_stay_nights": None,
                       "confirmed": False, "status_note": "미오픈"}]
        report = mod.build_report(facilities, place_map, {"1": {"rating": 4.0, "rating_count": 1, "review_count": 1}})
        self.assertEqual(report["ranked"], [])
        self.assertEqual(report["unranked"][0]["unranked_reason"], "미오픈")

    def test_render_text_smoke(self):
        report = mod.build_report([], {"foresttrip": {}, "providers": {}}, {})
        text = mod.render_text(report)
        self.assertIn("추천 순위 0곳", text)


class InputRoundTripTest(unittest.TestCase):
    def test_load_vacancy_inputs_merges_both_kinds(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "f.json"
            p2 = Path(tmp) / "c.json"
            p1.write_text(json.dumps(foresttrip_payload()), encoding="utf-8")
            p2.write_text(json.dumps(campsite_payload()), encoding="cp949")
            facilities = mod.load_vacancy_inputs([str(p1), str(p2)])
        self.assertEqual({f["source"] for f in facilities}, {"foresttrip", "campsite"})


if __name__ == "__main__":
    unittest.main()
