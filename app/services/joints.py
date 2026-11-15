"""PHYSICAL JOINT DETECTION — port of the modeller's engine/joints.js (`detectJoints`, `detectFeatureJoints`).

geometric contact != physical connection. This layer only answers "where do these resolved panels actually
touch, and what kind of contact is it"; it never decides what hardware a joint needs (that is the next
stage, hardware selection).

Every panel is an axis-aligned box (angled joinery is unsupported by the resolver), so a joint reduces to two
boxes adjacent along ONE axis (the contact axis) with their footprints overlapping on the other two:
  face_to_face  both panels' thickness axis == contact axis (broad face on broad face)
  corner_butt   exactly one panel's thickness axis == contact axis; the other meets it edge-first, at the
  t_butt        flat panel's boundary (corner) or mid-span, away from its edges (T)
  edge_to_edge  neither thickness axis == contact axis (detected, status 'unhandled')
  near_contact  within `nearContactToleranceMm` along the axis but not touching
True 3-D interpenetration is NOT a joint: it goes to `collisions`.

Input of detect_joints is the RESOLVED graph (app/services/resolve.py). detect_feature_joints (door hinges,
drawer slides) reads construction intent from the RAW nodes and geometry from the resolved ones.
"""
from __future__ import annotations

import math
from typing import Any

from ..schemas.panels import RawPanelNode
from .geometry import AXES, LOCAL_FACES, dim_field_for_axis, get_aligned_axis, world_half_extents

OTHER_AXES = {"x": ("y", "z"), "y": ("x", "z"), "z": ("x", "y")}

# All distances in mm (modeller DEFAULT_OPTIONS).
CONTACT_EPSILON_MM = 0.05        # within this of zero gap = a true, flush touch
NEAR_CONTACT_TOLERANCE_MM = 3.0  # beyond touching but still worth flagging as near_contact
MIN_CONTACT_LENGTH_MM = 5.0      # a footprint overlap this small is a corner graze, not a contact face
BOUNDARY_TOLERANCE_MM = 0.5      # classify_butt_geometry only
COLLISION_MIN_MM = 1.0           # real overlap on EVERY axis beyond this = interpenetration, not a joint

Box = dict[str, tuple[float, float]]


def _aabb(panel: dict[str, Any]) -> Box:
    half = world_half_extents(panel)
    return {a: (panel["position"][a] - half[a], panel["position"][a] + half[a]) for a in AXES}


def _axis_overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """> 0 overlap by that many mm; 0 touching exactly; < 0 separated by |value| mm."""
    return min(a[1], b[1]) - max(a[0], b[0])


def _boxes_overlap(a: Box, b: Box, tolerance: float) -> bool:
    return all(_axis_overlap(a[axis], b[axis]) >= tolerance for axis in AXES)


def _facing_face(panel: dict[str, Any], axis: str, other: dict[str, Any]) -> str | None:
    """Local face of `panel` pointing along `axis` toward `other`."""
    delta = other["position"][axis] - panel["position"][axis]
    toward = ((delta > 0) - (delta < 0)) or 1  # JS: Math.sign(d) || 1
    for face in LOCAL_FACES:
        aligned = get_aligned_axis(panel["rotation"], face)
        if aligned and aligned[0] == axis and aligned[1] == toward:
            return face
    return None


def _classify_butt_geometry(overlap: dict[str, list[float]], flat: Box, footprint: tuple[str, str], tol: float) -> str:
    """corner_butt vs t_butt: only a footprint axis where the contact is a PARTIAL slice of the flat panel is
    diagnostic; a slice touching one of the flat panel's own edges is a corner, one away from both is a T."""
    saw_partial = False
    for axis in footprint:
        flat_len = flat[axis][1] - flat[axis][0]
        o_min, o_max = overlap[axis]
        if abs((o_max - o_min) - flat_len) <= tol:
            continue  # spans the full flat panel: says nothing
        saw_partial = True
        if abs(o_min - flat[axis][0]) <= tol or abs(o_max - flat[axis][1]) <= tol:
            return "corner_butt"
    return "t_butt" if saw_partial else "corner_butt"


