"""app/index.html 을 만든다.

데이터를 HTML에 넣어 배포한다. 외부 호출이 없으므로 파일 하나만 열면 동작하고,
아티팩트 CSP에도 걸리지 않는다(PRD §8).

사용법
  python scripts/build_app.py              # 개인 빌드 (실명 포함)
  python scripts/build_app.py --public     # 공개 빌드 (실명을 번들에 넣지 않는다)

공개 빌드는 실명이 하나라도 남아 있으면 빌드를 실패시킨다(PRD §11).
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

import build_itineraries

DATA = Path("data")
APP = Path("app")
MAPS = DATA / "maps.json"         # .gitignore — 구글 지도 브라우저 키
TEMPLATE = APP / "index.template.html"
PRIVATE = DATA / "private.json"   # .gitignore — 실명과 업무 요약
SITE = DATA / "site.json"         # 홈 화면 문구 — 없어도 기본값으로 돈다
DESTS = DATA / "destinations.json"  # trip.com 여행지 캐시 — 없어도 사진 없이 돈다
ART = DATA / "design_pics" / "crops"  # 홈 화면 장식 그림 (한 장에서 잘라 낸 조각들)
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


def album_links(raw, private: bool) -> list[dict]:
    """여정에 붙은 앨범 링크(구글 포토·드라이브 공유 주소 등)를 정리한다.

    raw 는 주소 문자열, {"url", "label"}, 또는 그 목록. 주소는 http(s) 만 받는다 —
    `javascript:` 같은 것이 링크로 나가면 안 된다.
    """
    if not raw:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for it in items:
        url, label = (it.get("url"), it.get("label")) if isinstance(it, dict) else (it, None)
        url = str(url or "").strip()
        if not re.match(r"https?://\S+$", url):
            sys.exit(f"앨범 주소가 http(s) 링크가 아니다: {url!r}")
        out.append({"url": url, "label": label or "앨범", "private": private})
    return out


def site_and_destinations() -> tuple[dict, list]:
    """홈 화면 문구와 trip.com 여행지 캐시. 둘 다 없어도 앱은 그대로 돈다.

    사진과 소개 글은 번들에 넣지 않는다 — 주소만 넣고 원본을 링크로 건다(PRD §14).
    """
    site = strip_notes(load(SITE)) if SITE.exists() else {}
    dests = load(DESTS)["destinations"] if DESTS.exists() else []
    if "invite" in site:
        site["invite"] = strip_notes(site["invite"])
    return site, dests


def art_css() -> str:
    """홈 장식 그림을 CSS 변수로 박는다.

    번들은 파일 하나로 돈다(PRD §8). 그래서 그림도 바깥에서 부르지 않고
    data URI 로 넣는다. 조각이 없으면 변수도 없고, 화면은 그림 없이 그대로 돈다.
    """
    if not ART.exists():
        return ""
    lines = []
    for f in sorted(ART.glob("*.webp")):
        b64 = base64.b64encode(f.read_bytes()).decode("ascii")
        lines.append(f'  --art-{f.stem}:url("data:image/webp;base64,{b64}");')
    return "\n".join(lines)


def maps_key(public: bool) -> str:
    """구글 지도 키. 없으면 빈 문자열이고, 화면은 번들 지도만 쓴다(PRD §8).

    개인 빌드는 `data/maps.json`(gitignore)에서 읽는다. **공개 빌드는 그 파일을 보지
    않는다** — 공개본에 키를 넣으려면 CI에서 환경변수 GOOGLE_MAPS_KEY 로 넣어야 하고,
    그 키에는 반드시 HTTP 리퍼러 제한을 걸어 둔다.
    """
    env = os.environ.get("GOOGLE_MAPS_KEY", "").strip()
    if env:
        return env
    if public or not MAPS.exists():
        return ""
    return str(load(MAPS).get("googleMapsKey", "")).strip()


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
    priv_albums = strip_notes(priv.get("albums", {}))
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
                # 장소는 도시와 따로 관리한다 — 도시 목록에 섞지 않는다(PRD §5).
                "places": [aliases.get(x.strip(), x.strip()) for x in t.get("places", [])],
                "companions": [labels.get(c, c) for c in t.get("companions", [])],
                "role": t.get("role"),
                "summary": summary,
                "sources": t.get("sources", []),
                "confidence": t.get("confidence", "medium"),
                "umbrella": bool(t.get("umbrella")),
                "note": t.get("note"),
                "planned": bool(t.get("planned")),
                # 앨범: trips.json 의 album 은 공개, private.json 의 albums 는 개인 빌드에만.
                # 개인 앨범 주소는 gitignore 된 파일에만 두므로 저장소·공개본에 새지 않는다.
                "albums": album_links(t.get("album"), private=False)
                + ([] if public else album_links(priv_albums.get(t["id"]), private=True)),
            }
        )

    # 도시·장소별 방문 집계
    counts: dict[str, int] = {}
    for t in trips:
        if t["umbrella"]:
            continue
        for c in t["cities"] + t["places"]:
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

    # 일정표. 개인 일정표(data/trip_html/private/)는 공개 빌드에 넣지 않는다(PRD §11).
    itineraries = [i for i in build_itineraries.load_manifest()
                   if not (public and i["private"])]
    if public and any(i["private"] for i in itineraries):
        sys.exit("공개 빌드에 개인 일정표가 섞였다")

    return {
        "site": site,
        "mapsKey": maps_key(public),
        "destinations": dests,
        "itineraries": itineraries,
        "eras": trips_doc["eras"],
        "trips": sorted(trips, key=lambda t: t["start"]),
        "places": list(places.values()),
        "world": world["countries"],
        "candidates": candidates,
        "public": public,
    }


def check_public(html: str, trips_doc: dict) -> list[str]:
    """공개 빌드에 실명이나 개인 앨범 주소가 새어 나갔는지 본다."""
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
    if PRIVATE.exists():
        for raw in strip_notes(load(PRIVATE).get("albums", {})).values():
            for a in album_links(raw, private=True):
                if a["url"] in html:
                    leaked.append(a["url"])
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
    html = html.replace("/*__ART__*/", art_css())

    if public:
        leaked = check_public(html, load(DATA / "trips.json"))
        if leaked:
            sys.exit(f"공개 빌드에 실명·개인 앨범이 남아 있다: {', '.join(leaked)}")

    out = OUT.with_name("index.public.html") if public else OUT
    out.write_text(html, encoding="utf-8")
    kb = out.stat().st_size / 1024
    print(
        f"{out}: 여정 {len(payload['trips'])} · 장소 {len(payload['places'])} · "
        f"{kb:,.0f}KB · {'공개' if public else '개인'} 빌드"
    )


if __name__ == "__main__":
    main()
