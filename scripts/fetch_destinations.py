"""trip.com 여행 가이드에서 대표 여행지의 사진과 소개를 받아 캐시한다.

`data/tripcom_places.json` 에 적힌 (우리 장소 이름 → trip.com 목적지 번호) 짝을 돌며
공개 목적지 페이지에서 대표 사진·소개 글·원문 링크를 뽑아 `data/destinations.json` 에 쌓는다.
앱은 이 캐시만 읽는다 — 화면이 뜰 때 trip.com 을 부르지 않는다.

사용법
  python scripts/fetch_destinations.py              # 캐시에 없는 것만
  python scripts/fetch_destinations.py --refresh    # 전부 다시
  python scripts/fetch_destinations.py --only 베이징 상하이

예의
  robots.txt 가 열어 둔 /travel-guide/destination/ 만 본다. 한 건마다 쉬고,
  실패하면 이전 캐시를 그대로 둔다. 사진은 내려받지 않는다 — 원본을 링크로 건다(PRD §14).
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DATA = Path("data")
MAP = DATA / "tripcom_places.json"
OUT = DATA / "destinations.json"

BASE = "https://kr.trip.com/travel-guide/destination"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
PAUSE = 0.6          # 초 — 한 건 받고 쉬는 시간
HEAD_BYTES = 400_000  # __NEXT_DATA__ 까지면 충분하다
INTRO_MAX = 260       # 소개 글은 발췌만 싣는다. 전문은 trip.com 에서 본다


def strip_notes(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def slug(en_name: str, did: int) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(en_name or "d").lower()).strip("-")
    return f"{s or 'd'}-{did}"


def fetch(did: int) -> dict | None:
    """목적지 페이지의 머리 모듈(__NEXT_DATA__)을 읽는다."""
    req = urllib.request.Request(
        f"{BASE}/d-{did}/",
        headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9",
                 "Range": f"bytes=0-{HEAD_BYTES}"},
    )
    try:
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  ! {did}: {e}")
        return None
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        print(f"  ! {did}: 페이지 구조가 바뀌었다")
        return None
    try:
        props = json.loads(m.group(1))["props"]["pageProps"]
    except (ValueError, KeyError):
        print(f"  ! {did}: 데이터를 읽지 못했다")
        return None
    return props


def excerpt(text: str, limit: int = INTRO_MAX) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # 문장 중간에서 끊지 않는다
    stop = max(cut.rfind("다."), cut.rfind("요."), cut.rfind("."))
    return (cut[: stop + 1] if stop > limit * 0.5 else cut.rstrip() + "…")


def entry(place: str, did: int, props: dict) -> dict:
    head = props.get("onlineHeadModule") or {}
    en = props.get("englishName") or head.get("districtEnName") or place
    photos = []
    for p in (head.get("photoInfoList") or [])[:6]:
        if p.get("url"):
            photos.append({"url": p["url"], "poi": p.get("poiName") or ""})
    for url in (head.get("districtPhotoList") or []):
        if url and all(url != x["url"] for x in photos):
            photos.append({"url": url, "poi": ""})
    coord = head.get("coord") or {}
    return {
        "place": place,
        "id": did,
        "name": head.get("districtName") or props.get("destinationName") or place,
        "enName": en,
        "country": (head.get("parentDistrict") or {}).get("name"),
        "url": f"{BASE}/{slug(en, did)}/",
        "cover": head.get("imageUrl") or props.get("coverImageId"),
        "intro": excerpt(head.get("introduction")),
        "photos": photos[:6],
        "lat": coord.get("latitude"),
        "lng": coord.get("longitude"),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    refresh = "--refresh" in args
    only = args[args.index("--only") + 1:] if "--only" in args else None

    mapping = strip_notes(json.loads(MAP.read_text(encoding="utf-8")))
    cached = {}
    if OUT.exists():
        cached = {d["place"]: d for d in json.loads(OUT.read_text(encoding="utf-8"))["destinations"]}

    got = new = 0
    for place, did in mapping.items():
        if only and place not in only:
            continue
        if place in cached and not refresh:
            continue
        props = fetch(int(did))
        if props:
            cached[place] = entry(place, int(did), props)
            new += 1
            print(f"  · {place} ← {cached[place]['name']} ({did})")
        time.sleep(PAUSE)
    got = len([p for p in mapping if p in cached])

    order = list(mapping)
    doc = {
        "_": "빌드 산출물이 아니라 캐시다. scripts/fetch_destinations.py 가 채운다.",
        "source": "https://kr.trip.com/travel-guide/destination/",
        "credit": "사진·소개 글 © Trip.com. 발췌만 싣고 원문으로 링크한다.",
        "fetched": time.strftime("%Y-%m-%d"),
        "destinations": [cached[p] for p in order if p in cached],
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    missing = [p for p in mapping if p not in cached]
    print(f"{OUT}: 여행지 {got}/{len(mapping)} (새로 {new})")
    if missing:
        print(f"못 받은 곳: {', '.join(missing)}")


if __name__ == "__main__":
    main()
