"""Panel roles and the stage / orientation priorities of the assembly planner (port of assembly/roles.js).

`raw` panels are plain camelCase dicts (RawPanelNode.model_dump(by_alias=True)). The role flags the JS also reads
(isBack, isTop, ... role, code) are never produced by the modeller nor accepted by the contract, so the role of a
panel comes from its feature flags or, failing that, its NAME / piece code — exactly as in the JS.
"""
from __future__ import annotations

import re
from typing import Any

Raw = dict[str, Any]

STRUCTURAL_JOINT_TYPES = frozenset({"corner_butt", "t_butt", "face_to_face"})

_PLINTH_TEXT = re.compile(r"plinth|kick[ _-]?board|toe[ _-]?kick|zoccolo")
_DRAWER_FRONT = re.compile(r"drawer[ _-]*(front|face)|front[ _-]*drawer")
_DRAWER_BOX = re.compile(r"drawer[ _-]*(box|side)|drawer")


def text_of_panel(panel: Raw | None) -> str:
    if not panel:
        return ""
    parts = [panel.get("name"), panel.get("pieceCode"), panel.get("code"), panel.get("type"), panel.get("role")]
    return " ".join(str(p) for p in parts if p).lower()


def panel_role(panel: Raw | None) -> str:
    if not panel:
        return "unknown"
    if panel.get("isDoor"):
        return "door"
    if panel.get("isDrawerFront"):
        return "drawer_front"
    if panel.get("isDrawerBoxPanel"):
        return "drawer_box"
    if panel.get("isPlinth") or panel.get("isPlinthPanel") or panel.get("role") == "plinth":
        return "plinth"
    if panel.get("isBack") or panel.get("role") == "back":
        return "back"
    if panel.get("isTop") or panel.get("role") == "top":
        return "top"
    if panel.get("isBottom") or panel.get("role") == "bottom":
        return "bottom"
    if panel.get("isVerticalDivider") or panel.get("role") == "vertical_divider":
        return "vertical"
    if panel.get("isShelf") or panel.get("role") == "horizontal_shelf":
        return "horizontal"

    t = text_of_panel(panel)
    if _DRAWER_FRONT.search(t):
        return "drawer_front"
    if _DRAWER_BOX.search(t) and re.search(r"box|side", t):
        return "drawer_box"
    if re.search(r"door", t):
        return "door"
    if _PLINTH_TEXT.search(t):
        return "plinth"
    if re.search(r"back|rear", t):
        return "back"
    if re.search(r"top|upper|roof", t):
        return "top"
    if re.search(r"bottom|base", t):
        return "bottom"
    if re.search(r"vertical|divider|partition|upright|centre.?panel|center.?panel", t):
        return "vertical"
    if re.search(r"shelf|shelves|horizontal|fixed.?shelf|adjustable.?shelf", t):
        return "horizontal"
    return "unknown"


def cluster_role(cluster: list[str], raw_by_id: dict[str, Raw]) -> str:
    roles = [panel_role(raw_by_id.get(i)) for i in cluster]
    for role in ("door", "drawer_box", "drawer_front", "plinth"):
        if all(r == role for r in roles):  # `every` is True for an empty cluster: first role wins, like the JS
            return role
    if "door" in roles:
        return "door"
    if "drawer_box" in roles:
        return "drawer_box"
    return "carcass"


def desired_orientation(role: str) -> str:
    if role in ("door", "drawer_box", "drawer_front"):
        return "flat"
    if role == "back":
        return "rear_access"
    if role == "top":
        return "upright"
    return "flat"


_PANEL_PRIORITY = {"door": 10, "drawer_box": 20, "drawer_front": 25, "plinth": 30, "bottom": 40, "vertical": 50,
                   "horizontal": 60, "unknown": 65, "back": 90, "top": 100}
_CLUSTER_PRIORITY = {"door": 10, "drawer_box": 20, "drawer_front": 25, "plinth": 35, "carcass": 40}


def panel_priority(role: str) -> int:
    return _PANEL_PRIORITY.get(role, 65)


def cluster_priority(role: str) -> int:
    return _CLUSTER_PRIORITY.get(role, 40)


def role_of_step_panel(panel_id: str | None, raw_by_id: dict[str, Raw]) -> str:
    return panel_role(raw_by_id.get(panel_id) if panel_id is not None else None)
