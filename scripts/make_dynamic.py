"""여행 지도를 동적 사이트로 바꾼다: 데이터·그림을 index.html 안에 박지 않고 파일로 두고, 화면이 fetch로 읽는다.

- app/index.template.html: data/app(.public).json 을 받은 뒤 앱 스크립트를 실행한다
- scripts/build_app.py: app/data/*.json · app/art/*.webp 를 쓰고 HTML은 그 주소만 가리킨다
- CI: 공개본 JSON·그림도 Pages 에 올린다 · 테스트·README·.gitignore 를 맞춘다
한 번만 돌리면 되고, 다시 돌려도 같은 결과.
"""
from pathlib import Path

def patch(path: str, old: str, new: str) -> None:
    p = Path(path); t = p.read_text(encoding="utf-8")
    if new in t:
        return
    assert t.count(old) == 1, f"{path}: 바꿀 자리를 찾지 못함: {old[:60]}"
    p.write_text(t.replace(old, new), encoding="utf-8")

# 1) 화면: 데이터를 받은 다음 앱 스크립트를 실행한다(앱 코드는 그대로 전역 스크립트로 돈다)
patch("app/index.template.html", "<script>\nconst DATA = /*__DATA__*/;",
      '<script>\n'
      '/* 데이터는 빌드가 만든 JSON(data/app.json · 공개본은 data/app.public.json)에서 받는다.\n'
      '   받은 뒤에 아래 앱 스크립트를 실행한다 — 앱 코드는 예전처럼 전역 스크립트로 돈다. */\n'
      'fetch("__DATA_URL__").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(d => {\n'
      '  window.__DATA__ = d;\n'
      '  const s = document.createElement("script");\n'
      '  s.textContent = document.getElementById("app").textContent;\n'
      '  document.body.appendChild(s);\n'
      '}).catch(e => { document.getElementById("view").textContent = "여행 데이터를 불러오지 못했습니다 (" + e.message + "). 서버로 열어 주세요: python -m http.server --directory app"; });\n'
      '</script>\n'
      '<script type="text/plain" id="app">\n'
      'const DATA = window.__DATA__;')

# 2) 빌드: JSON·그림 파일을 쓰고 HTML 은 주소만
B = "scripts/build_app.py"
patch(B, 'import base64\n', 'import hashlib\n')
patch(B, 'OUT = APP / "index.html"', 'OUT = APP / "index.html"\nOUT_DATA = APP / "data"   # ← 빌드 산출물 · 화면이 읽는 JSON (개인본은 .gitignore)\nOUT_ART = APP / "art"     # ← 빌드 산출물 · 홈 장식 그림')
patch(B, '''    """홈 장식 그림을 CSS 변수로 박는다.

    번들은 파일 하나로 돈다(PRD §8). 그래서 그림도 바깥에서 부르지 않고
    data URI 로 넣는다. 조각이 없으면 변수도 없고, 화면은 그림 없이 그대로 돈다.
    """''', '''    """홈 장식 그림을 app/art/ 에 두고 CSS 변수로 그 주소를 건다.

    조각이 없으면 변수도 없고, 화면은 그림 없이 그대로 돈다.
    """''')
patch(B, '''    for f in sorted(ART.glob("*.webp")):
        b64 = base64.b64encode(f.read_bytes()).decode("ascii")
        lines.append(f'  --art-{f.stem}:url("data:image/webp;base64,{b64}");')''', '''    OUT_ART.mkdir(parents=True, exist_ok=True)
    for f in sorted(ART.glob("*.webp")):
        raw = f.read_bytes()
        (OUT_ART / f.name).write_bytes(raw)
        lines.append(f'  --art-{f.stem}:url("art/{f.name}?v={hashlib.md5(raw).hexdigest()[:8]}");')''')
patch(B, '''    if "/*__DATA__*/" not in html:
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
    )''', '''    if "__DATA_URL__" not in html:
        sys.exit("템플릿에 __DATA_URL__ 자리표시자가 없다")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    name = "app.public.json" if public else "app.json"
    html = html.replace("__DATA_URL__", f"data/{name}?v={hashlib.md5(body.encode()).hexdigest()[:10]}")
    html = html.replace("/*__ART__*/", art_css())

    if public:
        leaked = check_public(html + body, load(DATA / "trips.json"))
        if leaked:
            sys.exit(f"공개 빌드에 실명·개인 앨범이 남아 있다: {', '.join(leaked)}")

    OUT_DATA.mkdir(parents=True, exist_ok=True)
    (OUT_DATA / name).write_text(body, encoding="utf-8")
    out = OUT.with_name("index.public.html") if public else OUT
    out.write_text(html, encoding="utf-8")
    print(
        f"{out} ({out.stat().st_size / 1024:,.0f}KB) + {OUT_DATA / name} ({len(body.encode()) / 1024:,.0f}KB): "
        f"여정 {len(payload['trips'])} · 장소 {len(payload['places'])} · {'공개' if public else '개인'} 빌드"
    )''')
