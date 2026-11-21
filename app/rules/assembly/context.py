"""Everything the stages need, computed once per call (port of assembly/context.js): the resolved graph, joints,
hardware plan, rigid clusters and the hardware that must be fitted while its panel is still loose."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import cmp_to_key
from typing import Any

from ...schemas.panels import RawPanelNode
from ...services.hardware import build_hardware_plan
from ...services.joints import detect_feature_joints, detect_joints
from ..collation import locale_compare
from .clusters import compute_clusters, make_is_same_rigid_unit, order_cluster_panels
from .handles import build_handle_entries
from .human import subassembly_label
from .roles import STRUCTURAL_JOINT_TYPES, Raw, cluster_priority, cluster_role
from .scoring import ergonomic_cluster_score

# Cluster roles built BEFORE the carcass (stages 1, 2 and 4).
EARLY_CLUSTER_ROLES = frozenset({"door", "drawer_box", "drawer_front", "plinth"})


@dataclass
class Cluster:
    ids: list[str]            # breadth-first order
    role: str
    ordinal: int
    id: str                   # SUB01, SUB02... in discovery order (before the stage sort)
    name: str
    order: list[dict[str, Any]]
    idset: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        self.idset = frozenset(self.ids)


@dataclass
class Context:
    panels: list[Raw]
    resolved: list[dict[str, Any]]
    resolved_by_id: dict[str, dict[str, Any]]
    raw_by_id: dict[str, Raw]
    name_by_id: dict[str, str]
    joints: list[dict[str, Any]]
    feature_joints: list[dict[str, Any]]
    hardware_plan: dict[str, Any]
    structural_joints: list[dict[str, Any]]
    integration_panel_ids: set[str]
    pre_install_by_panel: dict[str, list[dict[str, Any]]]
    guide_entries: list[dict[str, Any]]
    handle_by_panel: dict[str, dict[str, Any]]
    cluster_list: list[Cluster]
    cluster_of_panel: dict[str, Cluster]
    code_by_id: dict[str, str | None]

    def code_of(self, panel_id: str) -> str:
        code = self.code_by_id.get(panel_id)  # JS `??`: only null / undefined fall through
        return code if code is not None else self.name_by_id.get(panel_id, panel_id)

    def clusters_of_role(self, role: str) -> list[Cluster]:
        return [c for c in self.cluster_list if c.role == role]


def create_assembly_context(panels: list[RawPanelNode], resolved: list[dict[str, Any]]) -> Context:
    raws: list[Raw] = [p.model_dump(by_alias=True) for p in panels]
    resolved_by_id = {r["id"]: r for r in resolved}
    name_by_id = {r["id"]: r.get("name") or r["id"] for r in resolved}
    code_by_id = {p.id: p.piece_code for p in panels}

    joints = detect_joints(resolved)["joints"]
    feature_joints = detect_feature_joints(panels, resolved)
    hardware_plan = build_hardware_plan(panels, resolved, joints=joints, feature_joints=feature_joints)

    raw_by_id = {r["id"]: r for r in raws}
    same_unit = make_is_same_rigid_unit(raw_by_id)
    structural = [j for j in joints if j["type"] in STRUCTURAL_JOINT_TYPES and same_unit(j["panelA"], j["panelB"])]
    integration_ids = {pid for j in feature_joints for pid in (j["panelA"], j["panelB"])}
    visible_ids = [r["id"] for r in resolved if not r["hidden"]]
    clusters = compute_clusters(visible_ids, structural)

    pre_install: dict[str, list[dict[str, Any]]] = {}
    for h in hardware_plan["hinges"]:
        pre_install.setdefault(h["panelA"], []).append(h)  # hinge cup on the door itself
        pre_install.setdefault(h["panelB"], []).append(h)  # mounting plate on the carcass boundary panel
    guide_entries: list[dict[str, Any]] = []
    for r in hardware_plan["runners"]:
        pre_install.setdefault(r["panelA"], []).append(r)  # the drawer-box half stays with the drawer
        guide_entries.append(r)  # the carcass-side guide gets its own stage
    guide_entries.sort(key=cmp_to_key(lambda a, b: locale_compare(str(a["displayId"]), str(b["displayId"]))))

    ctx = Context(
        panels=raws, resolved=resolved, resolved_by_id=resolved_by_id, raw_by_id=raw_by_id, name_by_id=name_by_id,
        joints=joints, feature_joints=feature_joints, hardware_plan=hardware_plan, structural_joints=structural,
        integration_panel_ids=integration_ids, pre_install_by_panel=pre_install, guide_entries=guide_entries,
        handle_by_panel={}, cluster_list=[], cluster_of_panel={}, code_by_id=code_by_id,
    )
    ctx.handle_by_panel = build_handle_entries(raws, resolved_by_id, ctx.code_of)

    role_counts: Counter[str] = Counter()
    built: list[Cluster] = []
    for index, ids in enumerate(clusters):
        role = cluster_role(ids, raw_by_id)
        role_counts[role] += 1
        ordinal = role_counts[role]
        built.append(Cluster(
            ids=ids, role=role, ordinal=ordinal, id=f"SUB{index + 1:02d}", name=subassembly_label(role, ordinal),
            order=order_cluster_panels(ids, structural, resolved_by_id, ctx.code_of, raw_by_id)))

    ergo = {c.id: ergonomic_cluster_score(c.ids, raw_by_id, resolved_by_id) for c in built}

    def cluster_cmp(a: Cluster, b: Cluster) -> int:
        pa, pb = cluster_priority(a.role), cluster_priority(b.role)
        if pa != pb:
            return pa - pb
        if ergo[a.id] != ergo[b.id]:
            return -1 if ergo[a.id] < ergo[b.id] else 1
        if len(b.ids) != len(a.ids):
            return len(b.ids) - len(a.ids)
        return locale_compare(ctx.code_of(sorted(a.ids)[0]), ctx.code_of(sorted(b.ids)[0]))

    ctx.cluster_list = sorted(built, key=cmp_to_key(cluster_cmp))
    for c in ctx.cluster_list:
        for pid in c.ids:
            ctx.cluster_of_panel[pid] = c
    return ctx
