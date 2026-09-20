"""블로그 글 본문을 수집한다 (PRD §3-1, Phase 2의 입력).

data/blog_cat*.json 의 글 목록을 모아 본문 앞부분만 받는다.
판정과 도시·날짜 추출에는 앞부분이면 충분하고, 전문을 받으면 파일이 너무 커진다.

사용법: python scripts/fetch_blog_bodies.py [--limit N] [--chars N]
결과: data/blog_bodies.json  (이어받기 — 이미 받은 글은 건너뛴다)

본문 파서는 『나의 서재』 scripts/fetch_blog_bodies.py 에서 가져왔다.
최신 글은 SmartEditor ONE, 2008년 전후 글은 구형 에디터라 컨테이너가 다르다.
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BLOG_ID = "joekang"
DATA = Path("data")
OUT = DATA / "blog_bodies.json"
SOURCES = {
    "blog_cat21_travel.json": 21,
    "blog_cat17_global.json": 17,
    "blog_cat1_essay.json": 1,
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
    "Referer": "https://blog.naver.com/",
}
SCRIPT_RE = re.compile(r"<(script|style).*?</\1>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
CONTAINERS = [
    r'<div[^>]*class="[^"]*se-main-container',
    r'<div[^>]*id="postViewArea',
    r'<div[^>]*class="[^"]*post_ct',
    r'<div[^>]*class="[^"]*se_component_wrap',
]


def extract_text(raw: str) -> str:
    # 스크립트를 먼저 걷어내지 않으면 스크립트 안의 셀렉터 문자열에 걸린다.
    raw = SCRIPT_RE.sub(" ", raw)
    seg = raw
    for pattern in CONTAINERS:
        m = re.search(pattern, raw)
        if m:
            seg = raw[m.start() : m.start() + 120000]
            break
    seg = TAG_RE.sub(" ", seg)
    seg = html.unescape(seg).replace("​", " ")
    return re.sub(r"\s+", " ", seg).strip()


def load_posts() -> list[dict]:
    posts, seen = [], set()
    for fname, cat in SOURCES.items():
        path = DATA / fname
        if not path.exists():
            continue
        for p in json.loads(path.read_text(encoding="utf-8")):
            if p["logNo"] in seen:
                continue
            seen.add(p["logNo"])
            # 목록 API가 제목을 HTML 엔티티로 준다 (&#39; 등)
            p["title"] = html.unescape(p["title"])
            posts.append({**p, "cat": cat})
    return posts


def fetch_body(log_no: str) -> str:
    url = f"https://m.blog.naver.com/{BLOG_ID}/{log_no}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return extract_text(resp.read().decode("utf-8", errors="replace"))


def arg(name: str, default: int) -> int:
    return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    limit = arg("--limit", 10**9)
    chars = arg("--chars", 1500)

    posts = load_posts()
    bodies = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [p for p in posts if p["logNo"] not in bodies][:limit]
    print(f"글 {len(posts)} · 받을 것 {len(todo)}")

    for i, p in enumerate(todo, 1):
        try:
            bodies[p["logNo"]] = fetch_body(p["logNo"])[:chars]
        except Exception as e:  # 한 건 실패로 전체를 멈추지 않는다
            bodies[p["logNo"]] = ""
            print(f"  실패 {p['logNo']}: {e}")
        if i % 50 == 0 or i == len(todo):
            OUT.write_text(json.dumps(bodies, ensure_ascii=False), encoding="utf-8")
            print(f"  {i}/{len(todo)}")
        time.sleep(0.25)

    OUT.write_text(json.dumps(bodies, ensure_ascii=False), encoding="utf-8")
    empty = sum(1 for v in bodies.values() if not v)
    print(f"{OUT}: {len(bodies)}건 · 본문 없음 {empty} · {OUT.stat().st_size / 1024:,.0f}KB")


if __name__ == "__main__":
    main()