def _evaluate_axis_contact(a: dict[str, Any], b: dict[str, Any], box_a: Box, box_b: Box, axis: str) -> dict[str, Any] | None:
    """The per-axis contact test. `axis` is the candidate contact NORMAL. None = not a plausible contact plane."""
    gap = -_axis_overlap(box_a[axis], box_b[axis])
    if gap < -CONTACT_EPSILON_MM or gap > NEAR_CONTACT_TOLERANCE_MM:
        return None

    footprint = OTHER_AXES[axis]
    overlap: dict[str, list[float]] = {}
    for fa in footprint:
        if _axis_overlap(box_a[fa], box_b[fa]) < MIN_CONTACT_LENGTH_MM:
            return None  # grazes at a corner/edge only
        overlap[fa] = [max(box_a[fa][0], box_b[fa][0]), min(box_a[fa][1], box_b[fa][1])]

    status = "classified"
    if not gap <= CONTACT_EPSILON_MM:
        joint_type = "near_contact"
    else:
        flat_a = a["thicknessAxis"] == axis
        flat_b = b["thicknessAxis"] == axis
        if flat_a and flat_b:
            joint_type = "face_to_face"
        elif flat_a or flat_b:
            joint_type = _classify_butt_geometry(overlap, box_a if flat_a else box_b, footprint, BOUNDARY_TOLERANCE_MM)
        else:
            joint_type = "edge_to_edge"
            status = "unhandled"

    # World coordinate along `axis` where the contact sits: midpoint of the two panels' nearest faces.
    contact_position = (max(box_a[axis][0], box_b[axis][0]) + min(box_a[axis][1], box_b[axis][1])) / 2
    return {"type": joint_type, "status": status, "overlap": overlap,
            "gap": max(gap, 0.0), "contactPosition": contact_position}


