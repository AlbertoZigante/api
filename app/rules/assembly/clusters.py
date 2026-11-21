"""Rigid sub-assemblies (connected components over STRUCTURAL joints only) and the order of the panels inside one
(port of assembly/clusters.js + clusterOrdering.js).

A cluster is an ORDERED list (breadth-first from the first panel, neighbours in joint order) — the order is part
of the output (`clusters[].panelIds`), so it is not a set.
"""
from __future__ import annotations

from collections.abc import Callable
from functools import cmp_to_key
from typing import Any

from ..collation import locale_compare
from .roles import Raw, desired_orientation, panel_priority, panel_role
from .scoring import ergonomic_step_score

Joint = dict[str, Any]


def compute_clusters(panel_ids: list[str], structural_joints: list[Joint]) -> list[list[str]]:
    adjacency: dict[str, dict[str, None]] = {pid: {} for pid in panel_ids}
    for j in structural_joints:
        if j["panelA"] in adjacency:
            adjacency[j["panelA"]][j["panelB"]] = None
        if j["panelB"] in adjacency:
            adjacency[j["panelB"]][j["panelA"]] = None
    visited: set[str] = set()
    clusters: list[list[str]] = []
    for start in panel_ids:
        if start in visited:
            continue
        cluster: list[str] = []
        queue = [start]
        visited.add(start)
        head = 0
        while head < len(queue):
            pid = queue[head]
            head += 1
            cluster.append(pid)
            for neighbour in adjacency.get(pid, {}):
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append(neighbour)
        clusters.append(cluster)
    return clusters


def make_is_same_rigid_unit(raw_by_id: dict[str, Raw]) -> Callable[[str, str], bool]:
    """Geometric contact != physical connection: a door, a drawer front, a drawer box against the carcass or a
    plinth against the carcass touch without being screwed together; only feature joints (hinge / slide) and a
    drawer box's OWN corners are real links."""
    def same(a_id: str, b_id: str) -> bool:
        a, b = raw_by_id.get(a_id), raw_by_id.get(b_id)
        if not a or not b:
            return True
        if a.get("isDoor") or b.get("isDoor"):
            return False
        if a.get("isDrawerFront") or b.get("isDrawerFront"):
            return False
        if a.get("isDrawerBoxPanel") or b.get("isDrawerBoxPanel"):
            return bool(a.get("isDrawerBoxPanel") and b.get("isDrawerBoxPanel")
                        and a.get("drawerBoxFrontId") == b.get("drawerBoxFrontId"))
        a_plinth, b_plinth = panel_role(a) == "plinth", panel_role(b) == "plinth"
        if a_plinth or b_plinth:
            return a_plinth and b_plinth
        return True
    return same


def order_cluster_panels(cluster: list[str], structural_joints: list[Joint], resolved_by_id: dict[str, Any],
                         code_of: Callable[[str], str], raw_by_id: dict[str, Raw]) -> list[dict[str, Any]]:
    """Anchor (hard role priority, then area, then code) and then, repeatedly, the best panel connected to what is
    already placed (role priority, ergonomics, most connecting joints, area, code)."""
    members = set(cluster)
    joints_by_panel: dict[str, list[Joint]] = {pid: [] for pid in cluster}
    best: dict[str, Any]
    for j in structural_joints:
        if j["panelA"] in members and j["panelB"] in members:
            joints_by_panel[j["panelA"]].append(j)
            joints_by_panel[j["panelB"]].append(j)

    def area_of(pid: str) -> float:
        r = resolved_by_id.get(pid)
        return r["width"] * r["height"] if r else 0

    def role_of(pid: str) -> str:
        return panel_role(raw_by_id.get(pid))

    def anchor_cmp(a: str, b: str) -> int:
        pa, pb = panel_priority(role_of(a)), panel_priority(role_of(b))
        if pa != pb:
            return pa - pb
        aa, ab = area_of(a), area_of(b)
        if aa != ab:
            return -1 if ab < aa else 1
        return locale_compare(code_of(a), code_of(b))

    remaining = list(cluster)
    anchor = sorted(remaining, key=cmp_to_key(anchor_cmp))[0]
    remaining.remove(anchor)
    placed = {anchor}
    last_placed = anchor
    steps = [{"newPanel": anchor, "joints": []}]

    while remaining:
        candidates: list[dict[str, Any]] = []
        for cid in remaining:
            connecting = [j for j in joints_by_panel[cid] if j["panelA"] in placed or j["panelB"] in placed]
            if connecting:
                candidates.append({"id": cid, "connecting": connecting})
        if not candidates:
            raise ValueError("order_cluster_panels: cluster is not fully connected")
        from_orientation = desired_orientation(role_of(last_placed))
        for c in candidates:  # pure function of the candidate + the last placed panel: compute once
            role = role_of(c["id"])
            c["priority"] = panel_priority(role)
            c["ergo"] = ergonomic_step_score(
                panel=raw_by_id.get(c["id"]), resolved=resolved_by_id.get(c["id"]), role=role,
                joints=c["connecting"], orientation=desired_orientation(role), from_orientation=from_orientation,
                kind="join")["score"]
            c["area"] = area_of(c["id"])

        def cand_cmp(a: dict[str, Any], b: dict[str, Any]) -> int:
            if a["priority"] != b["priority"]:
                return a["priority"] - b["priority"]
            if a["ergo"] != b["ergo"]:
                return -1 if a["ergo"] < b["ergo"] else 1
            if len(b["connecting"]) != len(a["connecting"]):
                return len(b["connecting"]) - len(a["connecting"])
            if a["area"] != b["area"]:
                return -1 if b["area"] < a["area"] else 1
            return locale_compare(code_of(a["id"]), code_of(b["id"]))

        best = sorted(candidates, key=cmp_to_key(cand_cmp))[0]
        remaining.remove(best["id"])
        placed.add(best["id"])
        last_placed = best["id"]
        steps.append({"newPanel": best["id"], "joints": best["connecting"]})
    return steps
