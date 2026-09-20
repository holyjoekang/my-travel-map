"""일정표(HTML)를 여정에 붙인다.

`data/trip_html/*.html` 은 여행 전에 따로 만들어 둔 **일정표 한 장**이다.
이 스크립트는 그 파일에서 제목·기간·도시를 규칙으로 읽어(LLM을 쓰지 않는다)
여정 원장의 어느 여정인지 찾아 붙이고, 못 찾으면 그 여정을 새로 등록한다.
그래서 화면에서 여정을 누르면 일정표가 곧바로 열린다.

입력
  data/trip_html/*.html          — 공개해도 되는 일정표 (저장소에 올라간다)
  data/trip_html/private/*.html  — 개인 일정표 (.gitignore — 개인 빌드에만 들어간다)
  data/trips.json                — 여정 원장
  data/places.json               — 도시 이름 사전 (없으면 좌표 원장으로 대신한다)

출력
  app/itinerary/<여정id>.html    — 배포용 사본 (돌아가기 링크를 한 줄 넣는다)
  data/itineraries.json          — 빌드 산출물 · 여정 ↔ 일정표 대응표
  data/trips.json                — 짝이 없던 일정표는 여정으로 새로 적는다

사용법
  python scripts/build_itineraries.py            # 개인 · 공개 일정표 모두
  python scripts/build_itineraries.py --check    # 고치지 않고 무엇을 할지만 본다

공개 폴더에 실명·연락처·집주소로 보이는 것이 있으면 빌드를 멈춘다(PRD §11).
그런 일정표는 `data/trip_html/private/` 으로 옮기면 개인 빌드에만 들어간다.
"""

from __future__ import annotations

import html as htmllib
import json
import re
import sys
from datetime import date
from pathlib import Path

DATA = Path("data")
APP = Path("app")
SRC_DIR = DATA / "trip_html"
PRIVATE_DIR = SRC_DIR / "private"
OUT_DIR = APP / "itinerary"
MANIFEST = DATA / "itineraries.json"
TRIPS = DATA / "trips.json"

# 같은 도시를 다루고 날짜가 이만큼 안에 있으면 같은 여정으로 본다.
MATCH_DAYS = 30
SUMMARY_MAX = 160

# 공개 폴더에 있으면 안 되는 것들. 이름을 추측하지 않고 형태로만 걸러낸다.
PRIVATE_PATTERNS = [
    (re.compile(r"[가-힣]{2,4}\s*(거점장|법인장|지사장|팀장|본부장|부장|차장|과장|대리|사원|"
                r"소장|점장|상무|전무|이사|사장|회장|님)\b"), "이름+직책"),
    (re.compile(r"\b01[016-9][-.\s]?\d{3,4}[-.\s]?\d{4}\b"), "휴대전화 번호"),
    (re.compile(r"\b1[3-9]\d{9}\b"), "중국 휴대전화 번호"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "이메일"),
    (re.compile(r"\d{1,3}\s*동\s*\d{3,4}\s*호"), "집 호수"),
    (re.compile(r"\b\d{1,3}-\d{3,4}\b\s*(?:高区|호)"), "집 호수"),
]

PURPOSE_HINTS = [
    ("business", ("출장", "거점장", "법인", "업무 미팅", "BUSINESS")),
    ("friends", ("친구", "Friends", "FRIENDS", "동창", "EMBA")),
    ("couple", ("아내", "부부", "COUPLE")),
    ("family", ("가족", "아들", "딸", "FAMILY")),
    ("pilgrimage", ("성지", "순례")),
]