def detect_joints(resolved: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Batch scan: every pair of visible resolved panels, keeping the tightest valid contact axis per pair.
    Returns {"joints": [...], "collisions": [...]}. Pure."""
    visible = [p for p in resolved if not p["hidden"]]  # a hidden wall has no physical presence to joint against
    boxes = {p["id"]: _aabb(p) for p in visible}
    joints: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []

    for i, a in enumerate(visible):
        for b in visible[i + 1:]:
            box_a, box_b = boxes[a["id"]], boxes[b["id"]]
            if _boxes_overlap(box_a, box_b, COLLISION_MIN_MM):
                collisions.append({
                    "panelA": a["id"], "panelB": b["id"],
                    "overlapMm": {axis: _axis_overlap(box_a[axis], box_b[axis]) for axis in AXES},
                })
                continue

            best: tuple[str, dict[str, Any]] | None = None
            for axis in AXES:
                result = _evaluate_axis_contact(a, b, box_a, box_b, axis)
                if result is not None and (best is None or result["gap"] < best[1]["gap"]):
                    best = (axis, result)
            if best is None:
                continue
            axis, result = best
            joints.append({
                "id": f"{a['id']}:{b['id']}:{axis}",
                "panelA": a["id"], "panelB": b["id"],
                "faceA": _facing_face(a, axis, b), "faceB": _facing_face(b, axis, a),
                "type": result["type"], "status": result["status"],
                "contactAxis": axis, "contactPosition": result["contactPosition"],
                "overlap": result["overlap"], "gap": result["gap"],
                "sameGroup": bool(a["groupId"]) and a["groupId"] == b["groupId"],
            })
    return {"joints": joints, "collisions": collisions}


# ----------------------------------------------------------------------------- feature joints
def detect_feature_joints(panels: list[RawPanelNode], resolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Door hinges and drawer slides: CONSTRUCTION INTENT the feature declared at creation time (door.hinge +
    boundaryIds; a drawer box panel's drawerBoxFrontId/Role + its front's boundaryIds), not rediscovered from
    contact — a drawer box side usually does NOT touch its carcass (slide clearance gap). Flags come from the RAW
    nodes; resolved data is used only for position, rotation and size."""
    by_id = {r["id"]: r for r in resolved}
    out: list[dict[str, Any]] = []

    for raw in panels:
        if not (raw.is_door and raw.boundary_ids is not None and raw.hinge and raw.normal_axis and raw.normal_axis != "y"):
            continue  # normalAxis 'y' (a lid-style door) has no vertical hinge edge
        door = by_id.get(raw.id)
        hinge_panel_id = raw.boundary_ids.get(raw.hinge)
        if door is None or not hinge_panel_id or hinge_panel_id not in by_id:
            continue
        horizontal = next(a for a in AXES if a not in (raw.normal_axis, "y"))
        half_w = door[dim_field_for_axis(raw.rotation, horizontal)] / 2
        half_h = door[dim_field_for_axis(raw.rotation, "y")] / 2
        hinge_coord = door["position"][horizontal] + (half_w if raw.hinge == "right" else -half_w)
        p1 = {**door["position"], "y": door["position"]["y"] - half_h, horizontal: hinge_coord}
        p2 = {**door["position"], "y": door["position"]["y"] + half_h, horizontal: hinge_coord}
        out.append({
            "id": f"{raw.id}:hinge", "kind": "door_hinge",
            "panelA": raw.id, "panelB": hinge_panel_id, "side": raw.hinge, "axis": raw.normal_axis,
            "p1": p1, "p2": p2, "lengthMm": math.dist((p1["x"], p1["y"], p1["z"]), (p2["x"], p2["y"], p2["z"])),
        })

    for front in panels:
        # A front with no normalAxis would make the JS emit garbage (an "undefined" coordinate): skipped here.
        if not (front.is_drawer_front and front.boundary_ids is not None and front.normal_axis):
            continue
        for side in ("left", "right"):
            boundary_id = front.boundary_ids.get(side)
            box_raw = next((p for p in panels if p.is_drawer_box_panel and p.drawer_box_front_id == front.id
                            and p.drawer_box_role == side), None)
            box = by_id.get(box_raw.id) if box_raw else None
            boundary = by_id.get(boundary_id) if boundary_id else None
            if not boundary_id or box is None or boundary is None or box_raw is None:
                continue

            # The slide's own run = the box side's depth extent along the front's normalAxis.
            half_depth = box[dim_field_for_axis(box_raw.rotation, front.normal_axis)] / 2
            p1, p2 = dict(box["position"]), dict(box["position"])
            p1[front.normal_axis] = box["position"][front.normal_axis] - half_depth
            p2[front.normal_axis] = box["position"][front.normal_axis] + half_depth

            # The ACTUAL gap between the box side's outer face and the carcass side's inner face along the
            # width axis: what a runner's own side-clearance spec has to match.
            width_axis = next(a for a in AXES if a not in (front.normal_axis, "y"))
            box_half, boundary_half = world_half_extents(box), world_half_extents(boundary)
            if side == "left":
                box_edge = box["position"][width_axis] - box_half[width_axis]
                boundary_edge = boundary["position"][width_axis] + boundary_half[width_axis]
            else:
                box_edge = box["position"][width_axis] + box_half[width_axis]
                boundary_edge = boundary["position"][width_axis] - boundary_half[width_axis]
            out.append({
                "id": f"{box_raw.id}:{boundary_id}:slide", "kind": "drawer_slide",
                "panelA": box_raw.id, "panelB": boundary_id, "side": side, "axis": front.normal_axis,
                "p1": p1, "p2": p2, "lengthMm": math.dist((p1["x"], p1["y"], p1["z"]), (p2["x"], p2["y"], p2["z"])),
                "clearanceMm": abs(box_edge - boundary_edge),
            })
    return out
