"""일정표 에이전트 — 내용을 주면 일정표 HTML 한 장을 만들어 홈페이지에 붙인다.

충칭·웨이하이 일정표처럼 생긴 문서를, 손으로 쓴 원고나 블로그 글이나 구글 문서에서
자동으로 만든다. 만든 다음에는 `scripts/build_itineraries.py` 가 그것을 여정에 잇고,
여정을 누르면 그 문서가 열린다(PRD §15).

여섯 걸음으로 돈다. 걸음마다 무엇을 했는지 찍는다.

  1 수집   원고 · 블로그 · 구글 문서에서 글을 모은다
  2 구조화 글을 원고 스펙으로 바꾼다 (규칙. 줄글뿐이면 --api 로 Claude에게 맡긴다)
  3 검증   기간·도시를 장소 마스터에 맞추고, 개인정보가 보이면 개인 폴더로 보낸다
  4 렌더   HTML 한 장을 만든다 (외부 스크립트 없이 파일 하나로 돈다)
  5 연동   data/trip_html 에 넣고 빌드해서 여정에 붙인다
  6 배포   --push 면 커밋하고 올린다 (배포는 CI가 이어받는다)

사용법
  # 내가 쓴 원고로
  python scripts/itinerary_agent.py data/trip_source/대련.txt

  # 블로그 글 몇 개로 (제목의 'n일차'를 읽어 하루씩 나눈다)
  python scripts/itinerary_agent.py --blog 224309929105 224309946570 --trip t-2026-06-03

  # 구글 문서로 (웹에 게시된 문서 주소이거나, 내려받은 .txt/.html 파일)
  python scripts/itinerary_agent.py --gdoc https://docs.google.com/document/d/…/edit

  옵션
    --trip t-2026-06-03   기존 여정에 붙인다 (기간·도시·제목을 그 여정에서 가져온다)
    --title/--subtitle/--dates/--cities/--purpose/--cover   원고 값을 덮어쓴다
    --private             개인 일정표로 둔다 (저장소에 올라가지 않는다)
    --api                 줄글을 Claude가 하루 단위로 정리한다 (ANTHROPIC_API_KEY)
    --full                블로그 본문을 캐시 대신 전문으로 다시 받는다
    --no-build            HTML만 만들고 빌드는 하지 않는다
    --push -m "메시지"     빌드·테스트까지 마치고 커밋·푸시한다

원고 스펙 (사람이 읽고 고치는 형식. 에이전트도 이 형식으로 적는다)

    제목: 충칭 여행 — 아들과 함께한 4박 5일
    부제: 천생삼교와 츠치커우, 그리고 판다
    기간: 2026-06-03 ~ 2026-06-08
    도시: 충칭
    목적: 가족여행
    여정: t-2026-06-03
    공개: 예
    소개: 한 문단. 여러 줄로 써도 된다.

    ## DAY 1 · 6/3 — 도착
    14:00 | 인천공항 출발 | 메모는 세 번째 칸에
    - 시각이 없는 항목은 이렇게
    문단은 그냥 줄로 적는다.

    ## 메모
    - 준비물

    링크: 블로그 원문 | https://blog.naver.com/joekang/224309929105
"""

from __future__ import annotations

import html as htmllib
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_itineraries as bi  # noqa: E402  (도시 사전·개인정보 검사를 같이 쓴다)
import fetch_blog_bodies as fb  # noqa: E402  (블로그 본문 로더)

ROOT = Path(__file__).resolve().parent.parent
DATA = Path("data")
SOURCE_DIR = DATA / "trip_source"      # 원고 보관함 (.gitignore — 개인 메모가 섞인다)
BLOG_URL = "https://blog.naver.com/joekang/{}"

PURPOSES = {"출장": "business", "주재": "expat", "가족여행": "family",
            "부부여행": "couple", "친구여행": "friends", "성지순례": "pilgrimage",
            "혼자": "solo"}
DAY_RE = re.compile(r"(?:DAY\s*|제?\s*)(\d+)\s*일?차?", re.I)
TIME_RE = re.compile(r"^(\d{1,2}:\d{2}(?:\s*[-–~]\s*\d{1,2}:\d{2})?|\d{1,2}시(?:\s*\d{1,2}분)?)"
                     r"\s*[|·]\s*(.+)$")