DASH = re.compile(r"[–—―~∼〜]")
TAG = re.compile(r"<[^>]+>")
DROP = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def strip_notes(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def text_of(html: str) -> str:
    """태그를 걷어낸 본문. 판정은 전부 이 평문 위에서 한다."""
    return re.sub(r"\s+", " ", htmllib.unescape(TAG.sub(" ", DROP.sub(" ", html)))).strip()


def tag_text(html: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, re.S | re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(TAG.sub(" ", m.group(1)))).strip() if m else ""


# ── 기간 ──────────────────────────────────────────────────────────────────
def parse_range(title: str, body: str, stem: str) -> tuple[str, str]:
    """제목 → 본문 → 파일 이름 순으로 기간을 찾는다. 실패하면 빈 값."""
    for src in (title, body[:4000]):
        s = DASH.sub("-", src)
        m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*-\s*"
                      r"(?:(\d{4})[.\-/])?(\d{1,2})[.\-/](\d{1,2})", s)
        if m:
            y, mo, d, y2, mo2, d2 = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}", f"{y2 or y}-{int(mo2):02d}-{int(d2):02d}"
        m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일[^0-9]{0,12}-\s*"
                      r"(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일", s)
        if m:
            y, mo, d, y2, mo2, d2 = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}", f"{y2 or y}-{int(mo2):02d}-{int(d2):02d}"
        m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
        if m:
            y, mo, d = m.groups()
            one = f"{y}-{int(mo):02d}-{int(d):02d}"
            return one, one
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", stem)
    return (m.group(0), m.group(0)) if m else ("", "")


def days_between(start: str, end: str) -> int:
    try:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return 1
    return abs((b - a).days) + 1


def gap_days(a: str, b: str) -> int:
    """두 기간이 겹치면 0, 아니면 떨어진 날 수."""
    try:
        s1, e1 = date.fromisoformat(a[0]), date.fromisoformat(a[1])
        s2, e2 = date.fromisoformat(b[0][:10]), date.fromisoformat(b[1][:10])
    except ValueError:
        return 10**6
    if s1 <= e2 and s2 <= e1:
        return 0
    return min(abs((s2 - e1).days), abs((s1 - e2).days))


# ── 도시 ──────────────────────────────────────────────────────────────────
def needles(aliases: dict) -> list[tuple[str, str]]:
    """찾을 표기 → 정식 도시명. 긴 표기부터 본다(청두 시 < 청두 순서가 되지 않게)."""
    pairs: dict[str, str] = {}
    names: list[str] = []
    if (DATA / "places.json").exists():
        names = [p["name"] for p in load(DATA / "places.json")["places"]
                 if p.get("level") in ("city", "prefecture", "district", "territory")]
    else:  # 장소 마스터가 아직 없어도 좌표 원장만으로 돈다
        names = list(strip_notes(load(DATA / "place_coords.json")))
    for name in names:
        pairs[name] = name
        short = re.sub(r"\s*(시|구|현)$", "", name)
        if len(short) >= 2:
            pairs.setdefault(short, name)
    for raw, target in aliases.items():
        if target in names and len(raw) >= 2:
            pairs.setdefault(raw, target)
    return sorted(pairs.items(), key=lambda kv: -len(kv[0]))


def parse_cities(title: str, head: str, body: str, table: list[tuple[str, str]]) -> list[str]:
    """제목과 머리글에 나온 도시를 먼저 쓰고, 없으면 본문에서 두 번 이상 나온 도시를 쓴다."""
    def hits(src: str) -> list[str]:
        found: dict[str, int] = {}
        taken = ""
        for needle, city in table:
            at = src.find(needle)
            # 이미 잡은 더 긴 표기에 묻힌 것이면 건너뛴다 (청두 시 → 청두)
            if at < 0 or city in found or needle in taken:
                continue
            found[city] = at
            taken += needle + "|"
        return sorted(found, key=found.get)  # 글에 나온 차례대로

    cities = hits(f"{title} {head}")
    if cities:
        return cities
    counts = {c: body.count(n) for n, c in table if body.count(n) >= 2}
    return [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:4]


