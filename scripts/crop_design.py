"""홈 표지 원화 한 장을 조각내 장식 그림을 만든다.

`data/design_pics/` 의 콜라주 원화에서 글자가 없는 자리만 오려 낸다. 제목과 소개,
버튼, 숫자는 원화에 그려진 것을 쓰지 않고 화면에서 글자로 다시 쓴다 — 그래야
번역·검색·화면 크기에 따라 살아 움직인다. 그림은 양 옆과 바닥의 장식으로만 쓴다.

오려 낸 조각은 `data/design_pics/crops/*.webp` 로 남고,
`scripts/build_app.py` 가 빌드할 때 `--art-<이름>` CSS 변수로 번들에 박는다.
번들은 파일 하나로 돌아야 하므로(PRD §8) 그림도 data URI 로 들어간다.

사용법
  python scripts/crop_design.py                 # 기본 원화로
  python scripts/crop_design.py 다른그림.png      # 원화를 바꿔서

Pillow 가 있어야 한다(`pip install Pillow`). 조각은 저장소에 들어 있으므로
평소 빌드와 CI는 이 스크립트를 돌리지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

DESIGN = Path("data/design_pics")
OUT = DESIGN / "crops"
DEFAULT = DESIGN / "4c1de208-6e21-4180-8515-40a516a0fa93.png"

# 이름 → 원화에서 오려 낼 자리 (왼쪽, 위, 오른쪽, 아래). 1024x1536 기준이다.
# 글자가 그려진 자리는 일부러 피했다 — hero-right 를 x=805 에서 시작하는 이유다.
BOXES = {
    "hero-left":  (0, 0, 345, 425),       # 사람과 폴라로이드 — 표지 왼쪽
    "hero-right": (805, 108, 1024, 425),  # 바다·나침반·여권 — 표지 오른쪽
    # 표지 아래 찢어진 종이 가장자리는 원화에서 오리지 않는다 — 폴라로이드 밑동과 여권이
    # 함께 잘려 나와 가로로 늘어났다. 화면에서 종이 색으로 직접 그린다(.torn).
    "map":        (490, 410, 812, 598),   # 수채 세계지도 — 숫자 띠 오른쪽. 여권과 손글씨는 뺐다
    "invite":     (153, 1395, 288, 1536), # 산 위에 선 사람 — 초대 띠 왼쪽. 띠가 거의 정사각이라
                                          # 사람만 오린다. 그림 글자(Better Roads)와 옆 제목은 뺐다
}
MAX_W = 900      # 장식이라 이보다 크게 둘 이유가 없다
QUALITY = 82


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow 가 필요하다 — pip install Pillow")

    src_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not src_path.exists():
        sys.exit(f"원화가 없다: {src_path}")
    src = Image.open(src_path).convert("RGB")
    OUT.mkdir(parents=True, exist_ok=True)

    total = 0
    for name, box in BOXES.items():
        im = src.crop(box)
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
        path = OUT / f"{name}.webp"
        im.save(path, "WEBP", quality=QUALITY, method=6)
        kb = path.stat().st_size / 1024
        total += kb
        print(f"  · {name} {im.width}x{im.height} · {kb:,.0f}KB")
    print(f"{OUT}: 조각 {len(BOXES)} · 합쳐서 {total:,.0f}KB "
          f"(번들에는 base64 라 약 {total * 4 / 3:,.0f}KB 로 들어간다)")


if __name__ == "__main__":
    main()
