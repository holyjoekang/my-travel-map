"""빌드 → 테스트 → 커밋 → 푸시를 한 번에. GitHub Pages 배포는 CI가 이어받는다.

깨진 것을 올리지 않으려고 순서를 고정했다 — **테스트가 떨어지면 커밋하지 않는다.**
푸시가 끝나면 Actions 가 공개 빌드를 다시 만들어
https://holyjoekang.github.io/my-travel-map/ 에 올린다(.github/workflows/ci.yml).

사용법
  python scripts/release.py -m "여행 홈페이지로 고쳤다"
  python scripts/release.py -m "..." --dry-run     # 무엇을 할지만 보여 준다
  python scripts/release.py -m "..." --no-push     # 커밋까지만
  python scripts/release.py -m "..." --watch       # 푸시 뒤 CI 결과까지 지켜본다
  python scripts/release.py --refresh-dest -m "…"  # trip.com 여행지 캐시부터 다시 받는다

올라가는 것은 저장소 파일뿐이다. `app/index*.html` 과 `data/private.json` 은
.gitignore 에 있으므로 이 스크립트로도 올라가지 않는다 — 공개본은 CI가 직접 만든다(PRD §11).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "main"
REMOTE = "origin"
PAGES = "https://holyjoekang.github.io/my-travel-map/"


def run(args: list[str], *, dry: bool = False, check: bool = True,
        capture: bool = False) -> subprocess.CompletedProcess:
    print(f"→ {' '.join(args)}")
    if dry:
        return subprocess.CompletedProcess(args, 0, "", "")
    r = subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                       capture_output=capture)
    if check and r.returncode:
        if capture:
            print(r.stdout or "", r.stderr or "", sep="\n")
        sys.exit(f"멈춘다 · {' '.join(args)} 가 {r.returncode} 로 끝났다")
    return r


def git(*args: str, **kw) -> subprocess.CompletedProcess:
    return run(["git", *args], **kw)


def changed() -> list[str]:
    r = git("status", "--porcelain", check=False, capture=True)
    return [l for l in (r.stdout or "").splitlines() if l.strip()]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="빌드·테스트·커밋·푸시")
    ap.add_argument("-m", "--message", help="커밋 메시지 (없으면 그냥 빌드·테스트만)")
    ap.add_argument("--dry-run", action="store_true", help="실행하지 않고 보여만 준다")
    ap.add_argument("--no-push", action="store_true", help="커밋까지만 한다")
    ap.add_argument("--watch", action="store_true", help="푸시 뒤 CI 결과를 지켜본다")
    ap.add_argument("--refresh-dest", action="store_true",
                    help="trip.com 여행지 캐시를 다시 받는다")
    a = ap.parse_args()
    dry = a.dry_run

    # 1. 빌드 — 개인본과 공개본을 함께 만든다. 공개본에 실명이 남으면 여기서 멈춘다.
    build = [sys.executable, "scripts/build_all.py", "--public"]
    if a.refresh_dest:
        build.append("--refresh-dest")
    run(build, dry=dry)

    # 2. 테스트 — 떨어지면 커밋하지 않는다.
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], dry=dry)

    if not a.message:
        print("커밋 메시지(-m)가 없어 빌드·테스트만 했다")
        return

    # 3. 커밋 — 올릴 것이 없으면 조용히 넘어간다.
    pending = changed()
    if not pending and not dry:
        print("고친 것이 없다 — 커밋할 것이 없다")
    else:
        for line in pending:
            print(f"   {line}")
        git("add", "-A", dry=dry)
        git("commit", "-m", a.message, dry=dry)

    if a.no_push:
        print("푸시는 건너뛴다(--no-push)")
        return

    # 4. 푸시 — 여기서부터 CI가 공개 빌드를 만들어 Pages 에 올린다.
    git("push", REMOTE, BRANCH, dry=dry)
    print(f"올렸다 · 잠시 뒤 {PAGES} 에 반영된다")

    if a.watch and not dry:
        if not shutil.which("gh"):
            print("gh 가 없어 CI 결과는 못 본다 — Actions 탭에서 확인하라")
            return
        run(["gh", "run", "watch", "--exit-status", "--compact"], check=False)
        run(["gh", "run", "list", "--limit", "1"], check=False)


if __name__ == "__main__":
    main()
