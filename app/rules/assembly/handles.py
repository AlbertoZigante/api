"""Door / drawer-front handles as assembly hardware (port of assembly/handles.js + shared/handle.js).

A handle is bought hardware, not a panel, so the hardware plan knows nothing about it; the planner needs an entry
shaped like the hinge / runner entries so a step can carry it. Only what the entry exposes is ported from
computeHandlePlacement: the length axis ('y' vertical for a door, 'x' horizontal for a drawer front) and the bar
length; the 3-D offsets are for the modeller's scene and are not part of any response."""
from __future__ import annotations

from collections.abc import Callable
from functools import cmp_to_key
from typing import Any

from ..collation import locale_compare
from .roles import Raw

HANDLE_LENGTH_MM = 128
HANDLE_CROSS_SECTION_MM = 14
HANDLE_PROTRUSION_MM = 25


def build_handle_entries(raw_panels: list[Raw], resolved_by_id: dict[str, Any],
                         code_of: Callable[[str], str]) -> dict[str, dict[str, Any]]:
    found = []
    for raw in raw_panels:
        if not raw.get("isDoor") and not raw.get("isDrawerFront"):
            continue
        r = resolved_by_id.get(raw["id"])
        if not r or r["hidden"]:
            continue
        found.append(raw)  # computeHandlePlacement never returns null for a door / drawer front

    def cmp(a: Raw, b: Raw) -> int:
        d = (0 if a.get("isDoor") else 1) - (0 if b.get("isDoor") else 1)
        return d or locale_compare(code_of(a["id"]), code_of(b["id"]))

    found.sort(key=cmp_to_key(cmp))
    by_panel: dict[str, dict[str, Any]] = {}
    for i, raw in enumerate(found):
        by_panel[raw["id"]] = {
            "kind": "handle",
            "displayId": f"HN{i + 1:02d}",
            "panelA": raw["id"],
            "panelB": None,
            "axis": "x" if raw.get("isDrawerFront") else "y",
            "hinge": (raw.get("hinge") or "left") if raw.get("isDoor") else None,
            "hardware": {"kind": "handle", "brand": "Generic", "series": f"Bar handle {HANDLE_LENGTH_MM} mm",
                         "lengthMm": HANDLE_LENGTH_MM},
        }
    return by_panel


def describe_handle_placement(entry: dict[str, Any]) -> str:
    if entry["axis"] == "y":
        free = "left" if entry["hinge"] == "right" else "right"
        return f"vertical, on the {free} edge (opposite the hinges)"
    return "horizontal, centred on the front"
