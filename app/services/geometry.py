"""Face / axis vocabulary and rotation maths — port of the geometry half of the modeller's modules.js.

Panels live in a local frame (width along X, height along Y, thickness along Z). A panel's six faces are
named in that local frame; its `rotation` (DEGREES, three.js Euler order XYZ) says how that frame sits in
the world. Everything the resolver needs from that is "which WORLD axis does this face point along, and
with which sign" — or None when the panel is at an arbitrary angle (angled joinery is unsupported).
"""
from __future__ import annotations

import math
from typing import Any

MIN_PANEL_DIM_MM = 10.0

LOCAL_FACES: dict[str, tuple[int, int, int]] = {
    "right": (1, 0, 0),   # +width axis
    "left": (-1, 0, 0),
    "top": (0, 1, 0),     # +height axis
    "bottom": (0, -1, 0),
    "front": (0, 0, 1),   # +thickness axis — the "show" face
    "back": (0, 0, -1),
}

# Which of a panel's own dimension fields a local face belongs to (right/left sit at +-width/2, ...).
FACE_TO_DIM_FIELD = {
    "right": "width", "left": "width",
    "top": "height", "bottom": "height",
    "front": "thickness", "back": "thickness",
}

# World axis of a constrainable field (position fields only; sizes depend on rotation, see DIM_FIELD_PROBE_FACE).
FIELD_TO_AXIS = {
    "width": "x", "height": "y", "thickness": "z",
    "positionX": "x", "positionY": "y", "positionZ": "z",
}

# A face representative of each dimension field: the world axis it lands on tells which axis that field
# currently runs along (it depends on the rotation).
DIM_FIELD_PROBE_FACE = {"width": "right", "height": "top", "thickness": "front"}

AXES = ("x", "y", "z")
ALIGN_TOLERANCE = 0.02  # |cos| within 0.02 of 1  (~11.5 degrees)


def _euler_xyz(rx: float, ry: float, rz: float) -> tuple[tuple[float, float, float], ...]:
    """Rotation matrix of three.js `Euler(x, y, z, 'XYZ')` (Matrix4.makeRotationFromEuler)."""
    a, b = math.cos(rx), math.sin(rx)
    c, d = math.cos(ry), math.sin(ry)
    e, f = math.cos(rz), math.sin(rz)
    ae, af, be, bf = a * e, a * f, b * e, b * f
    return (
        (c * e, -c * f, d),
        (af + be * d, ae - bf * d, -b * c),
        (bf - ae * d, be + af * d, a * c),
    )


def _component(rotation: Any, axis: str) -> float:
    """One Euler component (degrees) of a Rotation3 model OR a plain {x, y, z} dict (resolved output)."""
    if rotation is None:
        return 0.0
    value = rotation.get(axis, 0) if isinstance(rotation, dict) else getattr(rotation, axis, 0)
    return math.radians(value or 0)


def get_aligned_axis(rotation: Any, face: str | None) -> tuple[str, int] | None:
    """(axis, sign) the face's WORLD normal lands on, or None if it is not axis-aligned.
    `rotation` is a Rotation3 / anything with .x/.y/.z, a {x, y, z} dict (all degrees), or None."""
    local = LOCAL_FACES.get(face) if face is not None else None
    if local is None:
        return None
    rx, ry, rz = (_component(rotation, a) for a in AXES)
    m = _euler_xyz(rx, ry, rz)
    lx, ly, lz = local
    world = tuple(row[0] * lx + row[1] * ly + row[2] * lz for row in m)
    for axis, alignment in zip(AXES, world, strict=True):
        if abs(abs(alignment) - 1) <= ALIGN_TOLERANCE:
            return axis, (1 if alignment >= 0 else -1)
    return None


def world_half_extents(node: dict[str, Any]) -> dict[str, float]:
    """Half the panel's size along each WORLD axis (port of modules.js computeWorldHalfExtents).
    An axis no dimension lands on stays 0 (angled panels are unsupported, they degenerate rather than raise).
    As in the JS, a later dimension overwrites an earlier one if two land on the same axis."""
    half = dict.fromkeys(AXES, 0.0)
    for field in ("width", "height", "thickness"):
        aligned = get_aligned_axis(node["rotation"], DIM_FIELD_PROBE_FACE[field])
        if aligned:
            half[aligned[0]] = node[field] / 2
    return half


def dim_field_for_axis(rotation: Any, axis: str | None) -> str:
    """Which of width/height/thickness governs a world axis for a rotation (frontFit.js dimFieldForAxis)."""
    right = get_aligned_axis(rotation, "right")
    if right and right[0] == axis:
        return "width"
    top = get_aligned_axis(rotation, "top")
    if top and top[0] == axis:
        return "height"
    return "thickness"