SENT_RE = re.compile(r"(?<=[.!?다요])\s+")


def say(step: int, what: str) -> None:
    print(f"[{step}/6] {what}")


def esc(s: str) -> str:
    return htmllib.escape(str(s or ""), quote=True)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── 1. 수집 ───────────────────────────────────────────────────────────────
def from_blog(log_nos: list[str], full: bool) -> list[dict]:
    """블로그 글 → 글 조각. 제목·날짜는 목록에서, 본문은 캐시(또는 전문)에서."""
    posts = {p["logNo"]: p for p in fb.load_posts()}
    cache_path = DATA / "blog_bodies.json"
    cache = load(cache_path) if cache_path.exists() else {}
    out = []
    for no in log_nos:
        no = re.sub(r"\D", "", no)  # 주소를 통째로 줘도 된다
        post = posts.get(no, {})
        body = "" if full else cache.get(no, "")
        if not body:
            body = fb.fetch_body(no)
            cache[no] = body[:1500]
        out.append({
            "kind": "blog",
            "title": htmllib.unescape(post.get("title", f"블로그 {no}")),
            "date": norm_date(post.get("date", "")),
            "url": BLOG_URL.format(no),
            "text": body,
        })
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out


def from_gdoc(target: str) -> list[dict]:
    """구글 문서 → 글 조각. 주소면 텍스트로 내보내 받고, 파일이면 그대로 읽는다."""
    path = Path(target)
    if path.exists():
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = bi.text_of(raw) if path.suffix.lower() in (".html", ".htm") else raw
        return [{"kind": "gdoc", "title": path.stem, "date": "", "url": "", "text": text}]

    m = re.search(r"/document/d/([\w-]+)", target)
    if not m:
        sys.exit("구글 문서 주소나 내려받은 파일 경로를 달라")
    import urllib.request
    url = f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    try:
        with urllib.request.urlopen(url, timeout=25) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        sys.exit(f"문서를 못 받았다({e}). 문서를 '웹에 게시'하거나, "
                 "파일 → 다운로드 → 일반 텍스트(.txt) 로 받아 그 경로를 달라")
    return [{"kind": "gdoc", "title": text.strip().split("\n")[0][:80],
             "date": "", "url": target, "text": text}]


def norm_date(raw: str) -> str:
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", str(raw))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


# ── 2. 구조화 ─────────────────────────────────────────────────────────────
def paragraphs(text: str, per: int = 3) -> list[str]:
    """줄글을 문단으로 끊는다. 블로그 본문은 줄바꿈이 없어 문장 수로 센다."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sents = [s.strip() for s in SENT_RE.split(text) if s.strip()]
    return [" ".join(sents[i:i + per]) for i in range(0, len(sents), per)]


def clean_title(title: str) -> str:
    """글 제목에서 말머리와 'n일차'를 걷어낸다. [충칭 여행기] 0일차: 첫걸음 → 첫걸음"""
    t = re.sub(r"^\s*[\[【(][^\]】)]*[\]】)]\s*", "", title)
    t = DAY_RE.sub("", t, count=1)
    t = re.sub(r"#\S+", "", t)
    return t.strip(" ,.:·-—…") or title.strip()


def spec_from_sources(sources: list[dict], meta: dict) -> str:
    """글 조각들을 원고 스펙으로 옮긴다. 제목에 'n일차'가 있으면 하루씩 나눈다."""
    days = [(int(m.group(1)), s) for s in sources
            if (m := DAY_RE.search(s["title"]))]
    lines = [f"{k}: {v}" for k, v in meta.items() if v]
    by_day = len(days) == len(sources) and len(days) > 1
    ordered = sorted(days, key=lambda d: d[0]) if by_day \
        else [(0, s) for s in sources]
    first = min((n for n, _ in ordered), default=0)
    for n, s in ordered:
        head = clean_title(s["title"])
        lines.append(f"\n## DAY {n - first + 1} — {head}" if by_day else f"\n## {head}")
        lines += paragraphs(s["text"])
        if s["url"]:
            lines.append(f"링크: {head[:28]} | {s['url']}")
    return "\n".join(lines) + "\n"


def spec_to_text(spec: dict) -> str:
    """검증까지 마친 스펙을 다시 원고로 적는다. 이 파일만 고쳐 다시 돌릴 수 있다."""
    i = spec["info"]
    head = {"제목": i["title"], "부제": i["subtitle"],
            "기간": f"{i['start']} ~ {i['end']}", "도시": ", ".join(i["cities"]),
            "목적": i["purpose"], "여정": (spec["trip"] or {}).get("id", ""),
            "표지": i["cover"], "공개": "아니오" if i["private"] else "예",
            "소개": i["intro"]}
    lines = [f"{k}: {v}" for k, v in head.items() if v]
    for s in spec["sections"]:
        lines.append(f"\n## {s['title']}")
        for it in s["items"]:
            if it["time"]:
                lines.append(" | ".join(filter(None, [it["time"], it["what"],
                                                      it["note"]])))
            elif it["what"]:
                lines.append("- " + " | ".join(filter(None, [it["what"], it["note"]])))
            else:
                lines.append(it["note"])
    for l in spec["links"]:
        lines.append(f"링크: {l['label']} | {l['url']}")
    return "\n".join(lines) + "\n"


PROMPT = """다음은 여행 기록이다. 이것을 아래 '원고 스펙' 형식으로만 다시 적어라.
없는 사실을 지어내지 마라 — 원문에 있는 것만 옮긴다. 설명 없이 원고만 출력한다.

