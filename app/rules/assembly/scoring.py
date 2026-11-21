"""Heuristic ergonomic scoring (port of assembly/scoring.js). Scores are 0..10 per factor, LOWER = easier for a
person. They only break ties after the hard ordering rules; they never reorder anything on their own.

NOTE (faithful to the JS, deliberately not "fixed" here): the size thresholds (area > 1.5, span > 2.0) read like
square metres / metres but the panel sizes fed in are millimetres, so every real panel counts as large. Changing
that changes step order and scores: it is a rules change (bump RULES_VERSION and regenerate the goldens)."""
from __future__ import annotations

import math
import re
from typing import Any

from ..js import js_round
from .roles import Raw, desired_orientation, panel_role


def clamp10(value: float) -> float:
    return max(0.0, min(10.0, value))


def numeric_dimension(panel: Raw | None, keys: list[str]) -> float:
    for key in keys:
        value = (panel or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
            return float(value)
    return 0.0


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 0.0


def panel_ergonomic_size(panel: Raw | None, resolved: dict[str, Any] | None) -> dict[str, float]:
    r = resolved or {}
    width = numeric_dimension(panel, ["width", "w", "lengthX"]) or _num(r.get("width"))
    height = numeric_dimension(panel, ["height", "h", "lengthY"]) or _num(r.get("height"))
    thickness = numeric_dimension(panel, ["thickness", "depth", "d"]) or _num(r.get("thickness"))
    return {"width": width, "height": height, "thickness": thickness, "area": width * height,
            "maxSpan": max(width, height)}


def ergonomic_panel_metrics(panel: Raw | None, resolved: dict[str, Any] | None) -> dict[str, Any]:
    role = panel_role(panel)
    size = panel_ergonomic_size(panel, resolved)
    area = size["area"]
    large = area > 1.5 or size["maxSpan"] > 2.0
    very_large = area > 2.5 or size["maxSpan"] > 2.5
    explicit_weight = numeric_dimension(panel, ["weight", "mass", "kg", "weightKg"])
    weight_score = (clamp10(explicit_weight / 8) if explicit_weight
                    else clamp10(area * 2.0 + (0.5 if size["thickness"] > 0.025 else 0)))
    support_score = (clamp10(1 + area * 1.5) if role in ("door", "drawer_box", "drawer_front")
                     else clamp10(0.5 + area * 1.7))
    return {"role": role, **size, "largePanel": large, "veryLargePanel": very_large,
            "weightScore": weight_score, "supportScore": support_score}


def joint_tool_access_score(joints: list[dict[str, Any]] | None) -> float:
    if not joints:
        return 0.0
    score = 0.0
    for j in joints:
        kind = str(j.get("type") or j.get("kind") or "").lower()
        if re.search(r"corner|butt|t_butt", kind):
            score += 1
        elif re.search(r"face_to_face|edge", kind):
            score += 1.5
        else:
            score += 1.25
        if re.search(r"blind|hidden|rear|inside|interior", kind):
            score += 2
    return clamp10(score / max(1, len(joints)) * 2)


def _r1(x: float) -> float:
    return js_round(x * 10) / 10


def ergonomic_step_score(*, panel: Raw | None, resolved: dict[str, Any] | None, role: str,
                         joints: list[dict[str, Any]] | None = None, orientation: str | None,
                         from_orientation: str | None, kind: str | None) -> dict[str, float]:
    m = ergonomic_panel_metrics(panel, resolved)
    reach = 5 if m["veryLargePanel"] else 3 if m["largePanel"] else 1
    tool_access = joint_tool_access_score(joints)
    support, weight = m["supportScore"], m["weightScore"]
    posture = 1.5 if orientation == "rear_access" else (3.5 if m["largePanel"] else 2) if orientation == "upright" else 1
    p = panel or {}
    two_person = (10 if p.get("requiresTwoPeople") or p.get("twoPerson") or p.get("assemblyTwoPerson")
                  else 8 if m["veryLargePanel"] else 4 if m["largePanel"] else 0)
    reposition = 2 if (from_orientation and orientation and from_orientation != orientation
                       and from_orientation != "unknown" and orientation != "unknown") else 0
    integration_penalty = 0.5 if kind == "integrate" else 0
    score = (reach * 0.20 + tool_access * 0.20 + support * 0.18 + weight * 0.16 + posture * 0.10
             + two_person * 0.10 + reposition * 0.04 + integration_penalty * 0.02) * 10
    return {"score": _r1(score), "reach": _r1(reach), "toolAccess": _r1(tool_access), "support": _r1(support),
            "weight": _r1(weight), "posture": _r1(posture), "twoPerson": _r1(two_person),
            "reposition": _r1(reposition)}


def ergonomic_cluster_score(cluster: list[str], raw_by_id: dict[str, Raw], resolved_by_id: dict[str, Any]) -> float:
    total, count = 0.0, 0
    for pid in cluster:
        p = raw_by_id.get(pid)
        if p is None:
            continue
        role = panel_role(p)
        total += ergonomic_step_score(panel=p, resolved=resolved_by_id.get(pid), role=role,
                                      orientation=desired_orientation(role), from_orientation=None,
                                      kind="join")["score"]
        count += 1
    return total / count if count else 0.0
