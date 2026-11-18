"""HARDWARE RULE REGISTRY — port of the selectors and catalogs of the modeller's engine/hardware.js.

Geometry (services/joints.py) answers "where do things meet"; this module answers "what hardware goes there and
where exactly do ITS fixings go". Every selector takes plain numbers / joint dicts, never panels, so it is testable
against hand-built inputs. Catalog entries are plain dicts in the WIRE format (camelCase): they are echoed verbatim
in responses (`hardware`), so renaming a key is a contract change.

Sourcing (same honesty as the JS): hinges and runners are modelled on Blum's published catalogue (REFERENCES below);
the carcass connector is a GENERIC confirmat screw (brand None), not a Blum product; rules of thumb (hinge count by
door height, the 10% inset) are defaults to be overridden by a construction profile later, not citations.

Any change of a number or a rule here changes responses: bump app.rules.RULES_VERSION.
"""
from __future__ import annotations

import math
from typing import Any

Point = dict[str, float]

# ----------------------------------------------------------------------------- hinges
HINGE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "blum-clip-top-blumotion-110", "brand": "Blum", "series": "CLIP top BLUMOTION", "openingDeg": 110,
        "cupDiameterMm": 35, "cupDepthMm": 13,
        "edgeDistanceMm": {"min": 3, "max": 6, "default": 5},  # [REF 1]
        "screwPatternMm": 45,  # [REF 5]
        "minDoorThicknessMm": 16, "maxDoorThicknessMm": 24,
    },
    {
        "id": "blum-clip-top-blumotion-170", "brand": "Blum", "series": "CLIP top BLUMOTION", "openingDeg": 170,
        "cupDiameterMm": 35, "cupDepthMm": 13,
        "edgeDistanceMm": {"min": 3, "max": 8, "default": 5},  # [REF 2]
        "screwPatternMm": 45,
        "minDoorThicknessMm": 16, "maxDoorThicknessMm": 24,
    },
]

HINGE_INSET_FRACTION = 0.1
HINGE_INSET_MIN_MM = 80.0
HINGE_INSET_MAX_MM = 160.0


def hinge_count_for_height(height_mm: float) -> int:
    """Rule of thumb, NOT a Blum number: 2 up to 900 mm, 3 up to 1600, 4 up to 2200, else 5."""
    if height_mm <= 900:
        return 2
    if height_mm <= 1600:
        return 3
    if height_mm <= 2200:
        return 4
    return 5


def _lerp(p1: Point, p2: Point, t: float) -> Point:
    return {a: p1[a] + (p2[a] - p1[a]) * t for a in ("x", "y", "z")}


def place_along_line(p1: Point, p2: Point, count: int, inset_mm: float) -> list[Point]:
    """`count` points along p1->p2, the outer two inset `inset_mm` from the ends, the rest evenly between."""
    length = math.dist((p1["x"], p1["y"], p1["z"]), (p2["x"], p2["y"], p2["z"]))
    if count <= 1:
        return [_lerp(p1, p2, 0.5)]
    inset_t = min(inset_mm / length, 0.5 - 1e-6)
    return [_lerp(p1, p2, inset_t + ((1 - 2 * inset_t) * i) / (count - 1)) for i in range(count)]


def select_hinge_hardware(hinge_joint: dict[str, Any], door_thickness_mm: float) -> dict[str, Any] | None:
    """Hinge model + positions for a door_hinge feature joint; None = door too thin/thick for the catalog."""
    if hinge_joint["kind"] != "door_hinge":
        return None
    hardware = next((h for h in HINGE_CATALOG
                     if h["minDoorThicknessMm"] <= door_thickness_mm <= h["maxDoorThicknessMm"]), None)
    if hardware is None:
        return None
    length = hinge_joint["lengthMm"]
    count = hinge_count_for_height(length)
    inset = min(max(length * HINGE_INSET_FRACTION, HINGE_INSET_MIN_MM), HINGE_INSET_MAX_MM)
    return {"hardware": hardware, "count": count,
            "positions": place_along_line(hinge_joint["p1"], hinge_joint["p2"], count, inset)}


# ----------------------------------------------------------------------------- drawer runners
RUNNER_CATALOG: list[dict[str, Any]] = [
    {
        "id": "blum-tandem-plus-blumotion-560h", "brand": "Blum", "series": "TANDEM plus BLUMOTION",
        "type": "wood-drawer-side-mount",
        "nominalLengthsMm": [270, 300, 350, 400, 450, 500, 550, 600, 650],  # [REF 3]
        "drawerSideThicknessMm": {"min": 11, "max": 16},  # [REF 3]
        "sideClearanceMm": 21,  # [REF 4]: inside width = opening - 42
        "minScrewsPerBracket": 2,  # [REF 6]
    },
    {
        "id": "blum-legrabox-c", "brand": "Blum", "series": "LEGRABOX", "type": "steel-profile-side-mount",
        "nominalLengthsMm": [270, 350, 400, 450, 500, 550, 600],  # [REF 7]
        "sideClearanceMm": 21,
        "minScrewsPerBracket": 3,  # [REF 8]
        "fixingScrew": "612TH wood screw",  # [REF 7]
    },
]

# Absorbs floating-point noise of the geometry only; Blum's clearance is an exact spec.
CLEARANCE_TOLERANCE_MM = 1.0


