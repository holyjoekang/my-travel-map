"""전체 빌드. 지도 캐시 → 여행지 캐시 → 일정표 → 장소 마스터 → 앱 번들 순서로 돈다.

일정표가 장소 마스터보다 먼저인 이유는, 짝이 없던 일정표가 여정을 새로 만들고
그 여정의 도시가 장소 마스터에 들어가야 하기 때문이다.

캐시 둘은 이미 있으면 건드리지 않는다. 그래서 평소 빌드는 밖을 부르지 않는다.

사용법
  python scripts/build_all.py                 # 개인 빌드
  python scripts/build_all.py --public        # 공개 빌드도 함께
  python scripts/build_all.py --refresh-map   # 세계지도 캐시를 다시 받는다
  python scripts/build_all.py --refresh-dest  # trip.com 여행지 캐시를 다시 받는다
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args: list[str]) -> None:
    print(f"→ {' '.join(args)}")
    r = subprocess.run([sys.executable, *args], cwd=ROOT)
    if r.returncode:
        sys.exit(r.returncode)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--refresh-map" in sys.argv or not (ROOT / "data/world_land.json").exists():
        run(["scripts/fetch_world_map.py"])
    if "--refresh-dest" in sys.argv:
        run(["scripts/fetch_destinations.py", "--refresh"])
    elif not (ROOT / "data/destinations.json").exists():
        run(["scripts/fetch_destinations.py"])
    run(["scripts/build_itineraries.py"])
    run(["scripts/build_places.py"])
    run(["scripts/build_app.py"])
    if "--public" in sys.argv:
        run(["scripts/build_app.py", "--public"])
    print("완료 · app/index.html 을 브라우저로 열면 된다")


if __name__ == "__main__":
    main()