원고 스펙
제목: (한 줄)
부제: (한 줄, 없으면 생략)
기간: YYYY-MM-DD ~ YYYY-MM-DD
도시: 쉼표로 구분
소개: 한 문단

## DAY 1 · 날짜 — 그날의 한 줄
09:00 | 무엇을 | 메모
- 시각을 모르는 항목

원문:
"""


def ask_api(text: str, model: str = "claude-sonnet-5") -> str:
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic 이 필요하다")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(model=model, max_tokens=4000,
                                 messages=[{"role": "user",
                                            "content": PROMPT + text[:60000]}])
    out = msg.content[0].text.strip()
    return re.sub(r"^```(\w+)?|```$", "", out, flags=re.M).strip() + "\n"


# ── 원고 스펙 읽기 ────────────────────────────────────────────────────────
def parse_spec(text: str) -> dict:
    spec: dict = {"meta": {}, "links": [], "sections": []}
    section: dict | None = None
    key = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            key = None
            continue
        head = re.match(r"^##\s*(.+)$", line.strip())
        if head:
            title = head.group(1).strip()
            m = DAY_RE.match(title)
            section = {"day": int(m.group(1)) if m else None,
                       "title": title, "items": []}
            spec["sections"].append(section)
            key = None
            continue
        kv = re.match(r"^([가-힣A-Za-z]{2,6})\s*[:：]\s*(.*)$", line.strip())
        if kv and (section is None or kv.group(1) == "링크"):
            key, value = kv.group(1), kv.group(2).strip()
            if key == "링크":
                label, _, url = value.partition("|")
                spec["links"].append({"label": label.strip() or "원문",
                                      "url": url.strip()})
                key = None
            else:
                spec["meta"][key] = value
            continue
        if section is None:
            if key:  # 여러 줄짜리 값(소개 등)은 이어 붙인다
                spec["meta"][key] = (spec["meta"][key] + " " + line.strip()).strip()
            continue
        body = line.strip()
        t = TIME_RE.match(body)
        if t:
            rest = [p.strip() for p in t.group(2).split("|")]
            section["items"].append({"time": t.group(1), "what": rest[0],
                                     "note": " · ".join(rest[1:])})
        elif body.startswith(("-", "*", "•")):
            rest = [p.strip() for p in body.lstrip("-*• ").split("|")]
            section["items"].append({"time": "", "what": rest[0],
                                     "note": " · ".join(rest[1:])})
        else:
            section["items"].append({"time": "", "what": "", "note": body})
    return spec


# ── 3. 검증 ───────────────────────────────────────────────────────────────
WEEKDAY = "월화수목금토일"


def day_label(start: str, n: int) -> str:
    """출발일에서 n번째 날의 날짜. 6월 3일 (수)"""
    try:
        d = date.fromisoformat(start) + timedelta(days=n - 1)
    except ValueError:
        return ""
    return f"{d.month}월 {d.day}일 ({WEEKDAY[d.weekday()]})"
def enrich(spec: dict, args: dict) -> dict:
    meta = spec["meta"]
    trips_doc = load(DATA / "trips.json")
    aliases = bi.strip_notes(load(DATA / "place_aliases.json"))
    table = bi.needles(aliases)

    trip_id = args.get("trip") or meta.get("여정")
    trip = next((t for t in trips_doc["trips"] if t["id"] == trip_id), None)
    if trip_id and not trip:
        sys.exit(f"{trip_id} 는 data/trips.json 에 없다")
    if trip:  # 기존 여정에 붙이면 사실관계는 원장이 이긴다
        meta.setdefault("제목", trip.get("title", ""))
        meta["기간"] = f"{trip['start']} ~ {trip.get('end') or trip['start']}"
        meta.setdefault("도시", ", ".join(trip.get("cities", [])))
        meta.setdefault("목적", next((k for k, v in PURPOSES.items()
                                      if v == trip.get("purpose")), ""))
    for key, val in args.items():
        if val and key in ("제목", "부제", "기간", "도시", "목적", "표지"):
            meta[key] = val

    body = " ".join(i["what"] + " " + i["note"]
                    for s in spec["sections"] for i in s["items"])
    start, end = bi.parse_range(meta.get("기간", ""), body, "")
    if not start:
        sys.exit("기간을 못 읽었다 — 원고에 '기간: 2026-06-03 ~ 2026-06-08' 을 적어라")

    cities = [c.strip() for c in re.split(r"[,·]", meta.get("도시", "")) if c.strip()]
    cities = [aliases.get(c, c) for c in cities]
    if not cities:
        cities = bi.parse_cities(meta.get("제목", ""), body[:600], body, table)
    known = {p["name"] for p in load(DATA / "places.json")["places"]}
    unknown = [c for c in cities if c not in known]

    dests = {d["place"]: d for d in load(DATA / "destinations.json")["destinations"]} \
        if (DATA / "destinations.json").exists() else {}
    dest = next((dests[c] for c in cities if c in dests), None)

    # DAY 꼭지에는 그날의 실제 날짜를 붙인다 — 글을 올린 날이 아니라 여행한 날이다.
    for s in spec["sections"]:
        if s["day"] and not re.search(r"\d+월\s*\d+일", s["title"]):
            label = day_label(start, s["day"])
            body = s["title"].partition("—")[2].strip() or s["title"]
            s["title"] = f"DAY {s['day']} · {label} — {body}" if label else s["title"]

    spec["trip"] = trip
    spec["info"] = {
        "title": meta.get("제목") or (trip or {}).get("title") or "여행 일정",
        "subtitle": meta.get("부제", ""),
        "intro": meta.get("소개") or (trip or {}).get("summary", ""),
        "start": start, "end": end,
        "days": bi.days_between(start, end),
        "cities": cities, "unknown": unknown,
        "purpose": meta.get("목적", ""),
        "cover": meta.get("표지") or (dest or {}).get("cover", ""),
        "dest": dest,
        "private": args.get("private") or meta.get("공개", "").startswith("아니"),
    }
    return spec


# ── 4. 렌더 ───────────────────────────────────────────────────────────────
PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | {subtitle} | {period_dot}</title>
<meta name="description" content="{intro_short}">
<style>
:root{{
  --bg:#f7f5f0; --panel:#fffdf8; --line:#e2dcd0; --ink:#1f1c17; --dim:#7b7264;
  --accent:#9a6a3a; --accent-ink:#fff8ee;
  --shadow:0 1px 2px rgba(31,28,23,.06),0 10px 30px rgba(31,28,23,.07);
  --serif:Georgia,"Noto Serif KR","Apple SD Gothic Neo",serif;
  --sans:-apple-system,"Segoe UI","Noto Sans KR","Malgun Gothic",sans-serif;
}}
@media (prefers-color-scheme:dark){{:root{{
  --bg:#16150f; --panel:#201e17; --line:#38342a; --ink:#ece7dc; --dim:#9a9184;
  --accent:#d8b478; --accent-ink:#1b1810;
  --shadow:0 1px 3px rgba(0,0,0,.5),0 8px 24px rgba(0,0,0,.4);
}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  line-height:1.7;-webkit-text-size-adjust:100%}}
a{{color:var(--accent)}}
.back{{position:fixed;left:14px;top:14px;z-index:9;padding:7px 13px;border-radius:999px;
  background:rgba(20,18,14,.72);color:#fff;font-size:12.5px;font-weight:600;
  text-decoration:none;backdrop-filter:blur(6px)}}
.hero{{position:relative;min-height:62vh;display:flex;align-items:flex-end;
  padding:40px max(6vw,20px);color:#fff;background:#231f19}}
.hero img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.62}}
.hero .veil{{position:absolute;inset:0;background:linear-gradient(180deg,
  rgba(16,13,9,.35),rgba(16,13,9,.88))}}
.hero .box{{position:relative;max-width:900px}}
.kicker{{letter-spacing:.18em;font-size:11.5px;font-weight:700;color:#e4c79a;
  text-transform:uppercase}}
h1{{font:600 clamp(26px,5.2vw,50px)/1.18 var(--serif);margin:.35em 0 .2em;
  letter-spacing:-.02em}}
.sub{{font-size:clamp(14px,2.2vw,18px);color:#ece5d8;margin:0}}
.badges{{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}}
.badge{{padding:5px 12px;border-radius:999px;font-size:12px;
  border:1px solid rgba(255,255,255,.3);background:rgba(255,255,255,.08)}}
.credit{{position:absolute;right:12px;bottom:8px;font-size:10.5px;color:#d9d2c6;opacity:.85}}
.credit a{{color:#fff}}
main{{width:min(860px,calc(100% - 36px));margin:0 auto;padding:38px 0 70px}}
.lead{{font:400 clamp(15px,2.3vw,18px)/1.75 var(--serif);color:var(--ink);
  margin:0 0 26px}}
section{{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:22px 24px;margin:0 0 16px;box-shadow:var(--shadow)}}
section h2{{font:600 19px/1.35 var(--serif);margin:0 0 4px}}
section .when{{font-size:12px;color:var(--dim);letter-spacing:.04em;
  text-transform:uppercase;font-weight:700}}
.para{{margin:12px 0 0;font-size:14.5px}}
.para+.para{{margin-top:10px}}
.rows{{margin-top:14px;display:grid;gap:2px}}
.row{{display:grid;grid-template-columns:78px 1fr;gap:14px;padding:9px 0;
  border-top:1px solid var(--line)}}
.row:first-child{{border-top:0}}
.row time{{font-size:12.5px;color:var(--accent);font-weight:700;padding-top:2px;
  font-variant-numeric:tabular-nums}}
.row b{{display:block;font-size:14.5px;font-weight:600}}
.row p{{margin:2px 0 0;font-size:13.5px;color:var(--dim)}}

.links{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}
.links a{{font-size:12.5px;padding:5px 12px;border-radius:999px;
  border:1px solid var(--line);text-decoration:none}}
footer{{color:var(--dim);font-size:12px;text-align:center;padding:10px 0 0}}
footer a{{color:var(--dim)}}
@media(max-width:560px){{.row{{grid-template-columns:62px 1fr;gap:10px}}}}
</style>
</head>
<body>
<a class="back" href="../index.html">← 나의 여행 지도</a>
<header class="hero">
  {cover}
  <div class="veil"></div>
  <div class="box">
    <div class="kicker">{kicker}</div>
    <h1>{title}</h1>
    {subtitle_html}
    <div class="badges">{badges}</div>
  </div>
  {credit}
</header>
<main>
  {intro_html}
  {sections}
  {links_html}
  <footer>{footer}</footer>
</main>
</body>
</html>
"""


