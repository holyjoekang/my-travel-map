"""빌드 파이프라인 검증.

실행: python -m unittest discover -s tests -v   (프로젝트 루트에서)
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402
import build_places  # noqa: E402
import topojson  # noqa: E402


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class TopoJson(unittest.TestCase):
    def test_delta_decoding(self):
        topo = {
            "transform": {"scale": [1, 1], "translate": [0, 0]},
            "arcs": [[[0, 0], [2, 3], [1, 1]]],
        }
        self.assertEqual(topojson.decode_arcs(topo), [[[0, 0], [2, 3], [3, 4]]])

    def test_reversed_arc(self):
        """음수 인덱스는 해당 arc를 뒤집어 쓴다."""
        topo = {
            "transform": {"scale": [1, 1], "translate": [0, 0]},
            "arcs": [[[0, 0], [1, 0]], [[1, 0], [0, 1]]],
            "objects": {"x": {"geometries": [{"type": "Polygon", "arcs": [[0, 1, -1]]}]}},
        }
        ring = topojson.features(topo, "x")[0]["rings"][0]
        self.assertEqual(ring[0], [0, 0])
        self.assertEqual(ring[-1], [0, 0])  # 되돌아와 닫힌다

    def test_simplify_drops_duplicates(self):
        ring = [[1.111, 2.222], [1.11, 2.22], [3.0, 4.0]]
        self.assertEqual(topojson.simplify(ring, 1), [[1.1, 2.2], [3.0, 4.0]])


class Aliases(unittest.TestCase):
    def setUp(self):
        self.aliases = build_places.strip_notes(load("data/place_aliases.json"))

    def test_known_pairs_collapse(self):
        """PRD §5에서 실물로 확인한 세 쌍은 반드시 한 도시로 모여야 한다."""
        for raw, want in [("하문", "샤먼 시"), ("온주", "원저우 시"),
                          ("내몽고 후룬베이얼", "후룬베이얼 시"), ("북경", "베이징")]:
            self.assertEqual(build_places.canonical(raw, self.aliases), want, raw)

    def test_unknown_passes_through(self):
        self.assertEqual(build_places.canonical("듣보 시", self.aliases), "듣보 시")

    def test_no_alias_points_at_missing_target(self):
        """별칭의 목적지는 좌표 원장이나 저장 목록에 실제로 있어야 한다."""
        coords = build_places.strip_notes(load("data/place_coords.json"))
        saved = {p["name"] for p in load("data/gmaps_saved_2005.json")["places"]}
        for raw, target in self.aliases.items():
            self.assertTrue(target in coords or target in saved,
                            f"{raw} → {target} 가 어디에도 없다")


class Places(unittest.TestCase):
    def setUp(self):
        self.out = build_places.build()
        self.places = {p["name"]: p for p in self.out["places"]}

    def test_saved_list_fully_ingested(self):
        saved = load("data/gmaps_saved_2005.json")
        self.assertEqual(saved["list"]["total"], len(saved["places"]))
        e3 = [p for p in self.out["places"] if "E3" in p["eras"]]
        self.assertGreaterEqual(len(e3), 120)

    def test_coords_present(self):
        """좌표가 없어도 되는 것은 needsReview 장소뿐이다."""
        for name in self.out["missingCoords"]:
            self.assertTrue(self.places[name]["needsReview"],
                            f"{name} 에 좌표가 없는데 확인 필요 표시도 없다")

    def test_coords_in_range(self):
        for p in self.out["places"]:
            if p["lat"] is None:
                continue
            self.assertTrue(-90 <= p["lat"] <= 90, p["name"])
            self.assertTrue(-180 <= p["lng"] <= 180, p["name"])

    def test_xiamen_merged_not_duplicated(self):
        """'하문'(출장표)과 '샤먼 시'(지도)가 두 도시로 갈라지면 안 된다."""
        self.assertIn("샤먼 시", self.places)
        self.assertNotIn("하문", self.places)
        self.assertIn("하문", self.places["샤먼 시"]["aliasesSeen"])

    def test_trip_cities_all_resolve(self):
        trips = load("data/trips.json")
        aliases = build_places.strip_notes(load("data/place_aliases.json"))
        for t in trips["trips"]:
            for raw in t.get("cities", []):
                self.assertIn(build_places.canonical(raw, aliases), self.places,
                              f"{t['id']} 의 '{raw}' 가 장소 마스터에 없다")


class Trips(unittest.TestCase):
    def setUp(self):
        self.doc = load("data/trips.json")

    def test_dates_ordered(self):
        for t in self.doc["trips"]:
            if t.get("end"):
                self.assertLessEqual(str(t["start"]), str(t["end"]), t["id"])

    def test_era_exists_and_matches_dates(self):
        eras = {e["id"]: e for e in self.doc["eras"]}
        for t in self.doc["trips"]:
            self.assertIn(t["era"], eras, t["id"])
            era = eras[t["era"]]
            start = str(t["start"])[:7]
            if len(start) == 4:
                continue  # 연도만 아는 기억 여정은 건너뛴다
            self.assertGreaterEqual(start, era["start"][:7], f"{t['id']} 가 {era['id']} 보다 이르다")
            if era["end"]:
                self.assertLessEqual(start, era["end"][:7], f"{t['id']} 가 {era['id']} 보다 늦다")

    def test_companions_exist(self):
        for t in self.doc["trips"]:
            for c in t.get("companions", []):
                self.assertIn(c, self.doc["people"], f"{t['id']} 의 동행 {c}")

    def test_ids_unique(self):
        ids = [t["id"] for t in self.doc["trips"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_umbrella_pulls_its_source(self):
        """citiesFrom 을 쓰는 포괄 여정은 빌드 후 도시가 실제로 붙어야 한다.

        (한 번 값이 어긋나 E3 도시 127곳이 지도에서 통째로 빠진 적이 있다.)
        """
        payload = build_app.build_payload(public=False)
        for raw in self.doc["trips"]:
            if not raw.get("citiesFrom"):
                continue
            built = next(t for t in payload["trips"] if t["id"] == raw["id"])
            self.assertGreater(len(built["cities"]), 100, raw["id"])


class PublicBuild(unittest.TestCase):
    """PRD §11 — 공개 빌드에 실명이 들어가면 안 된다."""

    def test_real_names_absent(self):
        payload = build_app.build_payload(public=True)
        blob = json.dumps(payload, ensure_ascii=False)
        people = build_app.strip_notes(load("data/trips.json")["people"])
        for pid, person in people.items():
            name = person.get("realName")
            if not name or person.get("publicLabel") == name:
                continue
            self.assertNotIn(name, blob, f"공개 빌드에 실명 '{name}' 이 남아 있다")

    def test_private_build_keeps_names(self):
        """개인 빌드는 실명을 그대로 쓴다. 실명은 저장소 밖(data/private.json)에 있으므로
        여기에 적지 않고 그 파일에서 읽어 확인한다. 파일이 없으면(CI) 건너뛴다."""
        if not build_app.PRIVATE.exists():
            self.skipTest("data/private.json 없음 — 공개 표기만으로 빌드된다")
        priv = build_app.strip_notes(load("data/private.json")["people"])
        # 어느 여정에도 동행으로 안 붙은 사람은 번들에 나올 이유가 없다.
        used = {c for t in load("data/trips.json")["trips"]
                for c in t.get("companions", [])}
        blob = json.dumps(build_app.build_payload(public=False), ensure_ascii=False)
        checked = 0
        for pid in used & priv.keys():
            name = priv[pid].get("realName")
            if name:
                self.assertIn(name, blob, pid)
                checked += 1
        self.assertGreater(checked, 0, "확인할 실명이 하나도 없다")

    def test_no_gender_guessed(self):
        """표기를 정하지 않은 사람에게 Mr./Ms.를 임의로 붙이지 않는다."""
        payload = build_app.build_payload(public=True)
        for t in payload["trips"]:
            for label in t["companions"]:
                self.assertNotRegex(label, r"^(Mr\.|Ms\.)")

    def test_business_summary_withheld(self):
        """공개용 요약이 없는 출장은 요약을 내보내지 않는다."""
        payload = build_app.build_payload(public=True)
        for t in payload["trips"]:
            if t["purpose"] == "business":
                self.assertIsNone(t["summary"], t["id"])


class Bundle(unittest.TestCase):
    def test_placeholder_replaced(self):
        html = (ROOT / "app/index.html").read_text(encoding="utf-8")
        self.assertNotIn("/*__DATA__*/", html)
        self.assertIn("나의 여행 지도", html)

    def test_no_external_resources(self):
        """외부 스크립트·이미지를 받지 않아야 아티팩트에서도 뜬다 (PRD §8)."""
        html = (ROOT / "app/index.html").read_text(encoding="utf-8")
        for bad in ["<script src=", "<link rel=\"stylesheet\"", "https://maps.googleapis"]:
            self.assertNotIn(bad, html)


if __name__ == "__main__":
    unittest.main()
