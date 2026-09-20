"""TopoJSON 디코더 (표준 라이브러리만 사용).

world-atlas 같은 TopoJSON을 경위도 폴리곤으로 푼다.
빌드 때 한 번만 돌리고 결과를 캐시하므로 속도보다 의존성 없는 쪽을 택했다.
"""

from __future__ import annotations


def decode_arcs(topology: dict) -> list[list[list[float]]]:
    """델타 인코딩된 arc들을 [[lon, lat], ...] 목록으로 되돌린다."""
    tr = topology.get("transform")
    out = []
    for arc in topology["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            if tr:
                pts.append(
                    [
                        x * tr["scale"][0] + tr["translate"][0],
                        y * tr["scale"][1] + tr["translate"][1],
                    ]
                )
            else:
                pts.append([float(x), float(y)])
        out.append(pts)
    return out


def _ring(arcs: list[list[list[float]]], idx_list: list[int]) -> list[list[float]]:
    """arc 인덱스 목록을 이어붙여 하나의 고리를 만든다. 음수는 해당 arc의 역방향."""
    ring: list[list[float]] = []
    for i in idx_list:
        seg = arcs[~i][::-1] if i < 0 else arcs[i]
        # 이어붙일 때 이음매가 겹치므로 첫 점을 버린다.
        ring.extend(seg[1:] if ring else seg)
    return ring


def features(topology: dict, object_name: str) -> list[dict]:
    """{'id', 'name', 'rings'} 목록을 돌려준다. Polygon/MultiPolygon만 다룬다."""
    arcs = decode_arcs(topology)
    out = []
    for geom in topology["objects"][object_name]["geometries"]:
        gtype = geom.get("type")
        if gtype == "Polygon":
            groups = [geom["arcs"]]
        elif gtype == "MultiPolygon":
            groups = geom["arcs"]
        else:
            continue
        rings = [_ring(arcs, part) for poly in groups for part in poly]
        out.append(
            {
                "id": geom.get("id"),
                "name": (geom.get("properties") or {}).get("name"),
                "rings": rings,
            }
        )
    return out


def simplify(ring: list[list[float]], ndigits: int = 1) -> list[list[float]]:
    """좌표를 반올림하고 연속 중복점을 버린다. 세계 축척 점 지도에는 이 정도면 충분하다."""
    out: list[list[float]] = []
    for lon, lat in ring:
        p = [round(lon, ndigits), round(lat, ndigits)]
        if not out or p != out[-1]:
            out.append(p)
    return out