def render(spec: dict) -> str:
    info = spec["info"]
    period = f"{info['start']} ~ {info['end']}" if info["start"] != info["end"] \
        else info["start"]
    dot = (info["start"].replace("-", ".") + "–" +
           info["end"][5:].replace("-", ".")) if info["start"] != info["end"] \
        else info["start"].replace("-", ".")

    badges = [f"{info['days']}일", *info["cities"]]
    if info["purpose"]:
        badges.append(info["purpose"])
    badge_html = "".join(f'<span class="badge">{esc(b)}</span>' for b in badges)

    blocks = []
    for s in spec["sections"]:
        # 시각이 붙은 항목은 타임라인으로, 줄글은 문단 그대로 — 둘을 섞어 쓸 수 있다.
        parts, rows = [], []

        def flush():
            if rows:
                parts.append(f'<div class="rows">{"".join(rows)}</div>')
                rows.clear()

        for it in s["items"]:
            if not it["what"]:
                flush()
                parts.append(f'<p class="para">{esc(it["note"])}</p>')
                continue
            note = f'<p>{esc(it["note"])}</p>' if it["note"] else ""
            rows.append(f'<div class="row"><time>{esc(it["time"])}</time>'
                        f'<div><b>{esc(it["what"])}</b>{note}</div></div>')
        flush()
        when, _, rest = s["title"].partition("—")
        head, body = (when.strip(), rest.strip()) if rest else ("", s["title"].strip())
        when_html = f'<div class="when">{esc(head)}</div>' if head else ""
        blocks.append(f'<section>{when_html}<h2>{esc(body)}</h2>'
                      f'{"".join(parts)}</section>')

    links = "".join(f'<a href="{esc(l["url"])}" target="_blank" rel="noopener">'
                    f'{esc(l["label"])} →</a>' for l in spec["links"] if l["url"])
    dest = info.get("dest")
    if dest:
        links += (f'<a href="{esc(dest["url"])}" target="_blank" rel="noopener nofollow">'
                  f'Trip.com {esc(dest["name"])} 가이드 →</a>')

    cover = (f'<img src="{esc(info["cover"])}" alt="{esc(info["cities"][0] if info["cities"] else "")} 사진">'
             if info["cover"] else "")
    credit = (f'<div class="credit">표지 · <a href="{esc(dest["url"])}" target="_blank"'
              f' rel="noopener nofollow">© Trip.com</a></div>'
              if dest and info["cover"] == dest.get("cover") else "")

    return PAGE.format(
        title=esc(info["title"]),
        subtitle=esc(info["subtitle"] or " · ".join(info["cities"])),
        subtitle_html=f'<p class="sub">{esc(info["subtitle"])}</p>'
                      if info["subtitle"] else "",
        period_dot=dot,
        kicker=esc(" · ".join(filter(None, [period, *info["cities"]]))),
        intro_short=esc(info["intro"][:150]),
        intro_html=f'<p class="lead">{esc(info["intro"])}</p>' if info["intro"] else "",
        cover=cover, credit=credit, badges=badge_html,
        sections="".join(blocks),
        links_html=f'<div class="links">{links}</div>' if links else "",
        footer=f'{date.today().isoformat()} · 「나의 여행 지도」 일정표 · '
               f'<a href="../index.html">아카이브로</a>',
    )