def select_runner_hardware(slide_joint: dict[str, Any], drawer_side_thickness_mm: float) -> dict[str, Any] | None:
    """Runner model + nominal length for a drawer_slide feature joint. TANDEM only takes its own wood-side
    thickness range, LEGRABOX is always a candidate; the built side clearance must match the runner's spec; the
    nominal length is the LARGEST catalog length that still fits the box depth. None = nothing fits."""
    if slide_joint["kind"] != "drawer_slide":
        return None
    def side_ok(runner: dict[str, Any]) -> bool:
        rng = runner.get("drawerSideThicknessMm")
        return rng is None or rng["min"] <= drawer_side_thickness_mm <= rng["max"]

    by_thickness = [r for r in RUNNER_CATALOG if side_ok(r)]
    if not by_thickness:
        return None
    clearance = slide_joint.get("clearanceMm")
    by_clearance = by_thickness if clearance is None else [
        r for r in by_thickness if abs(clearance - r["sideClearanceMm"]) <= CLEARANCE_TOLERANCE_MM]
    if not by_clearance:
        return None
    hardware = by_clearance[0]
    fitting = [nl for nl in hardware["nominalLengthsMm"] if nl <= slide_joint["lengthMm"]]
    if not fitting:
        return None
    return {"hardware": hardware, "nominalLengthMm": max(fitting)}


# ----------------------------------------------------------------------------- panel connectors (generic)
PANEL_CONNECTOR_CATALOG: list[dict[str, Any]] = [
    {
        "id": "generic-confirmat-7x50", "brand": None, "kind": "confirmat_screw", "diameterMm": 7, "lengthMm": 50,
        "minPanelThicknessMm": 16, "pilotHoleDiameterMm": 4.5, "clearanceHoleDiameterMm": 7,
        "edgeOffsetMm": 50, "maxSpacingMm": 150,
    },
]


def place_fasteners_along_seam(seam: dict[str, Any], edge_offset_mm: float, max_spacing_mm: float) -> list[Point]:
    """Fasteners along a joint seam, `edge_offset_mm` from each end, spaced at or under `max_spacing_mm`.
    A seam too short for both offsets gets a single centred fastener."""
    p1, p2, length = seam["p1"], seam["p2"], seam["lengthMm"]
    usable = length - 2 * edge_offset_mm
    if usable <= 0:
        return [_lerp(p1, p2, 0.5)]
    gaps = max(1, math.ceil(usable / max_spacing_mm))
    return [_lerp(p1, p2, (edge_offset_mm + (usable * i) / gaps) / length) for i in range(gaps + 1)]


def select_panel_connector(
    joint: dict[str, Any], seam: dict[str, Any], panel_thickness_mm: float
) -> dict[str, Any] | None:
    """Connector + positions for a corner_butt / t_butt joint; None for every other type or a too-thin panel."""
    if joint["type"] not in ("corner_butt", "t_butt"):
        return None
    hardware = next((c for c in PANEL_CONNECTOR_CATALOG if panel_thickness_mm >= c["minPanelThicknessMm"]), None)
    if hardware is None:
        return None
    return {"hardware": hardware,
            "positions": place_fasteners_along_seam(seam, hardware["edgeOffsetMm"], hardware["maxSpacingMm"])}


# ----------------------------------------------------------------------------- sources
REFERENCES: list[dict[str, str]] = [
    {"id": "REF 1", "claim": "CLIP top 110°/125° hinge edge distance (K): 3-6mm", "source": "Cabinet Hinge Boring Dimensions: The Five Numbers", "url": "https://www.sizemarker.com/blog/cabinet-hinge-boring-dimensions"},  # noqa: E501
    {"id": "REF 2", "claim": "CLIP top 170° hinge edge distance: 3-8mm", "source": "Blum hinge drilling locations (WoodWeb Knowledge Base)", "url": "https://woodweb.com/knowledge_base/Blum_hinge_drilling_locations.html"},  # noqa: E501
    {"id": "REF 3", "claim": "TANDEM inner-drawer runner: 11-16mm wood drawer-side thickness range; nominal lengths", "source": "Blum catalogue 2022/2023, TANDEM section", "url": "https://publications.blum.com/2022/catalogue/en/450/"},  # noqa: E501
    {"id": "REF 4", "claim": "TANDEM: inside drawer width = opening width - 42mm", "source": "TANDEM plus BLUMOTION Premium Concealed Runners for Wood Drawers (Blum brochure)", "url": "https://woodworkinstitute.com/wp-content/uploads/2024/07/Blum-Tandem-plus-Blumotion-Brochure.pdf"},  # noqa: E501
    {"id": "REF 5", "claim": "35mm cup diameter / 13mm cup depth; 45mm fixing-hole pattern shared with Hettich", "source": "Cabinet Hinge Boring Dimensions: The Five Numbers", "url": "https://www.sizemarker.com/blog/cabinet-hinge-boring-dimensions"},  # noqa: E501
    {"id": "REF 6", "claim": "TANDEM: mount each runner using at least two of the elongated holes", "source": "TANDEM plus BLUMOTION 569H/569 installation instructions", "url": "https://s1.img-b.com/build.com/mediabase/specifications/blum/1136097/blum-t65-1600-01-user-guide.pdf"},  # noqa: E501
    {"id": "REF 7", "claim": "LEGRABOX C-height nominal lengths; 612TH installation wood screw", "source": "Blum LEGRABOX cabinet/drawer profile sets sheet", "url": "https://www.wwhardware.com/media/installation/Blum-legrabox-c-height.pdf"},  # noqa: E501
    {"id": "REF 8", "claim": "LEGRABOX: minimum 3 screws per bracket", "source": "TANDEM plus BLUMOTION 562F installation instructions", "url": "https://s2.img-b.com/build.com/mediabase/specifications/blum/256205/blum_562f3810b_installation_0.pdf"},  # noqa: E501
]
