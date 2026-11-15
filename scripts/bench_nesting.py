"""Optional benchmark: current guillotine/best-area-fit port vs rectpack MaxRects (NOT a runtime dependency).

    pip install rectpack && python scripts/bench_nesting.py

rectpack has no saw-kerf: each piece is inflated by the kerf (the standard trick), so the two columns are
comparable. Numbers feed docs/NESTING.md; nothing here ships.
"""
import random
import statistics
import time

from app.services.nesting import nest_pieces

try:
    from rectpack import MaxRectsBssf, newPacker
    from rectpack.packer import SORT_AREA
except ImportError:  # pragma: no cover
    raise SystemExit("pip install rectpack to run this benchmark") from None

STOCK = {"widthMm": 2440.0, "heightMm": 1220.0}
KERF = 3.0


def ours(pieces):
    t = time.perf_counter()
    r = nest_pieces(pieces, STOCK, KERF)
    return len(r["sheets"]), len(r["unplaced"]), time.perf_counter() - t


def rect(pieces):
    t = time.perf_counter()
    p = newPacker(pack_algo=MaxRectsBssf, sort_algo=SORT_AREA, rotation=True)
    for pc in pieces:
        p.add_rect(pc["widthMm"] + KERF, pc["heightMm"] + KERF, pc["id"])
    for _ in range(60):
        p.add_bin(STOCK["widthMm"] + KERF, STOCK["heightMm"] + KERF)
    p.pack()
    return len([b for b in p if len(b)]), len(p.rect_list()), time.perf_counter() - t


def instance(rng, n, lo, hi):
    return [{"id": f"p{i}", "label": f"p{i}", "widthMm": rng.uniform(lo, hi), "heightMm": rng.uniform(lo, hi),
             "rotatable": True, "finishedWidthMm": 1, "finishedHeightMm": 1} for i in range(n)]


if __name__ == "__main__":
    rng = random.Random(7)
    print(f"{'case':<22}{'ours sheets':>12}{'rectpack sheets':>17}{'ours ms':>10}{'rectpack ms':>13}")
    for n, lo, hi in [(20, 200, 900), (60, 150, 700), (120, 100, 600), (250, 80, 500)]:
        a, b, ta, tb = [], [], [], []
        for _ in range(20):
            ps = instance(rng, n, lo, hi)
            o, r = ours(ps), rect(ps)
            a.append(o[0])
            b.append(r[0])
            ta.append(o[2] * 1000)
            tb.append(r[2] * 1000)
        case = f"n={n} {lo}-{hi}mm"
        row = (statistics.mean(a), statistics.mean(b), statistics.mean(ta), statistics.mean(tb))
        print(f"{case:<22}{row[0]:>12.2f}{row[1]:>17.2f}{row[2]:>10.1f}{row[3]:>13.1f}")
