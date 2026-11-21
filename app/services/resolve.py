"""THE CONSTRAINT RESOLVER — port of the modeller's snap.js `resolveConstraints`.

Input: the RAW panel graph (literal values + optional constraints). Output: one dict per panel, same order,
where every dimension and position is a concrete number. The server runs this itself so it never has to
trust a client-resolved geometry.

It reproduces the JS behaviour exactly, including its failure handling: a constraint that cannot be applied
never raises — it becomes a human-readable WARNING on that panel (message text identical to the JS ones,
they are part of the contract the UI shows). Cycles are not resolved: every node in a cycle keeps its literal
values and gets a warning.

Deliberate differences (inputs the JS would crash on, rejected at the contract instead — see
schemas/panels.py): a constraint of a known type missing its required parts, or a `field` outside the six
known names, is a 422, not a TypeError-text warning.
"""
from __future__ import annotations

import math
from typing import Any

from ..schemas.panels import Constraint, ConstraintEnd, RawPanelNode
from .geometry import (
    AXES,
    DIM_FIELD_PROBE_FACE,
    FACE_TO_DIM_FIELD,
    FIELD_TO_AXIS,
    LOCAL_FACES,
    MIN_PANEL_DIM_MM,
    get_aligned_axis,
)

POSITION_FIELD = {"x": "positionX", "y": "positionY", "z": "positionZ"}
LOCK_FIELDS = ("width", "height", "thickness", "positionX", "positionY", "positionZ")


class _Failure(Exception):
    """A constraint that cannot be applied; its text becomes a warning (JS: `throw new Error(...)`)."""


def js_round(x: float) -> int:
    """JavaScript Math.round: halves round UP (Python's round() is banker's: round(30.5) == 30)."""
    return math.floor(x + 0.5)


def _js(value: Any) -> str:
    """How a JS template literal prints a value that may be missing."""
    return "undefined" if value is None else str(value)


class _Resolved:
    __slots__ = ("node", "id", "rotation", "width", "height", "thickness", "base", "position", "locked", "warnings")

    def __init__(self, node: RawPanelNode) -> None:
        self.node = node
        self.id = node.id
        self.rotation = node.rotation
        self.width, self.height, self.thickness = node.width, node.height, node.thickness
        self.base = {a: getattr(node.base_position, a) for a in AXES}
        self.position = {a: self.base[a] + (getattr(node.offset, a) or 0) for a in AXES}
        self.locked = dict.fromkeys(LOCK_FIELDS, False)
        # Move-gizmo axes the node always keeps locked (see snap.js emptyResolved).
        for axis in node.locked_move_axes:
            if axis in POSITION_FIELD:
                self.locked[POSITION_FIELD[axis]] = True
        self.warnings: list[str] = []

    def dim(self, field: str) -> float:
        return getattr(self, field)

    def to_dict(self) -> dict[str, Any]:
        n = self.node
        return {
            "id": n.id,
            "name": n.name,
            "material": n.material,
            "quantity": n.quantity,
            "rotation": {a: getattr(n.rotation, a) for a in AXES},
            "thicknessAxis": n.thickness_axis or (get_aligned_axis(n.rotation, "front") or ("z",))[0],
            "groupId": n.group_id or None,
            "resizeProxy": None,
            "hidden": bool(n.hidden),
            "width": self.width,
            "height": self.height,
            "thickness": self.thickness,
            "basePosition": dict(self.base),
            "position": dict(self.position),
            "lockedFields": dict(self.locked),
            "warnings": list(self.warnings),
        }


# ----------------------------------------------------------------------------- ordering
def _topo_sort(panels: list[RawPanelNode]) -> tuple[list[str], set[str]]:
    """Dependency order + nodes that are part of a cycle (same traversal as snap.js topoSort)."""
    by_id = {p.id for p in panels}
    deps: dict[str, dict[str, None]] = {p.id: {} for p in panels}  # insertion-ordered set
    for p in panels:
        for c in p.constraints:
            if c.overridden:
                continue
            for end in (c.from_, c.to):
                if end is not None and end.node and end.node in by_id:
                    deps[p.id][end.node] = None

    order: list[str] = []
    state: dict[str, int] = {}  # 0 unvisited, 1 visiting, 2 done
    cyclic: set[str] = set()

    def visit(node_id: str, stack: list[str]) -> None:
        s = state.get(node_id, 0)
        if s == 2:
            return
        if s == 1:
            cyclic.update(stack[stack.index(node_id):])
            return
        state[node_id] = 1
        stack.append(node_id)
        for dep in deps.get(node_id, ()):
            visit(dep, stack)
        stack.pop()
        state[node_id] = 2
        order.append(node_id)

    for p in panels:
        visit(p.id, [])
    return order, cyclic


