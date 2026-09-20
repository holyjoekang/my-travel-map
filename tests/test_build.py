"""빌드 파이프라인 검증.

실행: python -m unittest discover -s tests -v   (프로젝트 루트에서)
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402
import build_itineraries  # noqa: E402
import itinerary_agent  # noqa: E402
import fetch_destinations  # noqa: E402
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


class Itineraries(unittest.TestCase):
    """일정표 (PRD §15) — data/trip_html 의 HTML 한 장이 여정에 붙는다."""

    def setUp(self):
        self.out = build_itineraries.build(check=True)
        self.items = self.out["itineraries"]

    def test_every_itinerary_lands_on_a_trip(self):
        """일정표는 반드시 어떤 여정에 붙는다 — 짝이 없으면 여정을 새로 만든다."""
        self.assertTrue(self.items, "data/trip_html 에 일정표가 하나도 없다")
        ids = {t["id"] for t in load("data/trips.json")["trips"]}
        for m in self.items:
            self.assertTrue(m["tripId"] in ids or m["tripId"] in self.out["added"],
                            m["source"])

    def test_dates_read_from_the_page(self):
        for m in self.items:
            self.assertRegex(m["start"], r"^\d{4}-\d{2}-\d{2}$", m["source"])
            self.assertLessEqual(m["start"], m["end"], m["source"])
            self.assertGreaterEqual(m["days"], 1, m["source"])

    def test_cities_resolve_to_the_place_master(self):
        places = {p["name"] for p in load("data/places.json")["places"]}
        for m in self.items:
            self.assertTrue(m["cities"], m["source"])
            for city in m["cities"]:
                self.assertIn(city, places, f"{m['source']} 의 '{city}'")

    def test_one_file_per_itinerary(self):
        names = [m["file"] for m in self.items]
        self.assertEqual(len(names), len(set(names)))
        for m in self.items:
            self.assertTrue((ROOT / "app/itinerary" / m["file"]).exists(), m["file"])

    def test_public_folder_is_clean(self):
        """공개 폴더의 일정표에 실명·연락처·집주소가 있으면 안 된다 (PRD §11)."""
        for path in sorted(build_itineraries.SRC_DIR.glob("*.html")):
            self.assertEqual(build_itineraries.scan_private(path), [], path.name)

    def test_private_itinerary_never_goes_public(self):
        public = build_app.build_payload(public=True)["itineraries"]
        self.assertFalse([i for i in public if i["private"]])
        private_files = {m["file"] for m in self.items if m["private"]}
        blob = json.dumps(public, ensure_ascii=False)
        for name in private_files:
            self.assertNotIn(name, blob)

    def test_private_build_keeps_them_all(self):
        mine = build_app.build_payload(public=False)["itineraries"]
        self.assertEqual(len(mine), len(build_itineraries.load_manifest()))


SPEC = """제목: 시험 여행
부제: 이틀짜리
기간: 2026-05-01 ~ 2026-05-02
도시: 칭다오
목적: 부부여행
공개: 예
소개: 원고에서 온 소개 문장이다. 서른 자가 넘어야 일정표의 첫 문단으로 잡힌다.

## DAY 1 · 5/1 — 도착
14:00 | 인천공항 출발 | 3번 게이트
- 저녁 해안 산책
줄글 문단은 이렇게 그대로 들어간다.

## 메모
- 수영복