# ── 5·6. 연동과 배포 ──────────────────────────────────────────────────────
def run(args: list[str]) -> None:
    print(f"    → {' '.join(args)}")
    r = subprocess.run([sys.executable, *args], cwd=ROOT)
    if r.returncode:
        sys.exit(r.returncode)


def bind(trip_id: str, filename: str) -> None:
    """원장에 짝을 못 박는다. 규칙 매칭보다 이것이 앞선다(build_itineraries)."""
    path = DATA / "trips.json"
    doc = load(path)
    for t in doc["trips"]:
        if t["id"] == trip_id and t.get("itinerary") != filename:
            t["itinerary"] = filename
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            return


def flag(name: str) -> bool:
    return name in sys.argv


def opt(name: str, default: str = "") -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def opts(name: str) -> list[str]:
    """--blog a b c 처럼 값을 여러 개 받는다."""
    if name not in sys.argv:
        return []
    out = []
    for v in sys.argv[sys.argv.index(name) + 1:]:
        if v.startswith("--"):
            break
        out.append(v)
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    blogs, gdoc = opts("--blog"), opt("--gdoc")
    files = [a for a in sys.argv[1:] if not a.startswith("--")
             and Path(a).suffix in (".txt", ".md") and Path(a).exists()]

    # 1. 수집
    if blogs:
        sources = from_blog(blogs, flag("--full"))
    elif gdoc:
        sources = from_gdoc(gdoc)
    elif files:
        sources = []
    elif not sys.stdin.isatty():
        sources = [{"kind": "stdin", "title": "", "date": "", "url": "",
                    "text": sys.stdin.read()}]
    else:
        sys.exit(__doc__.split("사용법")[1].strip())
    say(1, f"수집 · {'원고 ' + files[0] if files else f'{len(sources)}조각'}")

    # 2. 구조화
    meta = {k: opt(f"--{en}") for k, en in
            (("제목", "title"), ("부제", "subtitle"), ("기간", "dates"),
             ("도시", "cities"), ("목적", "purpose"), ("여정", "trip"))}
    if files:
        spec_text = Path(files[0]).read_text(encoding="utf-8")
        origin = Path(files[0]).name
    else:
        joined = "\n\n".join(s["text"] for s in sources)
        spec_text = (ask_api(joined) if flag("--api")
                     else spec_from_sources(sources, meta))
        origin = (sources[0]["url"] or sources[0]["title"] or "원고")
    spec = parse_spec(spec_text)
    say(2, f"구조화 · 꼭지 {len(spec['sections'])} · "
           f"{'Claude' if flag('--api') else '규칙'} · 출처 {origin}")

    # 3. 검증
    spec = enrich(spec, {
        "trip": opt("--trip"), "private": flag("--private"),
        "제목": opt("--title"), "부제": opt("--subtitle"), "기간": opt("--dates"),
        "도시": opt("--cities"), "목적": opt("--purpose"), "표지": opt("--cover"),
    })
    info = spec["info"]
    html_text = render(spec)
    found = bi.scan_text(bi.text_of(html_text))
    if found and not info["private"]:
        info["private"] = True
        print(f"    ! 개인정보로 보이는 것({', '.join(found)})이 있어 개인 일정표로 둔다")
    if info["unknown"]:
        print(f"    ! 장소 마스터에 없는 도시: {', '.join(info['unknown'])} "
              f"— data/place_coords.json 에 좌표를 넣어라")
    say(3, f"검증 · {info['start']}~{info['end']} · {info['days']}일 · "
           f"{' · '.join(info['cities']) or '도시 미상'} · "
           f"{'개인' if info['private'] else '공개'}")

    # 4. 렌더
    out_dir = bi.PRIVATE_DIR if info["private"] else bi.SRC_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{info['start']}_{info['cities'][0] if info['cities'] else 'trip'}.html"
    out = out_dir / name
    stale = (bi.SRC_DIR if info["private"] else bi.PRIVATE_DIR) / name
    if stale.exists():  # 공개↔개인을 바꿔 다시 만들면 옛 자리의 것은 지운다
        stale.unlink()
        print(f"    · 옛 {stale} 를 지웠다")
    out.write_text(html_text, encoding="utf-8")
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    (SOURCE_DIR / (out.stem + ".txt")).write_text(spec_to_text(spec), encoding="utf-8")
    say(4, f"렌더 · {out} · {out.stat().st_size / 1024:,.0f}KB "
           f"(원고는 {SOURCE_DIR / (out.stem + '.txt')})")

    # 5. 연동
    if spec["trip"]:
        bind(spec["trip"]["id"], out.name)
    if flag("--no-build"):
        say(5, "연동 · 건너뛴다(--no-build) · python scripts/build_all.py 로 붙는다")
    else:
        run(["scripts/build_all.py", *(["--public"] if flag("--push") else [])])
        item = next((m for m in bi.load_manifest() if m["source"] == out.name), None)
        say(5, f"연동 · {item['tripId'] if item else '여정 못 찾음'} 에 붙었다")

    # 6. 배포
    if flag("--push"):
        message = opt("-m") or f"일정표 · {info['title']}"
        run(["scripts/release.py", "-m", message])
        say(6, "배포 · 올렸다. 잠시 뒤 공개본에 반영된다")
    else:
        say(6, '배포 · 건너뛴다. 올리려면 --push -m "메시지"')


if __name__ == "__main__":
    main()
