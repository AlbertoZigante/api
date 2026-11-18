"""Tool identification + ergonomics annotation of the sequence (port of engine/ergonomics.js).

An ANNOTATION pass over the sequence, not a second sequencer: it attaches `tools` / `toolNotes` and an
`ergonomics` block (weight, two-person, surface, single-joint caution, flip) to the order already computed.

Weights are volume x one assumed density (650 kg/m3), not looked up per material; the confirmat drive type is a
common convention, not a verified spec — both stated as such in the JS and kept.
"""
from __future__ import annotations

from typing import Any

from ..js import js_round

TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "concealed_hinge": {
        "toolCodes": ["screwdriver_pz2"],
        "tools": ["Phillips/PZ2 screwdriver (or drill/driver)"],
        "note": "Cup + fixing-hole boring is typically pre-drilled by the panel manufacturer; if boring it yourself, use a 35mm Forstner bit at the cup depth/edge distance from the hardware spec, ideally with a drill press or boring jig for accuracy.",
    },
    "drawer_runner_wood_screw": {
        "toolCodes": ["screwdriver_pz2"],
        "tools": ["Phillips/PZ2 screwdriver (or drill/driver)"],
        "note": "TANDEM mounts through its own elongated holes; LEGRABOX's 612TH screw is self-tapping. Neither needs a separate pilot hole per Blum's own installation instructions.",
    },
    "confirmat_screw": {
        "toolCodes": ["drill_bit_pilot_4_5", "drill_bit_clearance_7", "bit_pozidriv_pz3"],
        "tools": ["4.5mm drill bit (pilot hole)", "7mm drill bit or a stepped confirmat bit (clearance hole)",
                  "Pozidriv PZ3 screwdriver bit (or drill/driver)"],
        "note": "Requires a proper two-stage pilot + clearance hole (see the catalog entry's own pilotHoleDiameterMm/clearanceHoleDiameterMm) or the panel will split. Drive type (Pozidriv PZ3 here) is a common convention, not a verified spec — confirm against your specific confirmat screw brand.",
    },
}  # noqa: E501

DEFAULT_MATERIAL_DENSITY_KG_PER_M3 = 650
TWO_PERSON_THRESHOLD_KG = 20       # general manual-handling rule of thumb, not a Blum spec
FLOOR_SURFACE_THRESHOLD_KG = 10    # below: comfortable on a table; at or above: floor space


def tool_key_for_hardware_item(item: dict[str, Any]) -> str | None:
    kind = item.get("kind")
    if kind == "hinge":
        return "concealed_hinge"
    if kind == "runner":
        return "drawer_runner_wood_screw"
    if kind == "fastener":
        k = item["hardware"].get("kind")
        return k if k is not None else "confirmat_screw"
    return None


TOOL_CODES = ("screwdriver_pz2", "drill_bit_pilot_4_5", "drill_bit_clearance_7", "bit_pozidriv_pz3")
TOOL_NOTE_CODES = tuple(TOOL_CATALOG)


def annotate_steps_with_tools(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Returns (steps with tools/toolNotes + their stable codes, toolsSummary, toolsSummaryCodes)."""
    all_tools: dict[str, None] = {}
    all_codes: dict[str, None] = {}
    out = []
    for step in steps:
        keys = list(dict.fromkeys(k for k in (tool_key_for_hardware_item(h) for h in step["hardware"]) if k))
        tools = list(dict.fromkeys(t for k in keys for t in (TOOL_CATALOG.get(k) or {}).get("tools", [])))
        notes = [n for n in ((TOOL_CATALOG.get(k) or {}).get("note") for k in keys) if n]
        codes = list(dict.fromkeys(c for k in keys for c in (TOOL_CATALOG.get(k) or {}).get("toolCodes", [])))
        note_codes = [k for k in keys if (TOOL_CATALOG.get(k) or {}).get("note")]
        all_tools.update(dict.fromkeys(tools))
        all_codes.update(dict.fromkeys(codes))
        out.append({**step, "tools": tools, "toolNotes": notes, "toolCodes": codes, "toolNoteCodes": note_codes})
    return out, list(all_tools), list(all_codes)


def panel_weight_kg(resolved: dict[str, Any] | None) -> float:
    if not resolved:
        return 0.0
    volume_m3 = (resolved["thickness"] / 1000) * (resolved["width"] / 1000) * (resolved["height"] / 1000)
    return volume_m3 * DEFAULT_MATERIAL_DENSITY_KG_PER_M3


class PanelGroups:
    """Union-find over panels as steps join / integrate them, so 'how heavy is the object in your hands' stays right
    across sub-assemblies that are not integrated yet. Member order = insertion order (it fixes the float sum)."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, pid: str) -> str:
        self.parent.setdefault(pid, pid)
        root = pid
        while self.parent[root] != root:
            root = self.parent[root]
        cur = pid
        while self.parent[cur] != root:  # path compression
            nxt = self.parent[cur]
            self.parent[cur] = root
            cur = nxt
        return root

    def union(self, ids: list[str]) -> None:
        roots = [self.find(i) for i in ids]
        first = roots[0]
        for r in roots[1:]:
            if r != first:
                self.parent[r] = first

    def members_of(self, pid: str) -> list[str]:
        root = self.find(pid)
        return [k for k in list(self.parent) if self.find(k) == root]


def score_ergonomics(resolved_by_id: dict[str, dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Returns one `ergonomics` dict per step (index-aligned)."""
    groups = PanelGroups()
    last_orientation: dict[str, str] = {}
    out = []
    for step in steps:
        if step["kind"] == "join" and step["otherPanelIds"]:
            groups.union([*step["panelIds"], *step["otherPanelIds"]])
        elif step["kind"] == "integrate":
            groups.union(step["panelIds"])
        else:
            for pid in step["panelIds"]:
                groups.find(pid)

        ref = step["panelIds"][0] if step["panelIds"] else None
        members = groups.members_of(ref) if ref else []
        total = 0.0
        for i in members:  # NOT sum(): Python >= 3.12 sums floats with compensation, JS adds plainly, and an exact
            total += panel_weight_kg(resolved_by_id.get(i))  # x.x5 tie (29.25) rounds the other way
        weight = js_round(total * 10) / 10
        ergonomics: dict[str, Any] = {
            "weightKg": weight,
            "twoPersonJob": weight >= TWO_PERSON_THRESHOLD_KG,
            "recommendedSurface": "floor" if weight >= FLOOR_SURFACE_THRESHOLD_KG else "table",
        }
        if step["kind"] == "join" and step["jointIds"]:
            ergonomics["singleJointCaution"] = len(step["jointIds"]) == 1
            # jointId format is `${panelA}:${panelB}:${axis}` (detect_joints)
            axes = {(jid.split(":") + [None, None, None])[2] for jid in step["jointIds"]}
            axis = next(iter(axes)) if len(axes) == 1 else None
            ergonomics["orientationAxis"] = axis
            root = groups.find(ref) if ref else ""
            previous = last_orientation.get(root)
            ergonomics["reorientationNeeded"] = bool(axis and previous and previous != axis)
            if axis:
                last_orientation[root] = axis
        out.append(ergonomics)
    return out