patch("scripts/build_all.py", 'print("완료 · app/index.html 을 브라우저로 열면 된다")',
      'print("완료 · python -m http.server 8000 --directory app 후 http://localhost:8000 을 연다")')

# 3) 산출물은 저장소에 올리지 않는다(개인본 JSON 에는 실명이 들어간다)
patch(".gitignore", "app/index.public.html\n", "app/index.public.html\napp/data/\napp/art/\n")

# 4) CI: 공개본 화면 + 공개본 JSON + 그림만 Pages 로
patch(".github/workflows/ci.yml", "          cp app/index.public.html _site/index.html\n",
      "          cp app/index.public.html _site/index.html\n"
      "          mkdir -p _site/data && cp app/data/app.public.json _site/data/\n"
      "          if [ -d app/art ]; then cp -r app/art _site/art; fi\n")
patch(".github/workflows/ci.yml", "          path: app/index*.html\n", "          path: |\n            app/index.public.html\n            app/data/app.public.json\n            app/art\n")

# 5) 테스트: 데이터는 이제 JSON 에 있다
T = "tests/test_build.py"
patch(T, '''        """스크립트·스타일은 전부 파일 안에 있다. 파일 하나로 돌아야 한다 (PRD §8).''',
      '''        """스크립트·스타일은 전부 파일 안에 있다. 데이터·그림만 같은 곳의 파일로 받는다 (동적 전환).''')
patch(T, '''        html = (ROOT / "app/index.public.html").read_text(encoding="utf-8")
        self.assertIn('"mapsKey":""', html)''', '''        html = (ROOT / "app/index.public.html").read_text(encoding="utf-8")
        self.assertIn('"mapsKey":""', (ROOT / "app/data/app.public.json").read_text(encoding="utf-8"))''')
patch(T, '''        self.assertNotIn("/*__DATA__*/", html)''', '''        self.assertNotIn("__DATA_URL__", html)
        self.assertIn("data/app.json?v=", html)          # 화면은 빌드가 쓴 JSON 을 받는다
        self.assertTrue((ROOT / "app/data/app.json").exists())''')

# 6) README
patch("README.md", "`app/index.html` 이 만들어진다. 브라우저로 열면 끝이다 — **서버도, API 키도, 설치할 패키지도 없다.**",
      "`app/index.html` 과 그 화면이 읽는 `app/data/app.json`·`app/art/` 가 만들어진다.\n"
      "화면은 시작할 때 데이터를 받아 오므로(동적 사이트) 파일을 직접 열지 말고 서버로 연다 — **API 키도, 설치할 패키지도 없다.**\n\n"
      "```bash\npython -m http.server 8000 --directory app   # http://localhost:8000\n```")
patch("README.md", "  build_app.py            데이터를 HTML에 주입 → app/index.html",
      "  build_app.py            데이터 → app/data/app(.public).json · 그림 → app/art/ · 화면 → app/index(.public).html")
patch("README.md", "  index.html              ← 빌드 산출물", "  index.html              ← 빌드 산출물 · 시작할 때 data/app.json 을 받는다\n  data/                   ← 빌드 산출물 · app.json(개인) · app.public.json(공개)\n  art/                    ← 빌드 산출물 · 홈 장식 그림")
print("동적 전환 완료")

# 7) 사진 주소는 이제 JSON 에 있다 — 화면과 데이터를 함께 본다
patch(T, '''        """사진만 밖에서 받는다. 그것도 trip.com 한 곳에서만 (PRD §14)."""
        html = (ROOT / "app/index.html").read_text(encoding="utf-8")''',
      '''        """사진만 밖에서 받는다. 그것도 trip.com 한 곳에서만 (PRD §14)."""
        html = ((ROOT / "app/index.html").read_text(encoding="utf-8")
                + (ROOT / "app/data/app.json").read_text(encoding="utf-8"))''')
print("테스트 보정 완료")
