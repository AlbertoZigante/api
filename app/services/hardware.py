"""HARDWARE PLAN — port of the modeller's `buildHardwarePlan`: joints + feature joints -> hardware selection.

Input is the RAW graph (validated) plus its server-side resolution; the client never supplies joints. Anything that
matches no catalog entry (a door too thin, a drawer box too shallow, a panel under the connector's minimum) is NOT
dropped: it is reported in `unmatched`, a flag worth a person's attention, not a hidden gap.
Pure and deterministic (the JS `generatedAt` timestamp is deliberately not part of the contract).
"""
from __future__ import annotations

from typing import Any

from ..rules.hardware import select_hinge_hardware, select_panel_connector, select_runner_hardware
from ..schemas.panels import RawPanelNode
from .joints import compute_joint_extremities, detect_feature_joints, detect_joints


def _number(items: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return [{**item, "displayId": f"{prefix}{i + 1:03d}"} for i, item in enumerate(items)]


def build_hardware_plan(panels: list[RawPanelNode], resolved: list[dict[str, Any]], *,
                        joints: list[dict[str, Any]] | None = None,
                        feature_joints: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`joints` / `feature_joints` may be passed when the caller already detected them (the assembly planner does):
    detection is the expensive part and the result is the same."""
    by_id = {r["id"]: r for r in resolved}
    name_by_id = {r["id"]: r.get("name") or r["id"] for r in resolved}
    code_by_id = {p.id: p.piece_code for p in panels}

    def code_of(panel_id: str) -> str:
        code = code_by_id.get(panel_id)  # JS `??`: only null/undefined fall through, '' is kept
        return code if code is not None else name_by_id.get(panel_id, panel_id)

    def names(a: str, b: str) -> dict[str, str]:
        return {"panelA": a, "panelB": b, "panelAName": name_by_id.get(a, "?"), "panelBName": name_by_id.get(b, "?"),
                "panelACode": code_of(a), "panelBCode": code_of(b)}

    if joints is None:
        joints = detect_joints(resolved)["joints"]
    if feature_joints is None:
        feature_joints = detect_feature_joints(panels, resolved)
    hinges: list[dict[str, Any]] = []
    runners: list[dict[str, Any]] = []
    fasteners: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for fj in (j for j in feature_joints if j["kind"] == "door_hinge"):
        door = by_id.get(fj["panelA"])
        sel = select_hinge_hardware(fj, door["thickness"]) if door else None
        if sel is None:
            unmatched.append({"kind": "hinge", **names(fj["panelA"], fj["panelB"])})
            continue
        hinges.append({"kind": "hinge", **names(fj["panelA"], fj["panelB"]), "side": fj["side"],
                       "hardware": sel["hardware"], "count": sel["count"], "positions": sel["positions"]})

    for fj in (j for j in feature_joints if j["kind"] == "drawer_slide"):
        box = by_id.get(fj["panelA"])
        sel = select_runner_hardware(fj, box["thickness"]) if box else None
        if sel is None:
            unmatched.append({"kind": "runner", **names(fj["panelA"], fj["panelB"])})
            continue
        runners.append({"kind": "runner", **names(fj["panelA"], fj["panelB"]), "side": fj["side"],
                        "hardware": sel["hardware"], "nominalLengthMm": sel["nominalLengthMm"]})

    for joint in (j for j in joints if j["type"] in ("corner_butt", "t_butt")):
        a, b = by_id.get(joint["panelA"]), by_id.get(joint["panelB"])
        if a is None or b is None:
            continue
        sel = select_panel_connector(joint, compute_joint_extremities(joint), min(a["thickness"], b["thickness"]))
        base = {"jointId": joint["id"], "jointType": joint["type"], **names(joint["panelA"], joint["panelB"])}
        if sel is None:
            unmatched.append({"kind": "fastener", **base})
            continue
        fasteners.append({"kind": "fastener", **base, "hardware": sel["hardware"], "positions": sel["positions"]})

    hinges, runners, fasteners = _number(hinges, "HG"), _number(runners, "RN"), _number(fasteners, "FS")
    return {
        "summary": {
            "hingeCount": len(hinges),
            "totalHingeUnits": sum(h["count"] for h in hinges),
            "runnerCount": len(runners),
            "fastenerJointCount": len(fasteners),
            "totalFastenerCount": sum(len(f["positions"]) for f in fasteners),
            "unmatchedCount": len(unmatched),
        },
        "hinges": hinges, "runners": runners, "fasteners": fasteners, "unmatched": unmatched,
    }
