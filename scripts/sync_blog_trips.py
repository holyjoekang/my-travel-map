"""네이버 블로그 RSS의 새 여행 글을 여정 원장(data/trips.json)에 붙인다. LLM 없이 규칙만 쓴다.

    python scripts/sync_blog_trips.py            # RSS를 읽는다 (CI 기본)
    python scripts/sync_blog_trips.py --rss f.xml  # 받아 둔 RSS 파일로

- 여행 카테고리 글 중 trips.json 의 links 에 아직 없는 글만 본다
- 제목에서 아는 도시·장소(place_coords · place_aliases)를 찾는다. 하나도 없으면 여행 글이 아니라고 본다
- 같은 도시가 들어간 여정이 글 날짜 앞뒤(시작 -7일 ~ 끝 +30일)에 있으면 그 여정에 링크를 붙이고,
  없으면 새 여정을 만든다 ('N박M일'이 있으면 글 날짜를 끝날로 보고 거슬러 잡는다)
"""
from __future__ import annotations

import datetime as dt
import email.utils
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
RSS = "https://rss.blog.naver.com/joekang.xml"
TRAVEL_CATS = {"달리기,여행,맛집"}


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def rss_items(path=None):
    raw = Path(path).read_bytes() if path else urllib.request.urlopen(
        urllib.request.Request(RSS, headers={"User-Agent": "my-travel-map"}), timeout=30).read()
    for it in ET.fromstring(raw).iter("item"):
        yield {"cat": (it.findtext("category") or "").strip(),
               "url": (it.findtext("link") or "").split("?")[0],
               "title": re.sub(r"\s*#\S.*$", "", (it.findtext("title") or "").strip()),
               "date": email.utils.parsedate_to_datetime(it.findtext("pubDate")).date()}


def main():
    args = sys.argv[1:]
    rss = args[args.index("--rss") + 1] if "--rss" in args else None
    doc = load("trips.json")
    trips = doc["trips"]
    aliases = {k: v for k, v in load("place_aliases.json").items() if not k.startswith("_")}
    names = {n: n for n in load("place_coords.json") if not n.startswith("_")}
    names.update({k: v for k, v in aliases.items()})
    for n in list(names):  # '다롄 시' 는 제목에 '다롄'으로 나온다
        short = re.sub(r"\s*시$", "", n)
        if len(short) >= 2:
            names.setdefault(short, names[n])
    country = {p["name"]: p.get("country") for p in load("places.json")["places"]}
    known = {lk["url"] for t in trips for lk in t.get("links", [])} | {t.get("blog") for t in trips}
    eras = sorted(doc["eras"], key=lambda e: e["start"])

    added = 0
    for p in sorted(rss_items(rss), key=lambda i: i["date"]):
        if p["cat"] not in TRAVEL_CATS or p["url"] in known:
            continue
        found = []
        for n in sorted(names, key=len, reverse=True):
            if n in p["title"] and names[n] not in found:
                found.append(names[n])
        if not found:
            print(f"  · 건너뜀(장소 없음): {p['title']}")
            continue
        link = {"label": "블로그 · " + p["title"], "url": p["url"]}
        d = p["date"]
        near = [t for t in trips if set(found) & set(t.get("cities", []) + t.get("places", []))
                and dt.date.fromisoformat(t["start"]) - dt.timedelta(7) <= d
                <= dt.date.fromisoformat(t["end"]) + dt.timedelta(30)]
        if near:
            near[-1].setdefault("links", []).append(link)
            print(f"  + 링크 → {near[-1]['id']}: {p['title']}")
        else:
            m = re.search(r"(\d+)\s*박\s*\d+\s*일", p["title"])
            start = d - dt.timedelta(int(m[1]) if m else 0)
            tid = f"t-{start}"
            while any(t["id"] == tid for t in trips):
                tid += "b"
            domestic = all(country.get(c, "대한민국") == "대한민국" for c in found)
            trips.append({"id": tid, "title": p["title"][:40], "start": str(start), "end": str(d),
                          "era": [e["id"] for e in eras if e["start"] <= str(start)][-1],
                          "purpose": "couple" if re.search("아내|부부", p["title"]) else "solo",
                          "scope": "domestic" if domestic else "overseas",
                          "cities": found, "links": [link], "sources": ["blog"], "confidence": "medium"})
            print(f"  + 새 여정 {tid}: {p['title']}")
        known.add(p["url"])
        added += 1
    if added:
        (DATA / "trips.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"여행 글 {added}편 반영")


if __name__ == "__main__":
    main()