# ----------------------------------------------------------------------------- face geometry
def _face_point_mm(ref: ConstraintEnd, axis: str, resolved: dict[str, _Resolved]) -> float:
    """World position (mm, along `axis`) of a referenced face — or the literal `mm` snapshot."""
    if ref.node is None and ref.mm is not None:
        return ref.mm
    target = resolved.get(ref.node) if ref.node is not None else None
    if target is None:
        raise _Failure(f'references missing panel "{_js(ref.node)}"')
    if ref.face not in LOCAL_FACES:
        raise _Failure(f'unknown face "{_js(ref.face)}"')
    aligned = get_aligned_axis(target.rotation, ref.face)
    if aligned is None or aligned[0] != axis:
        raise _Failure(
            f'"{ref.face}" face of {ref.node} isn\'t aligned with the {axis.upper()} axis at its '
            "current rotation — angled/non-axis-aligned relations aren't supported yet"
        )
    half = target.dim(FACE_TO_DIM_FIELD[ref.face]) / 2
    return target.position[axis] + aligned[1] * (half + (ref.offset or 0))


def _axis_for_dimension_field(r: _Resolved, field: str) -> str | None:
    probe = DIM_FIELD_PROBE_FACE.get(field)
    if probe is None:
        return None
    aligned = get_aligned_axis(r.node.rotation, probe)
    return aligned[0] if aligned else None


# ----------------------------------------------------------------------------- constraint kinds
def _apply_spans_between(c: Constraint, r: _Resolved, resolved: dict[str, _Resolved]) -> None:
    assert c.field and c.from_ and c.to  # guaranteed by the contract
    if c.field == "thickness":
        r.warnings.append("thickness is fixed by Material now — a spansBetween constraint on it is ignored")
        return
    axis = _axis_for_dimension_field(r, c.field)
    if axis is None:
        raise _Failure(f'this panel\'s own "{c.field}" doesn\'t line up with any main axis at its current rotation')
    from_mm = _face_point_mm(c.from_, axis, resolved)
    to_mm = _face_point_mm(c.to, axis, resolved)
    setattr(r, c.field, max(MIN_PANEL_DIM_MM, abs(to_mm - from_mm)))
    r.locked[c.field] = True
    # A dimension constraint also centres the node on that axis unless that axis has its own position constraint.
    position_field = POSITION_FIELD[axis]
    if not any(not k.overridden and k.field == position_field for k in r.node.constraints):
        r.position[axis] = (from_mm + to_mm) / 2


def _apply_attached_to(c: Constraint, r: _Resolved, resolved: dict[str, _Resolved]) -> None:
    assert c.field and c.from_
    axis = FIELD_TO_AXIS[c.field]
    if not c.my_face or c.my_face not in LOCAL_FACES:
        raise _Failure('missing or unknown "myFace" for attachedTo constraint')
    target_mm = _face_point_mm(c.from_, axis, resolved)
    mine = get_aligned_axis(r.rotation, c.my_face)
    if mine is None or mine[0] != axis:
        raise _Failure(
            f'this panel\'s own "{c.my_face}" face isn\'t aligned with the {axis.upper()} axis '
            "at its current rotation — angled/non-axis-aligned relations aren't supported yet"
        )
    half = r.dim(FACE_TO_DIM_FIELD[c.my_face]) / 2
    r.position[axis] = target_mm - mine[1] * half
    r.locked[c.field] = True


