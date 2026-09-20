"""블로그 글을 여정 후보로 바꾼다 (PRD Phase 2).

PRD §3-1의 결론: 카테고리 번호로는 여행 글을 못 거른다. cat 17에는 2006년 현장
기록과 2026년 중국 시사 칼럼이 같이 있고, cat 21에는 러닝·영화·맛집이 섞여 있다.
그래서 두 단계로 거른다.

  1단계 (규칙, 공짜)  — 확실한 것만 자동으로 가른다. 애매하면 손대지 않는다.
  2단계 (LLM)        — 1단계가 못 가른 것만 모델에 묻는다.

자동 등록은 하지 않는다. 결과는 언제나 '후보'이고 사람이 승인한다(PRD §1).

사용법
  python scripts/classify_posts.py                     # 1단계만. 큐를 파일로 뽑는다
  python scripts/classify_posts.py --api               # 2단계를 Claude API로 (ANTHROPIC_API_KEY)
  python scripts/classify_posts.py --apply data/llm_verdicts.json
                                                       # 밖에서 판정한 결과를 물려 넣는다
출력
  data/import_candidates.json  — 승인 대기 후보
  data/llm_queue.json          — 2단계로 넘길 글 (--api 를 안 쓸 때)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

DATA = Path("data")
QUEUE = DATA / "llm_queue.json"
OUT = DATA / "import_candidates.json"

sys.path.insert(0, str(Path(__file__).parent))
import fetch_blog_bodies as fb  # noqa: E402  (글 목록 로더를 같이 쓴다)

# ── 1단계 규칙 ────────────────────────────────────────────────────────────────
# 여행 글이 아닌 것이 거의 확실한 신호. cat 17이 시사 칼럼으로 변한 뒤의 글들이 여기 걸린다.
NOT_TRAVEL = [
    r"영화\s*(리뷰|감상)", r"감상평", r"#영화", r"북리뷰", r"독서노트", r"서평",
    r"별세", r"부고", r"추모",
    r"(로보택시|스마트시티|드론\s*배송|반도체|챗GPT|ChatGPT|AI\s*(로봇|기술)|인구\s*통계)",
    r"(대통령|정상회의|우익|관세|금리|환율|증시|ETF|코스피|나스닥)",
    r"베스트셀러", r"트렌드", r"블챌", r"주간일기",
    r"^\[?(오늘의|매일)", r"기도(회|문)", r"설교", r"큐티",
]
# 여행 글이 거의 확실한 신호.
TRAVEL = [
    r"\[[^\]]*여행[^\]]*\]", r"여행\s*(기|후기|일지|\d+일차)", r"자유여행", r"한달살기",
    r"출장", r"기행", r"답사", r"성지순례", r"비전트립",
    r"#[^\s#]*여행", r"\d+박\s*\d+일",
]
# 장소 신호 — 도시 이름이 제목에 있으면 여행일 가능성이 올라간다(단독으로는 부족).
PLACE_HINT = None  # build 시 place_aliases 에서 만든다


def compile_all(pats: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in pats]


NOT_RE = compile_all(NOT_TRAVEL)
TRAVEL_RE = compile_all(TRAVEL)


# 흔한 우리말과 겹치는 지명. 접미사 없이 홀로 나오면 지명으로 보지 않는다.
#   지난(济南) ↔ "지난 주", 다리(大理) ↔ "다리를 건너", 대리(代理), 상주(常州) ↔ "상주하다"
AMBIGUOUS = {"지난", "다리", "대리", "상주", "영주", "의성", "고성", "남원", "포산"}

ALIASES: dict[str, str] = {}


def place_pattern() -> re.Pattern:
    """지명 정규식. 좌표 원장과 별칭 사전을 합쳐 만든다."""
    global ALIASES
    aliases = json.loads((DATA / "place_aliases.json").read_text(encoding="utf-8"))
    coords = json.loads((DATA / "place_coords.json").read_text(encoding="utf-8"))
    canon = {k for k in coords if not k.startswith("_")}
    names = {k for k in aliases if not k.startswith("_")} | canon
    # '시', '현' 접미사를 뗀 형태도 잡는다 (제목에는 '웨이하이'라고만 쓴다)
    short = {}
    for n in list(names):
        s = re.sub(r"\s*(시|현|구|지구|자치주|조선족 자치주|다이족 자치주)$", "", n).strip()
        if len(s) >= 2 and s not in AMBIGUOUS:
            short[s] = n
    ALIASES = {k: v for k, v in aliases.items() if not k.startswith("_")}
    for s, full in short.items():
        ALIASES.setdefault(s, ALIASES.get(full, full))
    for n in canon:
        ALIASES.setdefault(n, n)
    names = {n for n in (names | set(short)) if len(n) >= 2 and n not in AMBIGUOUS}
    return re.compile("|".join(sorted(map(re.escape, names), key=len, reverse=True)))


# 본문에 나오면 '다녀온 기록'일 가능성을 올리는 말. 1인칭 이동 흔적이다.
BODY_GO = [
    r"도착(했|하니|해서|한)", r"출발(했|하니|해서)", r"묵(었|은)", r"숙소", r"호텔",
    r"공항", r"비행기", r"기차|고속철|KTX", r"렌터카", r"가이드",
    r"일정", r"\d+일차", r"첫날|둘째\s*날|셋째\s*날",
    r"여행", r"출장", r"다녀왔", r"둘러(봤|보았)", r"구경(했|하고)",
]
# 본문에 나오면 '다녀온 기록'이 아닐 가능성을 올리는 말. 칼럼·묵상·서평의 말투다.
BODY_NO = [
    r"이 책", r"저자는", r"독자", r"출판", r"성경", r"말씀", r"주님", r"기도",
    r"보고서", r"전망", r"분석에 따르면", r"통계", r"전문가들은", r"시사점",
    r"우리는 .{0,12}해야", r"라고 생각한다", r"칼럼",
]
BODY_GO_RE = compile_all(BODY_GO)
BODY_NO_RE = compile_all(BODY_NO)


def stage1(post: dict, body: str) -> tuple[str, str]:
    """('travel'|'no'|'ask', 근거) 를 돌려준다.

    제목의 확실한 신호로 먼저 가르고, 남은 것은 본문 신호로 점수를 매긴다.
    가운데 띠에 있는 것만 2단계(LLM)로 넘긴다 — 모델에 묻는 건 비싸다.
    """
    title = post["title"]
    for r in NOT_RE:
        if r.search(title):
            return "no", f"제외 신호: {r.pattern}"
    for r in TRAVEL_RE:
        if r.search(title):
            return "travel", f"여행 신호: {r.pattern}"
    if not body:
        return "ask", "본문 없음"

    head = body[:900]
    go = sum(1 for r in BODY_GO_RE if r.search(head))
    nope = sum(1 for r in BODY_NO_RE if r.search(head))
    in_title = bool(PLACE_HINT and PLACE_HINT.search(title))
    places = len(find_cities(title, body))

    score = go * 1.0 - nope * 1.5 + (2.0 if in_title else 0) + min(places, 2) * 0.5
    if score >= 4.5:
        return "travel", f"본문 신호 {go} · 지명 {places} (점수 {score:.1f})"
    if score <= 1.0:
        return "no", f"이동 흔적 없음 (점수 {score:.1f})"
    return "ask", f"애매 (점수 {score:.1f})"


# ── 도시·날짜 추출 ────────────────────────────────────────────────────────────
DATE_PATS = [
    (re.compile(r"(\d{2,4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})"), 3),
    (re.compile(r"(\d{2,4})[.\-/년]\s*(\d{1,2})\s*월"), 2),
]


def guess_date(text: str, fallback: str) -> str:
    for pat, n in DATE_PATS:
        m = pat.search(text)
        if not m:
            continue
        y = int(m.group(1))
        y += 2000 if y < 100 else 0
        if not (1990 <= y <= 2035):
            continue
        parts = [f"{y:04d}", f"{int(m.group(2)):02d}"]
        if n == 3:
            parts.append(f"{int(m.group(3)):02d}")
        return "-".join(parts)
    return fallback


def norm_post_date(raw: str) -> str:
    m = re.match(r"\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", raw or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def find_cities(title: str, body: str) -> list[str]:
    """제목에서 먼저 찾고, 없을 때만 본문 앞부분을 본다.

    본문 뒤쪽에는 '관련 글' 목록이 붙어 다른 여행지 이름이 섞여 들어온다.
    그래서 본문은 앞 250자만 본다.
    """
    if not PLACE_HINT:
        return []

    def scan(text: str) -> list[str]:
        hits, seen = [], set()
        for m in PLACE_HINT.finditer(text or ""):
            name = ALIASES.get(m.group(0), m.group(0))
            if name not in seen:
                seen.add(name)
                hits.append(name)
        return hits

    return (scan(title) or scan(body[:250]))[:5]


def make_candidate(post: dict, body: str, verdict: str, why: str) -> dict:
    posted = norm_post_date(post.get("date", ""))
    text = post["title"] + " " + body[:250]
    return {
        "logNo": post["logNo"],
        "title": post["title"],
        "url": f"https://blog.naver.com/{fb.BLOG_ID}/{post['logNo']}",
        "cat": post["cat"],
        "posted": posted,
        "date": guess_date(text, posted),
        "cities": find_cities(post["title"], body),
        "verdict": verdict,
        "why": why,
        "status": "pending",
    }


# ── 2단계 (LLM) ──────────────────────────────────────────────────────────────
PROMPT = """다음은 한 사람의 블로그 글 목록이다. 글쓴이는 1996년부터 출장·주재·여행을 다녔다.
각 글이 **글쓴이가 실제로 어딘가에 다녀온 기록**인지 판정하라.