def first_paragraph(html: str) -> str:
    """소개 한 줄. 본문에서 처음 나오는 온전한 문단을 쓴다."""
    for m in re.finditer(r"<p\b[^>]*>(.*?)</p>", html, re.S | re.I):
        t = re.sub(r"\s+", " ", htmllib.unescape(TAG.sub("", m.group(1)))).strip()
        if len(t) < 30:
            continue
        if len(t) <= SUMMARY_MAX:
            return t
        cut = t[:SUMMARY_MAX]
        dot = max(cut.rfind("다. "), cut.rfind(". "))
        return (cut[:dot + 1] if dot > SUMMARY_MAX // 2 else cut.rstrip() + "…")
    return ""


# ── 일정표 한 장 읽기 ─────────────────────────────────────────────────────
def read_itinerary(path: Path, public: bool, table: list[tuple[str, str]]) -> dict:
    raw = path.read_text(encoding="utf-8")
    body = text_of(raw)
    doc_title = tag_text(raw, "title")
    h1 = tag_text(raw, "h1")
    parts = [p.strip() for p in doc_title.split("|") if p.strip()]
    title = parts[0] if parts else (h1 or path.stem)
    subtitle = parts[1] if len(parts) > 2 else ""
    start, end = parse_range(doc_title, body, path.stem)
    head = body[:600]

    lead = first_paragraph(raw)

    return {
        "source": path.name,
        "private": not public,
        "title": title,
        "subtitle": subtitle,
        "lead": lead,
        "start": start,
        "end": end,
        "days": days_between(start, end) if start else 1,
        "cities": parse_cities(doc_title + " " + h1, head, body, table),
        "purpose": next((p for p, keys in PURPOSE_HINTS
                         if any(k in body for k in keys)), "friends"),
        "scope": "domestic" if "인천" not in body and "공항" not in body else "overseas",
    }


def scan_text(body: str) -> list[str]:
    """평문에 개인정보로 보이는 것이 있는지 본다. 이름을 추측하지 않고 형태로만 본다."""
    return sorted({label for pat, label in PRIVATE_PATTERNS if pat.search(body)})


def scan_private(path: Path) -> list[str]:
    """공개 폴더에 개인정보로 보이는 것이 있는지 본다."""
    return scan_text(text_of(path.read_text(encoding="utf-8")))


# ── 여정에 붙이기 ─────────────────────────────────────────────────────────
def era_of(start: str, eras: list[dict]) -> str:
    ym = start[:7]
    for e in eras:
        if ym >= e["start"][:7] and (not e["end"] or ym <= e["end"][:7]):
            return e["id"]
    return eras[-1]["id"]


def match_trip(item: dict, trips: list[dict], aliases: dict) -> dict | None:
    """도시가 겹치고 날짜가 가까운 여정을 고른다. 없으면 None."""
    want = set(item["cities"])
    best, best_gap = None, MATCH_DAYS + 1
    for t in trips:
        if t.get("umbrella"):
            continue
        if t.get("itinerary") == item["source"]:
            return t  # 원장에 손으로 적어 둔 짝이 이긴다
        have = {aliases.get(c.strip(), c.strip()) for c in t.get("cities", [])}
        if not (want & have):
            continue
        gap = gap_days((item["start"], item["end"]), (str(t["start"]), str(t.get("end") or t["start"])))
        if gap < best_gap:
            best, best_gap = t, gap
    return best


def new_trip(item: dict, eras: list[dict], taken: set[str]) -> dict:
    tid = f"t-{item['start']}"
    n = 2
    while tid in taken:
        tid, n = f"t-{item['start']}-{n}", n + 1
    trip = {
        "id": tid,
        "title": item["title"],
        "start": item["start"],
        "end": item["end"],
        "era": era_of(item["start"], eras),
        "purpose": item["purpose"],
        "scope": item["scope"],
        "cities": item["cities"],
        "summary": item["lead"],
        "sources": ["itinerary"],
        "confidence": "high",
        "itinerary": item["source"],
        "planned": True,
    }
    if item["purpose"] != "business" and not item["private"]:
        trip["summaryPublic"] = item["lead"]
    return trip


BACK_LINK = """
<a href="../index.html" style="position:fixed;left:14px;top:14px;z-index:9999;
  padding:8px 14px;border-radius:999px;background:rgba(17,24,31,.82);color:#fff;
  font:600 13px/1 system-ui,-apple-system,'Malgun Gothic',sans-serif;text-decoration:none;
  backdrop-filter:blur(6px);box-shadow:0 4px 14px rgba(0,0,0,.25)">← 나의 여행 지도</a>
"""


def emit(path: Path, out: Path) -> None:
    """일정표를 배포 폴더로 옮기고 돌아가기 링크를 한 줄 넣는다."""
    raw = path.read_text(encoding="utf-8")
    if "나의 여행 지도</a>" not in raw:
        low = raw.lower()
        i = low.rfind("</body>")
        raw = raw[:i] + BACK_LINK + raw[i:] if i > 0 else raw + BACK_LINK
    out.write_text(raw, encoding="utf-8")


def build(check: bool = False) -> dict:
    trips_doc = load(TRIPS)
    aliases = strip_notes(load(DATA / "place_aliases.json"))
    table = needles(aliases)

    files = [(p, True) for p in sorted(SRC_DIR.glob("*.html"))]
    files += [(p, False) for p in sorted(PRIVATE_DIR.glob("*.html"))]

    leaks = {p.name: found for p, public in files if public
             for found in [scan_private(p)] if found}
    if leaks:
        lines = "\n".join(f"  {k} · {', '.join(v)}" for k, v in leaks.items())
        sys.exit("공개 폴더의 일정표에 개인정보로 보이는 것이 있다:\n" + lines +
                 f"\n{PRIVATE_DIR} 로 옮기면 개인 빌드에만 들어간다.")

    items = [read_itinerary(p, public, table) for p, public in files]
    items = [i for i in items if i["start"]] + \
            [i for i in items if not i["start"]]  # 기간을 못 읽은 것은 뒤로

    taken = {t["id"] for t in trips_doc["trips"]}
    added: list[str] = []
    changed = False
    manifest: list[dict] = []
    seen_files: set[str] = set()

    for item in items:
        if not item["start"]:
            print(f"  ! {item['source']} · 기간을 읽지 못해 건너뛴다")
            continue
        trip = match_trip(item, trips_doc["trips"], aliases)
        if trip is None:
            trip = new_trip(item, trips_doc["eras"], taken)
            trips_doc["trips"].append(trip)
            taken.add(trip["id"])
            added.append(trip["id"])
        if trip.get("itinerary") != item["source"]:
            trip["itinerary"] = item["source"]
            changed = True

        name = f"{trip['id']}.html"
        n = 2
        while name in seen_files:
            name, n = f"{trip['id']}-{n}.html", n + 1
        seen_files.add(name)
        manifest.append({
            "tripId": trip["id"], "file": name,
            **{k: item[k] for k in
               ("source", "title", "subtitle", "lead", "start", "end", "days",
                "cities", "private")},
        })

    if check:
        return {"itineraries": manifest, "added": added}

    if added or changed:
        # 순서는 건드리지 않는다 — 새 여정은 뒤에 붙이고 정렬은 앱이 한다.
        TRIPS.write_text(json.dumps(trips_doc, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    keep = {m["file"] for m in manifest}
    for old in OUT_DIR.glob("*.html"):
        if old.name not in keep:
            old.unlink()
    for m in manifest:
        src = (PRIVATE_DIR if m["private"] else SRC_DIR) / m["source"]
        emit(src, OUT_DIR / m["file"])

    MANIFEST.write_text(
        json.dumps({"_note": "빌드 산출물 · scripts/build_itineraries.py 가 만든다.",
                    "itineraries": manifest}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {"itineraries": manifest, "added": added}


def load_manifest() -> list[dict]:
    """빌드 산출물을 읽는다. 아직 없으면 빈 목록 — 앱은 그대로 돈다."""
    if not MANIFEST.exists():
        return []
    return load(MANIFEST)["itineraries"]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = build(check="--check" in sys.argv)
    for m in out["itineraries"]:
        mark = "개인" if m["private"] else "공개"
        print(f"  {m['tripId']} ← {m['source']} · {m['start']}~{m['end']} · "
              f"{' · '.join(m['cities']) or '도시 미상'} · {mark}")
    if out["added"]:
        print(f"여정으로 새로 적었다: {', '.join(out['added'])}")
    print(f"일정표 {len(out['itineraries'])} · {OUT_DIR}")


if __name__ == "__main__":
    main()
