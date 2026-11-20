"""Random-but-seeded DESIGN GENERATORS used by the unit tests (no JS involved).

They were built for the differential fuzz tests of the migration (Python port vs the real JS engine); those ran against
the JS until it was deleted (phase 12). What they produced is frozen in tests/golden/corpus.jsonl.gz and replayed by
tests/test_golden_corpus.py. The generators stay because they are good, varied inputs for any test:

  random_layout(rng)     panels placed around each other at every boundary of the joint tolerances (+ doors, drawers)
  furniture_layout(rng)  carcass + drawers at random gap / thickness / depth + doors (hardware selection boundaries)
  cabinet_layout(rng)    cabinet with named carcass panels, drawers (identical or not), plinth, doors, loose panels
  random_graph(rng)      constraint graphs (spansBetween / attachedTo / distance / equalSpacing) with rotations
"""
from __future__ import annotations

import random

from app.services.geometry import get_aligned_axis, world_half_extents

LAYOUT_ROTATIONS = [(0, 0, 0), (0, 90, 0), (90, 0, 0), (0, 0, 90), (90, 90, 0), (0, 90, 90), (90, 0, 90), (0, 180, 0),
             (0, -90, 0), (0, 0, 5), (0, 0, 45)]
LAYOUT_DIMS = [18, 18, 100, 300, 400, 600, 800.5]
# face-to-face distance along the contact axis (negative = the panels overlap by that much)
LAYOUT_GAPS = [0, 0, 0, 0.049, 0.05, 0.051, 1, 2.9, 3, 3.1, 5, -0.049, -0.05, -0.051, -0.5, -0.99, -1, -1.01, -2, 10]
LAYOUT_CONTACT_MARGINS = [0.5, 4.9, 5, 5.1, 20]  # how little footprint two panels share along a non-contact axis
LAYOUT_EDGE_TWEAKS = [0, 0.4, 0.5, 0.6, -0.4, -0.5, -0.6]  # around the corner/T boundary tolerance


def _node(pid: str, rng: random.Random) -> dict:
    rot = rng.choice(LAYOUT_ROTATIONS)
    rotation = {"x": rot[0], "y": rot[1], "z": rot[2]}
    w, h = rng.choice(LAYOUT_DIMS), rng.choice(LAYOUT_DIMS)
    aligned = get_aligned_axis(type("R", (), rotation)(), "front")
    axis = aligned[0] if aligned else "z"
    if rng.random() < 0.08:
        axis = rng.choice("xyz")  # deliberately inconsistent: thicknessAxis is passed through, not recomputed
    return {
        "id": pid, "name": pid, "material": "Melamine White 18mm", "quantity": 1, "thicknessAxis": axis,
        "width": w, "height": h, "thickness": 18, "rotation": rotation,
        "basePosition": {"x": 0, "y": 0, "z": 0}, "offset": {"x": 0, "y": 0, "z": 0},
        "constraints": [], "groupId": rng.choice([None, None, "g1", "g2"]), "hidden": rng.random() < 0.08,
    }


def _geom(n: dict) -> tuple[dict, dict]:
    half = world_half_extents({"rotation": n["rotation"], "width": n["width"], "height": n["height"], "thickness": 18})
    return dict(n["basePosition"]), half


