"""세계지도 윤곽을 내려받아 캐시한다 (빌드 때 1회).

앱은 외부 타일을 쓰지 않는다(아티팩트 CSP가 막는다). 그래서 국경 폴리곤을
미리 받아 data/world_land.json에 넣어두고, 앱은 이 파일만 읽어 SVG로 그린다.

사용법: python scripts/fetch_world_map.py [--force]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import topojson  # noqa: E402

URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json"
RAW = Path("data/_cache/countries-110m.json")
OUT = Path("data/world_land.json")

# 점 지도에서 뭉개져 보이는 아주 작은 고리는 버린다 (경위도 제곱 면적 기준).
MIN_AREA = 0.6


def _area(ring: list[list[float]]) -> float:
    s = 0.0
    for i in range(len(ring) - 1):
        s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(s) / 2


def download(force: bool = False) -> dict:
    RAW.parent.mkdir(parents=True, exist_ok=True)
    if RAW.exists() and not force:
        return json.loads(RAW.read_text(encoding="utf-8"))
    req = urllib.request.Request(URL, headers={"User-Agent": "MyTravel/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    RAW.write_bytes(raw)
    return json.loads(raw)


def build(topo: dict) -> dict:
    countries = []
    for feat in topojson.features(topo, "countries"):
        rings = []
        for ring in feat["rings"]:
            simple = topojson.simplify(ring, 1)
            if len(simple) >= 4 and _area(simple) >= MIN_AREA:
                rings.append(simple)
        if rings:
            countries.append({"name": feat["name"], "rings": rings})
    return {"source": URL, "countries": countries}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    topo = download("--force" in sys.argv)
    out = build(topo)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    rings = sum(len(c["rings"]) for c in out["countries"])
    pts = sum(len(r) for c in out["countries"] for r in c["rings"])
    print(f"{OUT}: 나라 {len(out['countries'])} · 고리 {rings} · 점 {pts} · {OUT.stat().st_size:,}B")


if __name__ == "__main__":
    main()