링크: 원문 | https://example.com/post
"""


class Agent(unittest.TestCase):
    """일정표 에이전트 (PRD §15) — 원고 → HTML → 다시 여정으로."""

    def setUp(self):
        self.spec = itinerary_agent.enrich(itinerary_agent.parse_spec(SPEC), {})
        self.html = itinerary_agent.render(self.spec)

    def test_spec_parsed_into_days_and_items(self):
        secs = self.spec["sections"]
        self.assertEqual(len(secs), 2)
        self.assertEqual(secs[0]["day"], 1)
        self.assertIsNone(secs[1]["day"])
        first = secs[0]["items"][0]
        self.assertEqual((first["time"], first["what"], first["note"]),
                         ("14:00", "인천공항 출발", "3번 게이트"))
        self.assertEqual(secs[0]["items"][1]["what"], "저녁 해안 산책")
        self.assertEqual(secs[0]["items"][2]["what"], "")  # 줄글은 문단으로 간다
        self.assertEqual(self.spec["links"][0]["url"], "https://example.com/post")

    def test_city_normalised_and_dates_read(self):
        info = self.spec["info"]
        self.assertEqual(info["cities"], ["칭다오 시"])  # 별칭을 정식 도시명으로
        self.assertEqual((info["start"], info["end"], info["days"]),
                         ("2026-05-01", "2026-05-02", 2))
        self.assertFalse(info["unknown"])

    def test_rendered_page_reads_back_the_same(self):
        """일정표를 다시 읽는 쪽(build_itineraries)이 같은 값을 얻어야 한다."""
        title = build_itineraries.tag_text(self.html, "title")
        body = build_itineraries.text_of(self.html)
        self.assertEqual(build_itineraries.parse_range(title, body, ""),
                         ("2026-05-01", "2026-05-02"))
        table = build_itineraries.needles(
            build_itineraries.strip_notes(load("data/place_aliases.json")))
        self.assertIn("칭다오 시",
                      build_itineraries.parse_cities(title, body[:600], body, table))
        self.assertTrue(build_itineraries.first_paragraph(self.html)
                        .startswith("원고에서 온 소개"))

    def test_page_is_one_file(self):
        """일정표도 파일 하나로 돈다 — 밖에서 받는 것은 trip.com 사진뿐이다(PRD §8·§14)."""
        self.assertNotIn("<script", self.html)
        self.assertNotIn("<link rel=\"stylesheet\"", self.html)
        for url in re.findall(r'src="(https?://[^"]+)"', self.html):
            self.assertTrue(url.startswith("https://ak-d.tripcdn.com/"), url)
        self.assertIn('href="../index.html"', self.html)  # 아카이브로 돌아간다

    def test_generated_page_is_clean(self):
        self.assertEqual(build_itineraries.scan_text(
            build_itineraries.text_of(self.html)), [])

    def test_spec_round_trips(self):
        """검증을 마친 원고를 다시 읽으면 같은 꼭지가 나온다 — 고쳐서 다시 돌릴 수 있다."""
        again = itinerary_agent.parse_spec(itinerary_agent.spec_to_text(self.spec))
        self.assertEqual([s["title"] for s in again["sections"]],
                         [s["title"] for s in self.spec["sections"]])
        self.assertEqual(again["meta"]["도시"], "칭다오 시")

    def test_blog_title_cleaned(self):
        self.assertEqual(
            itinerary_agent.clean_title("[충칭 여행기] 0일차: 첫걸음 #중국여행"),
            "첫걸음")


class Destinations(unittest.TestCase):
    """trip.com 여행지 캐시 (PRD §14)."""

    def setUp(self):
        self.doc = load("data/destinations.json")
        self.mapping = build_app.strip_notes(load("data/tripcom_places.json"))

    def test_every_destination_is_a_place_we_went(self):
        places = {p["name"] for p in load("data/places.json")["places"]}
        for d in self.doc["destinations"]:
            self.assertIn(d["place"], places, d["place"])
            self.assertIn(d["place"], self.mapping, f"{d['place']} 가 목적지 표에 없다")

    def test_photos_are_linked_not_copied(self):
        """사진은 번들에 넣지 않는다 — 주소만 넣고 원본을 링크로 건다."""
        for d in self.doc["destinations"]:
            self.assertTrue(d["url"].startswith("https://kr.trip.com/travel-guide/destination/"),
                            d["place"])
            for url in [d["cover"]] + [p["url"] for p in d["photos"]]:
                if url:
                    self.assertTrue(url.startswith("https://"), d["place"])
                    self.assertNotIn("data:", url, d["place"])

    def test_intro_is_an_excerpt(self):
        """소개 글은 발췌만 싣는다. 전문은 trip.com 에서 본다."""
        for d in self.doc["destinations"]:
            self.assertLessEqual(len(d["intro"] or ""),
                                 fetch_destinations.INTRO_MAX + 1, d["place"])

    def test_payload_carries_site_and_destinations(self):
        for public in (False, True):
            payload = build_app.build_payload(public=public)
            self.assertTrue(payload["destinations"], public)
            self.assertIn("offers", payload["site"], public)


class Bundle(unittest.TestCase):
    # 화면이 사진을 받아도 되는 곳. 이 밖의 주소가 들어오면 빌드가 아니라 테스트가 잡는다.
    IMG_HOSTS = ("https://ak-d.tripcdn.com/",)

    def test_placeholder_replaced(self):
        html = (ROOT / "app/index.html").read_text(encoding="utf-8")
        self.assertNotIn("/*__DATA__*/", html)
        self.assertIn("나의 여행 지도", html)

    def test_no_external_code(self):
        """스크립트·스타일은 전부 파일 안에 있다. 파일 하나로 돌아야 한다 (PRD §8)."""
        html = (ROOT / "app/index.html").read_text(encoding="utf-8")
        for bad in ["<script src=", "<link rel=\"stylesheet\"", "https://maps.googleapis"]:
            self.assertNotIn(bad, html)

    def test_images_only_from_tripcom(self):
        """사진만 밖에서 받는다. 그것도 trip.com 한 곳에서만 (PRD §14)."""
        html = (ROOT / "app/index.html").read_text(encoding="utf-8")
        found = re.findall(r'https?://[^\s"<>]+?\.(?:jpg|jpeg|png|webp|gif)', html)
        self.assertTrue(found, "여행지 사진이 하나도 없다")
        for url in set(found):
            self.assertTrue(url.startswith(self.IMG_HOSTS), url)

    def test_map_still_draws_without_network(self):
        """지도는 사진과 달리 외부를 안 탄다 — 국경은 번들 안에 있다."""
        payload = build_app.build_payload(public=False)
        self.assertGreater(len(payload["world"]), 100)


if __name__ == "__main__":
    unittest.main()