def random_layout(rng: random.Random) -> list[dict]:
    count = rng.randint(2, 10)
    nodes = [_node("p0", rng)]
    nodes[0]["basePosition"] = {a: round(rng.uniform(-200, 200), 3) for a in "xyz"}
    for i in range(1, count):
        new = _node(f"p{i}", rng)
        anchor = rng.choice(nodes)
        a_pos, a_half = _geom(anchor)
        n_half = _geom(new)[1]
        axis, sign = rng.choice("xyz"), rng.choice([-1, 1])
        pos = {}
        for a in "xyz":
            if a == axis:
                face = a_pos[a] + sign * a_half[a]
                pos[a] = face + sign * (rng.choice(LAYOUT_GAPS) + n_half[a])
            else:
                kind = rng.random()
                if kind < 0.25:
                    off = 0.0
                elif kind < 0.55:  # share only a thin strip of footprint
                    off = rng.choice([-1, 1]) * (a_half[a] + n_half[a] - rng.choice(LAYOUT_CONTACT_MARGINS))
                elif kind < 0.8:  # flush with an edge, give or take the boundary tolerance
                    off = rng.choice([-1, 1]) * (a_half[a] - n_half[a] + rng.choice(LAYOUT_EDGE_TWEAKS))
                else:
                    off = rng.uniform(-150, 150)
                pos[a] = a_pos[a] + off
        new["basePosition"] = {a: round(pos[a], 6) for a in "xyz"}
        nodes.append(new)

    ids = [n["id"] for n in nodes]
    fronts: list[str] = []
    for n in nodes:
        roll = rng.random()
        if roll < 0.18:
            n.update({"isDoor": True, "hinge": rng.choice(["left", "right", "right", None]),
                      "normalAxis": rng.choice(["x", "y", "z", "z", "x"]),
                      "boundaryIds": rng.choice([{}, {"left": rng.choice(ids + ["ghost"]), "right": rng.choice(ids)},
                                                 {"right": rng.choice(ids)}, None])})
        elif roll < 0.32:
            n.update({"isDrawerFront": True, "normalAxis": rng.choice(["x", "z", "z", "y"]),
                      "boundaryIds": rng.choice([{"left": rng.choice(ids), "right": rng.choice(ids)},
                                                 {"left": rng.choice(ids + ["ghost"])}, {}, None])})
            fronts.append(n["id"])
        elif roll < 0.5 and fronts:
            n.update({"isDrawerBoxPanel": True, "drawerBoxFrontId": rng.choice(fronts + ["ghost"]),
                      "drawerBoxRole": rng.choice(["left", "right", "left", "right", "bottom"])})
    for n in nodes:  # JSON has no `undefined`: absent keys, not nulls (the modeller never sends null here)
        for k in [k for k, v in n.items() if v is None and k in ("hinge", "boundaryIds")]:
            del n[k]
    rng.shuffle(nodes)
    return nodes


