"""app/index.html 을 만든다.

데이터를 HTML에 넣어 배포한다. 외부 호출이 없으므로 파일 하나만 열면 동작하고,
아티팩트 CSP에도 걸리지 않는다(PRD §8).

사용법
  python scripts/build_app.py              # 개인 빌드 (실명 포함)
  python scripts/build_app.py --public     # 공개 빌드 (실명을 번들에 넣지 않는다)

공개 빌드는 실명이 하나라도 남아 있으면 빌드를 실패시킨다(PRD §11).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA = Path("data")
APP = Path("app")
TEMPLATE = APP / "index.template.html"
PRIVATE = DATA / "private.json"   # .gitignore — 실명과 업무 요약
SITE = DATA / "site.json"         # 홈 화면 문구 — 없어도 기본값으로 돈다
DESTS = DATA / "destinations.json"  # trip.com 여행지 캐시 — 없어도 사진 없이 돈다
OUT = APP / "index.html"

NEUTRAL = {
    "colleague": "동료",
    "client": "거래선",
    "friend": "친구",
    "family": "가족",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def strip_notes(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def person_label(pid: str, person: dict, public: bool, seq: dict) -> str:
    """사람 표시 이름. 공개 빌드에서는 실명을 절대 쓰지 않는다."""
    if not public:
        name = person.get("realName", pid)
        title = person.get("title")
        return f"{name} {title}".strip() if title else name
    if person.get("publicLabel"):
        return person["publicLabel"]
    # 사용자가 표기를 정하지 않은 사람은 관계별 중립 표기로 나간다.
    # 이름으로 성별을 추측하지 않는다(PRD §11-2).
    rel = person.get("relation", "colleague")
    seq[rel] = seq.get(rel, 0) + 1
    return f"{NEUTRAL.get(rel, '동행')} {chr(ord('A') + seq[rel] - 1)}"


def site_and_destinations() -> tuple[dict, list]:
    """홈 화면 문구와 trip.com 여행지 캐시. 둘 다 없어도 앱은 그대로 돈다.

    사진과 소개 글은 번들에 넣지 않는다 — 주소만 넣고 원본을 링크로 건다(PRD §14).
    """
    site = strip_notes(load(SITE)) if SITE.exists() else {}
    dests = load(DESTS)["destinations"] if DESTS.exists() else []
    if "invite" in site:
        site["invite"] = strip_notes(site["invite"])
    return site, dests


def build_payload(public: bool) -> dict:
    places_doc = load(DATA / "places.json")
    trips_doc = load(DATA / "trips.json")
    world = load(DATA / "world_land.json")
    aliases = strip_notes(load(DATA / "place_aliases.json"))

    places = {p["name"]: p for p in places_doc["places"]}

    # 실명과 업무 요약은 저장소에 올리지 않는다. data/private.json 이 있으면 덮어쓰고,
    # 없으면(예: CI, 남의 클론) 공개 표기만으로 그대로 빌드된다.
    priv = load(PRIVATE) if PRIVATE.exists() else {}
    people = strip_notes(trips_doc["people"])
    for pid, extra in strip_notes(priv.get("people", {})).items():
        people.setdefault(pid, {}).update(extra)
    priv_summaries = strip_notes(priv.get("summaries", {}))
    seq: dict[str, int] = {}
    labels = {pid: person_label(pid, pr, public, seq) for pid, pr in people.items()}

    e3_places = [p["name"] for p in places_doc["places"] if "E3" in p["eras"]]

    trips = []
    for t in trips_doc["trips"]:
        cities = [aliases.get(c.strip(), c.strip()) for c in t.get("cities", [])]
        # 포괄 여정은 도시를 일일이 적지 않고 소스 전체를 끌어온다.
        if str(t.get("citiesFrom", "")).startswith("gmaps_saved"):
            cities = e3_places
        summary = (t.get("summaryPublic") if public
                   else priv_summaries.get(t["id"]) or t.get("summary"))
        if public and not t.get("summaryPublic"):
            summary = None  # 공개용 요약이 없으면 내보내지 않는다
        trips.append(
            {
                "id": t["id"],
                "title": t.get("title") or " · ".join(cities[:3]),
                "start": t["start"],
                "end": t.get("end") or t["start"],
                "era": t["era"],
                "purpose": t["purpose"],
                "scope": t["scope"],
                "cities": cities,
                "companions": [labels.get(c, c) for c in t.get("companions", [])],
                "role": t.get("role"),
                "summary": summary,
                "sources": t.get("sources", []),
                "confidence": t.get("confidence", "medium"),
                "umbrella": bool(t.get("umbrella")),
                "note": t.get("note"),
            }
        )

    # 도시별 방문 집계
    counts: dict[str, int] = {}
    for t in trips:
        if t["umbrella"]:
            continue
        for c in t["cities"]:
            counts[c] = counts.get(c, 0) + 1
    for name, p in places.items():
        p["visits"] = counts.get(name, 0)

    # 승인 대기 후보 (Phase 2). 공개 빌드에는 넣지 않는다 — 아직 검토 전 자료다.
    candidates = []
    cand_path = DATA / "import_candidates.json"
    if cand_path.exists() and not public:
        for c in load(cand_path)["candidates"]:
            if c["verdict"] == "no":
                continue
            candidates.append({k: c[k] for k in
                               ("logNo", "title", "url", "posted", "date",
                                "cities", "verdict", "why")})

    site, dests = site_and_destinations()
    # 방문한 적 없는 도시의 사진은 실을 이유가 없다.
    dests = [d for d in dests if d["place"] in places]

    return {
        "site": site,
        "destinations": dests,
        "eras": trips_doc["eras"],
        "trips": sorted(trips, key=lambda t: t["start"]),
        "places": list(places.values()),
        "world": world["countries"],
        "candidates": candidates,
        "public": public,
    }


def check_public(html: str, trips_doc: dict) -> list[str]:
    """공개 빌드에 실명이 새어 나갔는지 본다."""
    people = strip_notes(trips_doc["people"])
    if PRIVATE.exists():
        for pid, extra in strip_notes(load(PRIVATE).get("people", {})).items():
            people.setdefault(pid, {}).update(extra)
    leaked = []
    for pid, person in people.items():
        name = person.get("realName")
        if not name or person.get("publicLabel") == name:
            continue  # 스스로 공개 표기인 경우(아내/아들 등)는 제외
        if name in html:
            leaked.append(name)
    return leaked


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    public = "--public" in sys.argv
    payload = build_payload(public)

    html = TEMPLATE.read_text(encoding="utf-8")
    if "/*__DATA__*/" not in html:
        sys.exit("템플릿에 /*__DATA__*/ 자리표시자가 없다")
    html = html.replace(
        "/*__DATA__*/", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )

    if public:
        leaked = check_public(html, load(DATA / "trips.json"))
        if leaked:
            sys.exit(f"공개 빌드에 실명이 남아 있다: {', '.join(leaked)}")

    out = OUT.with_name("index.public.html") if public else OUT
    out.write_text(html, encoding="utf-8")
    kb = out.stat().st_size / 1024
    print(
        f"{out}: 여정 {len(payload['trips'])} · 장소 {len(payload['places'])} · "
        f"{kb:,.0f}KB · {'공개' if public else '개인'} 빌드"
    )


if __name__ == "__main__":
    main()
