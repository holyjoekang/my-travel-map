"""출입국 기록(data/immigration.tsv)을 여정 원장(data/trips.json)에 합친다.

- 출국일이 ±3일 안에 드는 기존 여정은 날짜를 출입국 기록으로 고치고 출처에 immigration을 더한다.
- 연도만 있던 기억 여정은 도시가 겹치고 연도가 맞으면 날짜를 채운다.
- 행선지가 적혀 있고 원장에 없던 여정은 NEW에 적힌 것만 새로 넣는다.
- 행선지 미상이거나 주재 기간(우산 여정) 안의 출입국은 원장에 넣지 않고 tsv에만 남긴다.
다시 돌려도 결과가 같다.
"""
import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIPS = ROOT / "data" / "trips.json"
LOG = ROOT / "data" / "immigration.tsv"
SRC = "immigration"

# 원장에 없던 여정 — 번호: (id, 제목, 목적, 도시, 추가 필드)
NEW = {
    6: ("t-2002-06-11", "신혼여행 — 싱가포르·빈탄", "couple", ["싱가포르", "빈탄"], {"companions": ["wife"]}),
    7: ("t-2003-09-07", "베이징 — 오라클월드 컨퍼런스", "business", ["베이징"], {}),
    11: ("t-2004-10-31", "모스크바 출장 — 물산과", "business", ["모스크바"], {}),
    12: ("t-2004-04-10", "모스크바 — 물산과 출장", "business", ["모스크바"],
         {"note": "출입국 기록 원문: 모스크바, 물산과 출장, 교통카드."}),
    90: ("t-2017-05-23", None, "business", ["하문"], {}),
    117: ("t-2023-07-24", "상해 출장", "business", ["상해"], {}),
}


def d(s):
    y, m, dd = map(int, s.split("."))
    return date(y, m, dd)


def era_of(eras, day):
    ym = day.strftime("%Y-%m")
    for e in eras:
        if e["start"] <= ym and (e["end"] is None or ym <= e["end"]):
            last = e["id"]
    return last


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    doc = json.loads(TRIPS.read_text(encoding="utf-8"))
    trips, eras = doc["trips"], doc["eras"]
    rows = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        no, out, back, note = line.split("\t")
        rows.append((int(no), d(out), d(back), "" if note == "—" else note))

    log = {"updated": [], "filled": [], "added": [], "unchanged": [], "logOnly": []}
    for no, out, back, note in rows:
        s, e = out.isoformat(), back.isoformat()
        exact = [t for t in trips if len(t["start"]) == 10
                 and abs((date.fromisoformat(t["start"]) - out).days) <= 3]
        fuzzy = [t for t in trips if len(t["start"]) == 4 and note
                 and int(t["start"]) <= out.year <= int(t["end"][:4])
                 and any(c in note for c in t["cities"])]
        hits = exact or fuzzy
        for t in hits:
            if SRC not in t["sources"]:
                t["sources"].append(SRC)
            if (t["start"], t["end"]) == (s, e):
                log["unchanged"].append(f"#{no} {t['id']}")
                continue
            log["filled" if t in fuzzy else "updated"].append(
                f"#{no} {t['id']}: {t['start']}~{t['end']} → {s}~{e}  ({note or '—'} / {','.join(t['cities'])})")
            t["start"], t["end"] = s, e
            if t in fuzzy:
                t["confidence"] = "medium"
                t["note"] = f"날짜는 출입국 기록 #{no}에서 채웠다. 원문: {note}"
        if hits:
            continue
        if no in NEW:
            tid, title, purpose, cities, extra = NEW[no]
            if not any(t["id"] == tid for t in trips):
                t = {"id": tid, "start": s, "end": e, "era": era_of(eras, out),
                     "purpose": purpose, "scope": "overseas", "cities": cities,
                     "sources": [SRC], "confidence": "high", **extra}
                if title:
                    t = {"id": tid, "title": title, **{k: v for k, v in t.items() if k != "id"}}
                trips.append(t)
                log["added"].append(f"#{no} {tid} {s}~{e} {','.join(cities)}")
            continue
        log["logOnly"].append(f"#{no} {s}~{e} {note or '—'}")

    TRIPS.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for k, v in log.items():
        print(f"\n[{k}] {len(v)}")
        if k != "logOnly":
            print("\n".join("  " + x for x in v))


if __name__ == "__main__":
    main()