def furniture_layout(rng: random.Random) -> list[dict]:
    """A carcass with two sides, 0-3 drawers (box sides at a random gap / thickness / depth: the runner rules
    only fire when these line up) and 0-2 doors of random thickness, with piece codes present / absent / empty."""
    def node(pid, w, h, t, rot, pos, **extra):
        axis = {"x": "x", "y": "y", "z": "z"}[extra.pop("axis")]
        n = {"id": pid, "name": f"Name {pid}", "material": "Melamine White 18mm", "quantity": 1, "thicknessAxis": axis,
             "width": w, "height": h, "thickness": t, "rotation": rot, "basePosition": pos,
             "offset": {"x": 0, "y": 0, "z": 0}, "constraints": [], "groupId": "g", "hidden": False, **extra}
        code = rng.choice([None, None, f"PC{pid}", ""])
        if code is not None:
            n["pieceCode"] = code
        return n

    half = rng.choice([250, 291, 400])
    depth, height = rng.choice([300, 450, 600, 700]), rng.choice([500, 900, 1700, 2300])
    side_rot = {"x": 0, "y": 90, "z": 0}
    left = node("L", depth, height, 18, side_rot, {"x": -half - 9, "y": height / 2, "z": 0}, axis="x")
    right = node("R", depth, height, 18, side_rot, {"x": half + 9, "y": height / 2, "z": 0}, axis="x")
    top = node("T", 2 * half, depth, 18, {"x": 90, "y": 0, "z": 0}, {"x": 0, "y": height + 9, "z": 0}, axis="y")
    nodes = [left, right, top]
    for i in range(rng.randint(0, 3)):
        front_id = f"F{i}"
        nodes.append(node(front_id, 2 * half, 150, 18, {"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 100 + 160 * i, "z": depth / 2 + 9},
                          axis="z", isDrawerFront=True, normalAxis="z", boundaryIds={"left": "L", "right": "R"}))
        for role, sign in (("left", -1), ("right", 1)):
            t = rng.choice([8, 12, 15.99, 16, 16.01, 18, 19, 20])
            gap = rng.choice([19.99, 20, 21, 21, 21, 22, 22.01, 25])
            length = rng.choice([250, 269.99, 270, 300, 349.99, 350, 450, 650, 651])
            x = sign * (half - gap - t / 2)
            nodes.append(node(f"{front_id}{role[0]}", length, 120, t, side_rot, {"x": x, "y": 100 + 160 * i, "z": 0}, axis="x",
                              isDrawerBoxPanel=True, drawerBoxFrontId=front_id, drawerBoxRole=role))
    for i in range(rng.randint(0, 2)):
        nodes.append(node(f"D{i}", half, rng.choice([300, 900, 1600, 1601, 2200, 2201]), rng.choice([15.99, 16, 18, 24, 24.01]),
                          {"x": 0, "y": 0, "z": 0}, {"x": rng.choice([-half / 2, half / 2]), "y": 700, "z": depth / 2 + 30},
                          axis="z", isDoor=True, hinge=rng.choice(["left", "right"]), normalAxis="z",
                          boundaryIds={"left": "L", "right": rng.choice(["R", "R", "ghost"])}))
    rng.shuffle(nodes)
    return nodes


NAMES = {"top": ["Top", "Top Panel", "Roof"], "bottom": ["Bottom", "Base"], "back": ["Back", "Back Panel", "Rear"],
         "shelf": ["Shelf", "Fixed shelf", "Horizontal 1"], "vert": ["Divider", "Vertical Divider", "Partition"],
         "side": ["Left Side", "Right Side", "Side", "Panel", "Shelf Side"]}


def cabinet_layout(rng: random.Random) -> list[dict]:
    def node(pid, name, w, h, t, rot, pos, **extra):
        n = {"id": pid, "name": name, "material": rng.choice(["Melamine White 18mm", "Oak 18mm"]), "quantity": 1,
             "thicknessAxis": extra.pop("axis"), "width": w, "height": h, "thickness": t, "rotation": rot,
             "basePosition": pos, "offset": {"x": 0, "y": 0, "z": 0}, "constraints": [], "groupId": "g",
             "hidden": rng.random() < 0.03, **extra}
        code = rng.choice([None, None, f"{rng.choice('abAB')}{rng.randint(1, 30):02d}", f"PC-{pid}", ""])
        if code is not None:
            n["pieceCode"] = code
        return n

    half, depth = rng.choice([250, 291, 400]), rng.choice([300, 450, 600])
    height = rng.choice([500, 900, 1700, 2300])
    side = {"x": 0, "y": 90, "z": 0}
    flat = {"x": 90, "y": 0, "z": 0}
    nodes = [
        node("L", rng.choice(NAMES["side"]), depth, height, 18, side, {"x": -half - 9, "y": height / 2, "z": 0}, axis="x"),
        node("R", rng.choice(NAMES["side"]), depth, height, 18, side, {"x": half + 9, "y": height / 2, "z": 0}, axis="x"),
        node("T", rng.choice(NAMES["top"]), 2 * half + 36, depth, 18, flat, {"x": 0, "y": height + 9, "z": 0}, axis="y"),
    ]
    if rng.random() < 0.8:
        nodes.append(node("B", rng.choice(NAMES["bottom"]), 2 * half, depth, 18, flat, {"x": 0, "y": 9, "z": 0}, axis="y"))
    if rng.random() < 0.7:
        nodes.append(node("K", rng.choice(NAMES["back"]), 2 * half + 36, height, 8, {"x": 0, "y": 0, "z": 0},
                          {"x": 0, "y": height / 2, "z": -depth / 2 - 4}, axis="z"))
    for i in range(rng.randint(0, 2)):
        nodes.append(node(f"S{i}", rng.choice(NAMES["shelf"]), 2 * half, depth, 18, flat,
                          {"x": 0, "y": 200 + 250 * i, "z": 0}, axis="y"))
    if rng.random() < 0.3:
        nodes.append(node("V", rng.choice(NAMES["vert"]), depth, height - 36, 18, side,
                          {"x": rng.choice([-half / 2, 0, half / 2]), "y": height / 2, "z": 0}, axis="x"))
    if rng.random() < 0.4:  # plinth frame under the bottom: front board + two returns (sometimes with a gap: no contact)
        drop = rng.choice([0, 0, 120])  # a gap leaves the plinth touching nothing -> the 'bottom panel' fallback
        nodes.append(node("PF", "Plinth Front", 2 * half, 100, 18, {"x": 0, "y": 0, "z": 0}, {"x": 0, "y": -50 - drop, "z": depth / 2 - 41}, axis="z", isPlinthPanel=True))
        nodes.append(node("PL", "Plinth Side", depth - 100, 100, 18, side, {"x": -half + 9, "y": -50 - drop, "z": 0}, axis="x", isPlinthPanel=True))
        nodes.append(node("PR", "Plinth Side", depth - 100, 100, 18, side, {"x": half - 9, "y": -50 - drop, "z": 0}, axis="x", isPlinthPanel=True))
    identical = rng.random() < 0.5
    t0, gap0, len0 = rng.choice([12, 15, 16, 18]), rng.choice([21, 21, 20.5, 25]), rng.choice([300, 450, 650])
    for i in range(rng.randint(0, 3)):
        fid = f"F{i}"
        nodes.append(node(fid, "Drawer Front", 2 * half, 150, 18, {"x": 0, "y": 0, "z": 0},
                          {"x": 0, "y": 100 + 160 * i, "z": depth / 2 + 9}, axis="z", isDrawerFront=True, normalAxis="z",
                          boundaryIds={"left": "L", "right": "R"}))
        t = t0 if identical else rng.choice([12, 16, 18])
        gap = gap0 if identical else rng.choice([21, 22.5])
        length = len0 if identical else rng.choice([300, 450, 650])
        for role, sign in (("left", -1), ("right", 1)):
            nodes.append(node(f"{fid}{role[0]}", f"Drawer Box {role}", length, 120, t, side,
                              {"x": sign * (half - gap - t / 2), "y": 100 + 160 * i, "z": 0}, axis="x",
                              isDrawerBoxPanel=True, drawerBoxFrontId=fid, drawerBoxRole=role))
        if rng.random() < 0.8:
            nodes.append(node(f"{fid}k", "Drawer Box back", 2 * (half - gap) - 2 * t, 120, t, {"x": 0, "y": 0, "z": 0},
                              {"x": 0, "y": 100 + 160 * i, "z": -length / 2 + t / 2}, axis="z",
                              isDrawerBoxPanel=True, drawerBoxFrontId=fid, drawerBoxRole="back"))
        if rng.random() < 0.8:
            nodes.append(node(f"{fid}b", "Drawer Box bottom", 2 * (half - gap) - 2 * t, length, 8, flat,
                              {"x": 0, "y": 100 + 160 * i - 56, "z": 0}, axis="y",
                              isDrawerBoxPanel=True, drawerBoxFrontId=fid, drawerBoxRole="bottom"))
    for i in range(rng.randint(0, 2)):
        nodes.append(node(f"D{i}", "Door", half, rng.choice([300, 900, 1700]), 18, {"x": 0, "y": 0, "z": 0},
                          {"x": rng.choice([-half / 2, half / 2]), "y": 700, "z": depth / 2 + 30}, axis="z",
                          isDoor=True, hinge=rng.choice(["left", "right"]), normalAxis="z", doorSign=rng.choice([-1, 1]),
                          boundaryIds={"left": "L", "right": "R"}))
    if rng.random() < 0.15:  # a loose panel that touches nothing
        nodes.append(node("X", "Loose Panel", 300, 300, 18, flat, {"x": 3000, "y": 3000, "z": 3000}, axis="y"))
    rng.shuffle(nodes)
    return nodes


FACES = ["right", "left", "top", "bottom", "front", "back"]
FIELDS = ["width", "height", "thickness", "positionX", "positionY", "positionZ"]
GRAPH_ROTATIONS = [(0, 0, 0), (0, 90, 0), (90, 0, 0), (0, 0, 90), (90, 90, 0), (0, -90, 0), (0, 180, 0), (180, 0, 0),
             (0, 0, 45), (0, 0, 11), (0, 0, 12), (30, 60, 0), (270, 0, 90), (0, 0, 11.4), (0, 0, 11.6),
             # all three angles non-zero: exercises every term of the Euler matrix
             (90, 90, 90), (90, 0, 90), (0, 90, 90), (30, 60, 45), (180, 90, 180), (10, 10, 10), (89, 91, 90)]


def random_graph(rng: random.Random) -> list[dict]:
    n = rng.randint(1, 8)
    ids = [f"p{i}" for i in range(n)]

    def ref(allow_literal=True):
        roll = rng.random()
        if allow_literal and roll < 0.12:
            return {"mm": round(rng.uniform(-500, 1500), 3)}
        node = rng.choice(ids + ["ghost"] if roll < 0.2 else ids)
        end = {"node": node, "face": rng.choice(FACES + (["sideways"] if rng.random() < 0.05 else []))}
        if rng.random() < 0.6:
            end["offset"] = rng.choice([0, 10, -10, 25.5, 100])
        return end

    def constraint():
        t = rng.choices(["spansBetween", "attachedTo", "distance", "equalSpacing", "weird"], [4, 3, 3, 2, 0.3])[0]
        c: dict = {"id": f"c{rng.randint(0, 999)}", "type": t, "field": rng.choice(FIELDS),
                   "overridden": rng.random() < 0.08}
        if t == "spansBetween":
            c["field"] = rng.choice(["width", "height", "width", "height", "thickness", "positionX"])
            c["from"], c["to"] = ref(), ref()
        elif t == "attachedTo":
            c["field"] = rng.choice(["positionX", "positionY", "positionZ", "width"])
            c["from"] = ref(allow_literal=False) if rng.random() < 0.9 else ref()
            if rng.random() < 0.92:
                c["myFace"] = rng.choice(FACES)
        elif t == "distance":
            c["field"] = rng.choice(["positionX", "positionY", "positionZ", "positionX", "width"])
            c["from"] = ref(allow_literal=False)
            if rng.random() < 0.92:
                c["myFace"] = rng.choice(FACES)
            if rng.random() < 0.93:
                c["value"] = rng.choice([0, 5, 25, 120.5, -3])
        elif t == "equalSpacing":
            c["field"] = rng.choice(["positionX", "positionY", "positionZ", "height"])
            c["from"], c["to"] = ref(allow_literal=False), ref(allow_literal=False)
            c["members"] = rng.sample(ids, rng.randint(1, min(4, n))) + (["ghost"] if rng.random() < 0.1 else [])
            c["spacingId"] = "sp"
        return c

    panels = []
    for pid in ids:
        rot = rng.choice(GRAPH_ROTATIONS)
        panels.append({
            "id": pid, "name": f"Panel {pid}", "material": "Melamine White 18mm", "quantity": 1, "thicknessAxis": "z",
            "width": round(rng.uniform(10, 1500), 3), "height": round(rng.uniform(10, 1500), 3), "thickness": 18,
            "rotation": {"x": rot[0], "y": rot[1], "z": rot[2]},
            "basePosition": {a: round(rng.uniform(-300, 800), 3) for a in "xyz"},
            "offset": {a: rng.choice([0, 0, round(rng.uniform(-100, 100), 3)]) for a in "xyz"},
            "constraints": [constraint() for _ in range(rng.choice([0, 1, 1, 2, 3]))],
            "groupId": rng.choice([None, None, "g1"]), "hidden": rng.random() < 0.1,
            "lockedMoveAxes": rng.choice([[], [], ["x"], ["y", "z"], ["x", "bogus"]]),
        })
    rng.shuffle(panels)
    return panels