def _apply_distance(c: Constraint, r: _Resolved, resolved: dict[str, _Resolved]) -> None:
    """A user quote: the clear gap between an anchor face and the facing face of THIS panel (position only)."""
    assert c.field and c.from_
    axis = FIELD_TO_AXIS[c.field]
    if not c.field.startswith("position"):
        raise _Failure("a distance quote can only drive a position field, never a size")
    if not c.my_face or c.my_face not in LOCAL_FACES:
        raise _Failure('missing or unknown "myFace" for distance quote')
    if not (c.value is not None and c.value >= 0):
        raise _Failure("a distance quote needs a value of 0 mm or more")
    anchor = resolved.get(c.from_.node) if c.from_.node is not None else None
    if anchor is None:
        raise _Failure(f'references missing panel "{_js(c.from_.node)}"')
    anchor_aligned = get_aligned_axis(anchor.rotation, c.from_.face)
    mine = get_aligned_axis(r.rotation, c.my_face)
    if anchor_aligned is None or anchor_aligned[0] != axis or mine is None or mine[0] != axis:
        raise _Failure(
            f"both faces must be aligned with the {axis.upper()} axis — angled/non-axis-aligned quotes aren't supported yet"
        )
    if mine[1] != -anchor_aligned[1]:
        raise _Failure("the two faces must face each other along the quoted axis")
    anchor_mm = _face_point_mm(c.from_, axis, resolved)
    my_face_mm = anchor_mm + anchor_aligned[1] * c.value
    r.position[axis] = my_face_mm - mine[1] * (r.dim(FACE_TO_DIM_FIELD[c.my_face]) / 2)
    r.locked[c.field] = True


def _apply_equal_spacing(c: Constraint, r: _Resolved, resolved: dict[str, _Resolved]) -> None:
    """One constraint per member shelf, all sharing `spacingId`: every gap (boundary-shelf, shelf-shelf,
    shelf-boundary) becomes the same. Members deleted since are left out of the count."""
    assert c.field and c.from_ and c.to
    axis = FIELD_TO_AXIS[c.field]
    if not c.field.startswith("position"):
        raise _Failure("equal spacing can only drive a position field")
    p_a = _face_point_mm(c.from_, axis, resolved)
    p_b = _face_point_mm(c.to, axis, resolved)
    direction = 1 if p_b >= p_a else -1
    span = abs(p_b - p_a)
    members = [m for m in c.members if m in resolved]
    if r.id not in members:
        raise _Failure("is not part of its own equal-spacing set")
    index = members.index(r.id)
    thick = [resolved[m].thickness for m in members]
    total = sum(thick)
    gap = (span - total) / (len(members) + 1)
    if gap < 0:
        r.warnings.append(
            f"equal spacing: the {len(members)} shelves ({js_round(total)} mm) don't fit in {js_round(span)} mm"
        )
    before = sum(thick[:index])
    r.position[axis] = p_a + direction * (gap * (index + 1) + before + thick[index] / 2)
    r.locked[c.field] = True


_APPLY = {
    "spansBetween": _apply_spans_between,
    "attachedTo": _apply_attached_to,
    "distance": _apply_distance,
    "equalSpacing": _apply_equal_spacing,
}


# ----------------------------------------------------------------------------- entry point
def resolve_constraints(panels: list[RawPanelNode]) -> list[dict[str, Any]]:
    """Raw graph -> resolved graph (same order). Never raises on a valid PanelSet."""
    resolved = {p.id: _Resolved(p) for p in panels}
    by_id = {p.id: p for p in panels}
    order, cyclic = _topo_sort(panels)

    for node_id in order:
        node, r = by_id[node_id], resolved[node_id]
        if node_id in cyclic:
            r.warnings.append(
                "part of a circular relation (A depends on B which depends on A) — using its last literal values"
            )
            continue
        # spansBetween (dimensions) first: attachedTo / distance read the resolved dimension; sort is stable.
        for c in sorted(node.constraints, key=lambda k: 0 if k.type == "spansBetween" else 1):
            if c.overridden:
                continue
            apply = _APPLY.get(c.type)
            if apply is None:
                r.warnings.append(f'unknown constraint type "{c.type}"')
                continue
            try:
                apply(c, r, resolved)
            except _Failure as err:
                r.warnings.append(str(err))

    return [resolved[p.id].to_dict() for p in panels]
