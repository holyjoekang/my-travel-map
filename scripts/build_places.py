"""장소 마스터를 만든다.

입력
  data/gmaps_saved_2005.json  — 지도 저장 목록 128개 (E3)
  data/trips.json             — 여정 원장 (cities는 원문 표기 그대로)
  data/place_aliases.json     — 표기 → 정식 도시명
  data/place_coords.json      — 정식 도시명 → [위도, 경도]

출력
  data/places.json            — 정규화된 장소 + 좌표 + 방문 집계

정규화 규칙은 PRD §5. 이름이 어떻게 들어오든 별칭 사전을 거쳐 한 도시로 모은다.

사용법: python scripts/build_places.py [--strict]
  --strict : 좌표가 없는 장소가 있으면 오류로 끝낸다(CI용)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path("data")


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def strip_notes(d: dict) -> dict:
    """_로 시작하는 주석 키를 걷어낸다."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def canonical(name: str, aliases: dict) -> str:
    """표기 하나를 정식 도시명으로 바꾼다. 사전에 없으면 원문을 그대로 쓴다."""
    return aliases.get(name.strip(), name.strip())


def build() -> dict:
    saved = load("gmaps_saved_2005.json")
    trips = load("trips.json")
    aliases = strip_notes(load("place_aliases.json"))
    coords = strip_notes(load("place_coords.json"))

    places: dict[str, dict] = {}

    def touch(name: str, **fields) -> dict:
        key = canonical(name, aliases)
        p = places.setdefault(
            key,
            {
                "name": key,
                "level": "city",
                "country": None,
                "region": None,
                "parent": None,
                "kind": None,
                "lat": None,
                "lng": None,
                "sources": [],
                "tripIds": [],
                "eras": [],
                "aliasesSeen": [],
                "needsReview": False,
            },
        )
        for k, v in fields.items():
            if v is not None and p.get(k) in (None, False, "city"):
                p[k] = v
        if name.strip() != key and name.strip() not in p["aliasesSeen"]:
            p["aliasesSeen"].append(name.strip())
        return p

    # 1) 지도 저장 목록 — E3의 장소 마스터
    for row in saved["places"]:
        p = touch(
            row["name"],
            level=row.get("level"),
            country=row.get("country"),
            region=row.get("region"),
            parent=row.get("parentCity") or row.get("parentPrefecture"),
            kind=row.get("kind"),
        )
        if "gmaps_saved" not in p["sources"]:
            p["sources"].append("gmaps_saved")
        if "E3" not in p["eras"]:
            p["eras"].append("E3")
        if row.get("needsReview"):
            p["needsReview"] = True
        if row.get("note"):
            p["note"] = row["note"]

    # 2) 여정에 등장한 도시
    for trip in trips["trips"]:
        for raw in trip.get("cities", []):
            p = touch(raw)
            for s in trip.get("sources", []):
                if s not in p["sources"]:
                    p["sources"].append(s)
            if trip["id"] not in p["tripIds"]:
                p["tripIds"].append(trip["id"])
            if trip["era"] not in p["eras"]:
                p["eras"].append(trip["era"])

    # 3) 좌표 결합. 없으면 상위 도시 좌표를 빌린다.
    for p in places.values():
        xy = coords.get(p["name"])
        if xy:
            p["lat"], p["lng"] = xy
    for p in places.values():
        if p["lat"] is None and p["parent"]:
            parent = places.get(canonical(p["parent"], aliases))
            if parent and parent["lat"] is not None:
                p["lat"], p["lng"] = parent["lat"], parent["lng"]
                p["coordFrom"] = "parent"

    # 4) 국가 보정 — 저장 목록에 없던 도시는 좌표로 대충 나눈다.
    for p in places.values():
        if p["country"]:
            continue
        p["country"] = guess_country(p["name"], p["lat"], p["lng"])

    ordered = sorted(places.values(), key=lambda p: (p["country"] or "", p["name"]))
    missing = [p["name"] for p in ordered if p["lat"] is None]
    return {"places": ordered, "missingCoords": missing}


KR_CITIES = {"서울", "제주", "부여", "양평", "평택", "남해", "유명산"}


def guess_country(name: str, lat: float | None, lng: float | None) -> str | None:
    if name in KR_CITIES:
        return "대한민국"
    if lat is None:
        return None
    table = [
        ("싱가포르", 0.9, 1.8, 103.4, 104.2),
        ("말레이시아", 2.5, 3.6, 101.2, 102.1),
        ("태국", 13.0, 14.3, 100.0, 101.0),
        ("인도", 27.9, 29.3, 76.7, 77.7),
        ("베트남", 8.0, 24.0, 102.0, 110.0),
        ("일본", 30.0, 46.0, 129.0, 146.0),
        ("대만", 21.8, 25.5, 119.9, 122.1),
        ("대한민국", 33.0, 38.7, 125.0, 130.0),
        ("영국", 49.8, 59.5, -8.2, 2.0),
        ("미국", 24.0, 49.5, -125.0, -66.0),
        ("중국", 17.0, 54.0, 73.0, 135.0),
    ]
    for country, la0, la1, ln0, ln1 in table:
        if la0 <= lat <= la1 and ln0 <= lng <= ln1:
            return country
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = build()
    (DATA / "places.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    total = len(out["places"])
    cities = sum(1 for p in out["places"] if p["level"] in ("city", "prefecture", "territory"))
    print(f"data/places.json: 장소 {total} · 도시급 {cities} · 좌표없음 {len(out['missingCoords'])}")
    if out["missingCoords"]:
        print("  좌표 없음:", ", ".join(out["missingCoords"]))
        if "--strict" in sys.argv:
            sys.exit(1)


if __name__ == "__main__":
    main()