여행 기록이다 = travel : 특정 장소에 다녀온 이야기 (출장·주재·가족여행·맛집탐방·성지순례 포함)
아니다 = no : 시사 칼럼, 책·영화 감상, 남의 이야기, 일반론, 부고, 신앙 묵상

JSON 배열로만 답하라. 다른 말은 쓰지 마라.
[{"logNo":"...","verdict":"travel"|"no","cities":["도시명",...],"date":"YYYY-MM"|""}]

글 목록:
"""


def ask_api(items: list[dict], model: str = "claude-sonnet-5") -> list[dict]:
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic 이 필요하다")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    out = []
    for i in range(0, len(items), 25):  # 한 번에 25건씩
        chunk = items[i : i + 25]
        listing = "\n".join(
            f'- logNo={it["logNo"]} | {it["posted"]} | {it["title"]} | {it["excerpt"]}'
            for it in chunk
        )
        msg = client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": PROMPT + listing}],
        )
        text = msg.content[0].text.strip()
        text = re.sub(r"^```(json)?|```$", "", text, flags=re.M).strip()
        out.extend(json.loads(text))
        print(f"  LLM {min(i + 25, len(items))}/{len(items)}")
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    global PLACE_HINT
    PLACE_HINT = place_pattern()

    posts = fb.load_posts()
    bodies = json.loads((DATA / "blog_bodies.json").read_text(encoding="utf-8")) \
        if (DATA / "blog_bodies.json").exists() else {}

    decided, queue = [], []
    for p in posts:
        body = bodies.get(p["logNo"], "")
        verdict, why = stage1(p, body)
        if verdict == "ask":
            queue.append({**make_candidate(p, body, "ask", why),
                          "excerpt": body[:180]})
        else:
            decided.append(make_candidate(p, body, verdict, why))

    # 2단계
    verdicts: dict[str, dict] = {}
    if "--api" in sys.argv and queue:
        for row in ask_api(queue):
            verdicts[str(row["logNo"])] = row
    elif "--apply" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--apply") + 1])
        for row in json.loads(path.read_text(encoding="utf-8")):
            verdicts[str(row["logNo"])] = row

    for item in queue:
        v = verdicts.get(item["logNo"])
        item.pop("excerpt", None)
        if v:
            item["verdict"] = v.get("verdict", "ask")
            item["why"] = "LLM 판정"
            if v.get("cities"):
                item["cities"] = v["cities"]
            if v.get("date"):
                item["date"] = v["date"]
        decided.append(item)

    travel = [c for c in decided if c["verdict"] == "travel"]
    ask = [c for c in decided if c["verdict"] == "ask"]
    decided.sort(key=lambda c: c["posted"] or "", reverse=True)

    OUT.write_text(json.dumps({"candidates": decided}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"{OUT}: 전체 {len(decided)} · 여행 {len(travel)} · "
          f"아님 {len(decided) - len(travel) - len(ask)} · 미판정 {len(ask)}")

    if ask and "--api" not in sys.argv:
        QUEUE.write_text(
            json.dumps([{k: c[k] for k in ("logNo", "posted", "title")} |
                        {"excerpt": bodies.get(c["logNo"], "")[:180]}
                        for c in ask], ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"{QUEUE}: 2단계로 넘길 글 {len(ask)}건")


if __name__ == "__main__":
    main()
