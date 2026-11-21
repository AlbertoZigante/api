"""The six build stages, in the order a person builds the furniture (port of assembly/stages/*.js):

  1 doors        door panels (+ hinge cups), then their handles
  2 drawers      drawer boxes (+ runner half on the box sides), fronts, then handles; identical drawers once, x N
  3 guides       carcass-side drawer guides, mounted on the still-loose side / shelf panels
  4 plinth       plinth panels, built as their own frame
  5 carcass      everything else: bottom -> verticals -> shelves -> back -> top
  6 integration  plinth fitted, drawers slid in, doors hung (hinges last)

Nothing from a later stage is ever emitted before an earlier one.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from ..collation import locale_compare
from ..js import js_round
from .context import EARLY_CLUSTER_ROLES, Cluster, Context
from .emitter import StepEmitter
from .handles import describe_handle_placement
from .roles import STRUCTURAL_JOINT_TYPES, desired_orientation, role_of_step_panel

Partial = dict[str, Any]


# ----------------------------------------------------------------------------- shared cluster emission
def emit_cluster_steps(ctx: Context, em: StepEmitter, cluster: Cluster) -> None:
    """Hardware that must go on a panel before its first joint, then the panel's own join / start step."""
    order = cluster.order
    for entry in order:
        new_panel, connecting = entry["newPanel"], entry["joints"]
        role = role_of_step_panel(new_panel, ctx.raw_by_id)
        code = ctx.code_of(new_panel)
        pre = ctx.pre_install_by_panel.get(new_panel)

        for hw in pre or []:
            spec = hw["hardware"]
            brand = spec.get("brand") if spec.get("brand") is not None else "Generic"
            label = spec.get("series") if spec.get("series") is not None else spec.get("kind")
            em.emit({
                "verb": "prepare_hardware",
                "params": {"panel": code, "brand": brand, "series": label, "hardware": hw["displayId"],
                           "hardwareName": hw.get("displayId") or spec.get("series") or spec.get("kind") or "hardware"},
                "kind": "pre_install", "phase": "prepare", "panelIds": [new_panel], "otherPanelIds": [],
                "jointIds": [], "hardware": [hw], "orientation": desired_orientation(role),
                "description": f"Prepare {code} with {brand} {label} hardware ({hw['displayId']}) before the panel joins the assembly.",
            })

        if not connecting:
            has_others = len(order) > 1
            known_future = bool(pre) or new_panel in ctx.integration_panel_ids or role == "plinth"
            if has_others:
                what = "door" if role == "door" else "drawer" if role == "drawer_box" else "plinth" if role == "plinth" else "sub-assembly"
                description = f"Start the {what} with {code}."
                verb = {"door": "start_door", "drawer": "start_drawer", "plinth": "start_plinth"}.get(what, "start_subassembly")
            elif known_future:
                description = f"Prepare {code} and set it aside ready for final integration."
                verb = "set_aside"
            else:
                description = f"Place {code} — no structural joint or hardware association found for it yet (see the known-gap note)."
                verb = "place_loose"
            attached = has_others or known_future
            em.emit({
                "verb": verb, "params": {"panel": code},
                "kind": "join" if attached else "unattached",
                "phase": ("subassembly" if role in ("door", "drawer_box") else "internal") if attached else "unattached",
                "panelIds": [new_panel], "otherPanelIds": [], "jointIds": [], "hardware": [],
                "orientation": desired_orientation(role), "description": description,
            })
        else:
            joint_ids = {j["id"] for j in connecting}
            fasteners = [f for f in ctx.hardware_plan["fasteners"] if f["jointId"] in joint_ids]
            others = list(dict.fromkeys(i for j in connecting for i in (j["panelA"], j["panelB"]) if i != new_panel))
            closure = role in ("back", "top")
            em.emit({
                "verb": ("install_closure_back" if role == "back" else "install_closure_top") if closure else "attach_to",
                "params": ({"panel": code} if closure else
                           {"panel": code, "others": [ctx.code_of(i) for i in others],
                            "jointTypes": [j["type"] for j in connecting]}),
                "kind": "join",
                "phase": "closure" if closure else ("internal" if role in ("vertical", "horizontal") else "subassembly"),
                "panelIds": [new_panel], "otherPanelIds": others, "jointIds": [j["id"] for j in connecting],
                "hardware": fasteners, "jointObjects": connecting, "orientation": desired_orientation(role),
                "description": (f"Install {code} as a {role} closure after all accessible internal components are in place."
                                if closure else
                                f"Attach {code} to {', '.join(ctx.code_of(i) for i in others)} ({', '.join(j['type'] for j in connecting)})."),
            })


def emit_handle_step(ctx: Context, em: StepEmitter, panel_id: str, repeat_hardware: list[dict[str, Any]] | None = None) -> None:
    """Handle step for ONE door / drawer front, after the panel itself is built (handles go on while the front is
    still flat and off the furniture). `repeat_hardware` (drawers) is the identical twins' handles, and is present
    on the step — even when empty — only for drawers, exactly as in the JS."""
    handle = ctx.handle_by_panel.get(panel_id)
    if not handle:
        return
    what = "door" if ctx.raw_by_id.get(panel_id, {}).get("isDoor") else "drawer front"
    code = ctx.code_of(panel_id)
    placement = ("vertical_left" if handle["hinge"] == "right" else "vertical_right") if handle["axis"] == "y" else "horizontal"
    partial: Partial = {
        "verb": "fit_handle_door" if what == "door" else "fit_handle_drawer_front",
        "params": {"handle": handle["displayId"], "panel": code, "series": handle["hardware"]["series"],
                   "placement": placement},
        "warningCodes": ["handle_fit_flat"],
        "kind": "fit_handle", "phase": "prepare", "action": "install", "panelIds": [panel_id], "otherPanelIds": [],
        "jointIds": [], "hardware": [handle], "orientation": "flat",
        "description": f"Fit handle {handle['displayId']} on {what} {code}.",
        "instruction": f"Fit handle {handle['displayId']} ({handle['hardware']['series']}) on {code}: {describe_handle_placement(handle)}.",
        "warnings": ["Fit the handle while the panel is flat on a protected surface."],
    }
    if repeat_hardware is not None:
        partial["repeatHardware"] = repeat_hardware
    em.emit(partial)


# ----------------------------------------------------------------------------- 1 doors
def run_doors(ctx: Context, em: StepEmitter) -> None:
    doors = ctx.clusters_of_role("door")
    for cluster in doors:
        em.set_unit({"kind": "door", "title": f"DOOR {cluster.ordinal}" if len(doors) > 1 else "DOOR",
                     "component": {"kind": "door", "ordinal": cluster.ordinal if len(doors) > 1 else None},
                     "unitPanelIds": list(cluster.ids)})
        emit_cluster_steps(ctx, em, cluster)
        for entry in cluster.order:
            emit_handle_step(ctx, em, entry["newPanel"])


# ----------------------------------------------------------------------------- 2 drawers
_BOX_ROLES = ("left", "right", "back", "bottom")


def _round1(v: Any) -> Any:
    return None if v is None else js_round(float(v) * 10) / 10  # only compared for equality


def _panel_signature(ctx: Context, pid: str) -> str:
    raw, res = ctx.raw_by_id.get(pid) or {}, ctx.resolved_by_id.get(pid) or {}
    return ":".join(str(x) for x in [
        raw.get("drawerBoxRole") or ("front" if raw.get("isDrawerFront") else "?"),
        _round1(res.get("width")), _round1(res.get("height")), _round1(res.get("thickness")),
        raw.get("material") or "", json.dumps(raw.get("bandedEdges") or []),
    ])


def _hardware_signature(entry: dict[str, Any] | None) -> str:
    if not entry:
        return "-"
    hw = entry.get("hardware") or {}
    return ":".join(str(x) for x in [hw.get("kind"), hw.get("series"), hw.get("lengthMm")])


def collect_drawer_units(ctx: Context) -> list[dict[str, Any]]:
    from functools import cmp_to_key

    front_ids = [p["id"] for p in ctx.raw_by_id.values()
                 if p.get("isDrawerFront") and ctx.resolved_by_id.get(p["id"]) and not ctx.resolved_by_id[p["id"]]["hidden"]]
    front_ids.sort(key=cmp_to_key(lambda a, b: locale_compare(ctx.code_of(str(a)), ctx.code_of(str(b)))))

    units = []
    for i, front_id in enumerate(front_ids):
        box: dict[str, str] = {}
        for p in ctx.raw_by_id.values():
            res = ctx.resolved_by_id.get(p["id"])
            if p.get("isDrawerBoxPanel") and p.get("drawerBoxFrontId") == front_id and not (res and res["hidden"]):
                box[str(p.get("drawerBoxRole"))] = p["id"]
        box_ids = [box[r] for r in _BOX_ROLES if box.get(r)]
        runner_by_side = {
            side: next((r for r in ctx.hardware_plan["runners"] if r["panelA"] == box[side]), None) if box.get(side) else None
            for side in ("left", "right")}
        handle = ctx.handle_by_panel.get(front_id)
        probe = box.get("left") or front_id
        cluster = (next((c for c in ctx.cluster_list if probe in c.idset), None)
                   or next((c for c in ctx.cluster_list if front_id in c.idset), None))
        unit = {"number": i + 1, "frontId": front_id, "box": box, "boxIds": box_ids,
                "unitPanelIds": [front_id, *box_ids], "runnerBySide": runner_by_side, "handle": handle,
                "cluster": cluster}
        unit["signature"] = "|".join([
            _panel_signature(ctx, front_id),
            *[_panel_signature(ctx, box[r]) if box.get(r) else "-" for r in _BOX_ROLES],
            _hardware_signature(runner_by_side["left"]), _hardware_signature(runner_by_side["right"]),
            _hardware_signature(handle),
        ])
        units.append(unit)
    return units


def group_identical_drawers(units: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for u in units:
        groups.setdefault(u["signature"], []).append(u)
    return list(groups.values())


def _joints_between(ctx: Context, panel_id: str, other_ids: list[str]) -> list[dict[str, Any]]:
    others = set(other_ids)
    return [j for j in ctx.joints if j["type"] in STRUCTURAL_JOINT_TYPES
            and ((j["panelA"] == panel_id and j["panelB"] in others) or (j["panelB"] == panel_id and j["panelA"] in others))]


def drawer_step_descriptors(ctx: Context, unit: dict[str, Any]) -> list[Partial]:
    """Ordered step descriptors of ONE drawer (same shape for every drawer of a group, so the Nth descriptor of the
    leader and of its twins describe the same step)."""
    front, box = unit["frontId"], unit["box"]
    front_code = ctx.code_of(front)
    out: list[Partial] = []
    placed = [front]

    for side in ("left", "right"):
        pid, runner = box.get(side), unit["runnerBySide"][side]
        if not pid or not runner:
            continue
        code = ctx.code_of(pid)
        out.append({
            "verb": f"fit_guide_box_{side}", "params": {"guide": runner["displayId"], "panel": code},
            "key": f"guide-{side}", "kind": "pre_install", "phase": "prepare", "panelIds": [pid], "otherPanelIds": [],
            "jointIds": [], "hardware": [runner], "orientation": "flat",
            "description": f"Fit drawer guide {runner['displayId']} on the {side} side {code}.",
            "instruction": f"Fit drawer guide {runner['displayId']} on the {side} side {code} while it is still loose.",
        })

    def attach(pid: str, role: str, others: list[str], instruction: str) -> None:
        joints = _joints_between(ctx, pid, others)
        joint_ids = {j["id"] for j in joints}
        out.append({
            "verb": "attach_plain", "instructionVerb": f"drawer_attach_{role}",
            "params": {"panel": ctx.code_of(pid), "others": [ctx.code_of(o) for o in others], "front": front_code},
            "key": f"attach-{role}", "kind": "join", "phase": "subassembly", "panelIds": [pid], "otherPanelIds": others,
            "jointIds": [j["id"] for j in joints],
            "hardware": [f for f in ctx.hardware_plan["fasteners"] if f["jointId"] in joint_ids],
            "jointObjects": joints, "orientation": "flat",
            "description": f"Attach {ctx.code_of(pid)} to {', '.join(ctx.code_of(o) for o in others)}.",
            "instruction": instruction,
        })
        placed.append(pid)

    if box.get("left"):
        attach(box["left"], "left", [front], f"Lay the drawer front {front_code} face down, then attach the left side {ctx.code_of(box['left'])} to it.")
    if box.get("right"):
        attach(box["right"], "right", [front], f"Attach the right side {ctx.code_of(box['right'])} to the drawer front {front_code}.")
    if box.get("back"):
        attach(box["back"], "back", [b for b in (box.get("left"), box.get("right")) if b], f"Attach the back panel {ctx.code_of(box['back'])} between the two sides.")
    if box.get("bottom"):
        attach(box["bottom"], "bottom", [p for p in placed if p != front], f"Fit the drawer bottom {ctx.code_of(box['bottom'])} into the box.")
    if unit["handle"]:
        out.append({"key": "handle", "handle": True, "panelIds": [front]})
    return out


def run_drawers(ctx: Context, em: StepEmitter) -> None:
    units = collect_drawer_units(ctx)
    claimed: set[str] = set()

    for group in group_identical_drawers(units):
        leader, twins = group[0], group[1:]
        count = len(group)
        numbers = [u["number"] for u in group]
        em.set_unit({
            "kind": "drawer",
            "title": f"DRAWER ×{count}" if count > 1 else f"DRAWER {leader['number']}",
            "subtitle": (f"Drawers {', '.join(map(str, numbers))} are identical — build this drawer {count} times"
                         if count > 1 else None),
            "component": ({"kind": "drawers", "count": count, "numbers": numbers} if count > 1
                          else {"kind": "drawer", "number": leader["number"]}),
            "subassemblyRef": ({"drawers": numbers, "count": count} if count > 1 else {"drawer": leader["number"]}),
            "unitPanelIds": leader["unitPanelIds"],
            "subassemblyId": leader["cluster"].id if leader["cluster"] else None,
            "subassemblyName": (f"Drawers {', '.join(map(str, numbers))} (×{count})" if count > 1
                                else f"Drawer {leader['number']}"),
            "repeatCount": count,
            "repeatLabels": [f"Drawer {n}" for n in numbers],
        })
        leader_steps = drawer_step_descriptors(ctx, leader)
        twin_steps = [drawer_step_descriptors(ctx, u) for u in twins]
        for i, descriptor in enumerate(leader_steps):
            if descriptor.get("handle"):
                twin_handles = [u["handle"] for u in twins if u["handle"]]
                if ctx.handle_by_panel.get(descriptor["panelIds"][0]):
                    emit_handle_step(ctx, em, descriptor["panelIds"][0], twin_handles)
                continue
            repeat = [h for steps in twin_steps if i < len(steps) for h in steps[i].get("hardware") or []]
            em.emit({**descriptor, "repeatHardware": repeat})
        for u in group:
            claimed.update(u["unitPanelIds"])

    # Fallback: drawer boxes with no front (or panels the unit builder did not claim) keep the generic build.
    em.set_unit(None)
    for cluster in ctx.clusters_of_role("drawer_box"):
        if not all(pid in claimed for pid in cluster.ids):
            emit_cluster_steps(ctx, em, cluster)


# ----------------------------------------------------------------------------- 3 guides
def run_guides(ctx: Context, em: StepEmitter) -> None:
    for runner in ctx.guide_entries:
        panel_id = runner["panelB"]
        code = ctx.code_of(panel_id)
        em.set_unit({"kind": "guides", "title": "DRAWER GUIDES", "component": {"kind": "guides"},
                     "unitPanelIds": [panel_id]})  # only this panel is drawn
        raw = ctx.raw_by_id.get(panel_id) or {}
        text = " ".join(str(x) for x in (raw.get("name"), raw.get("role")) if x)
        is_shelf = bool(re.search(r"shelf|horizontal", text, re.I))
        em.emit({
            "verb": "mount_guide_shelf" if is_shelf else "mount_guide_panel",
            "params": {"guide": runner["displayId"], "panel": code},
            "kind": "pre_install", "phase": "prepare", "panelIds": [panel_id], "otherPanelIds": [], "jointIds": [],
            "hardware": [runner], "orientation": "flat",
            "description": f"Mount drawer guide {runner['displayId']} on {code} before the panel joins the carcass.",
            "instruction": f"Mount drawer guide {runner['displayId']} on {'shelf' if is_shelf else 'panel'} {code} while it is loose and fully accessible.",
        })


# ----------------------------------------------------------------------------- 4 plinth
def run_plinth(ctx: Context, em: StepEmitter) -> None:
    plinths = ctx.clusters_of_role("plinth")
    for cluster in plinths:
        em.set_unit({"kind": "plinth", "title": f"PLINTH {cluster.ordinal}" if len(plinths) > 1 else "PLINTH",
                     "component": {"kind": "plinth", "ordinal": cluster.ordinal if len(plinths) > 1 else None},
                     "unitPanelIds": list(cluster.ids)})
        emit_cluster_steps(ctx, em, cluster)


# ----------------------------------------------------------------------------- 5 carcass
def run_carcass(ctx: Context, em: StepEmitter) -> None:
    for cluster in ctx.cluster_list:
        if cluster.role not in EARLY_CLUSTER_ROLES:
            emit_cluster_steps(ctx, em, cluster)


# ----------------------------------------------------------------------------- 6 integration
def _fit_plinth(ctx: Context, em: StepEmitter) -> None:
    carcass = [c for c in ctx.cluster_list if c.role == "carcass"]
    in_carcass = lambda pid: any(pid in c.idset for c in carcass)  # noqa: E731
    for plinth in ctx.clusters_of_role("plinth"):
        # Real contacts between this plinth and the carcass (kept out of the rigid clusters on purpose).
        touching = [j for j in ctx.joints if j["type"] in STRUCTURAL_JOINT_TYPES and (
            (j["panelA"] in plinth.idset and j["panelB"] not in plinth.idset and in_carcass(j["panelB"]))
            or (j["panelB"] in plinth.idset and j["panelA"] not in plinth.idset and in_carcass(j["panelA"])))]
        carcass_ids = list(dict.fromkeys(i for j in touching for i in (j["panelA"], j["panelB"]) if i not in plinth.idset))
        if not carcass_ids:
            carcass_ids = [pid for c in carcass for pid in c.ids
                           if (ctx.raw_by_id.get(pid) or {}).get("isBottom") or (ctx.raw_by_id.get(pid) or {}).get("role") == "bottom"
                           or re.search(r"bottom", (ctx.raw_by_id.get(pid) or {}).get("name") or "", re.I)]
        touching_ids = {j["id"] for j in touching}
        fasteners = [f for f in ctx.hardware_plan["fasteners"] if f["jointId"] in touching_ids]
        tail = f" ({', '.join(ctx.code_of(i) for i in carcass_ids)})" if carcass_ids else ""
        em.emit({
            "verb": "fit_plinth_to" if carcass_ids else "fit_plinth",
            "params": {"plinthPanels": [ctx.code_of(i) for i in plinth.ids],
                       "carcassPanels": [ctx.code_of(i) for i in carcass_ids]},
            "subassemblyRef": {"role": plinth.role, "ordinal": plinth.ordinal},
            "kind": "integrate", "phase": "integration", "orientation": "upright",
            "panelIds": [*plinth.ids, *carcass_ids], "otherPanelIds": [], "jointIds": [j["id"] for j in touching],
            "hardware": fasteners, "jointObjects": touching, "subassemblyId": plinth.id, "subassemblyName": plinth.name,
            "integrationSubassemblyIds": [plinth.id, *[c.id for c in carcass]],
            "description": f"Fit the plinth ({', '.join(ctx.code_of(i) for i in plinth.ids)}) under the finished carcass{tail}.",
        })


def _slide_in_drawers(ctx: Context, em: StepEmitter) -> None:
    groups: dict[tuple[str, str], tuple[Cluster | None, list[dict[str, Any]]]] = {}
    for j in ctx.feature_joints:
        if j["kind"] != "drawer_slide":
            continue
        cluster = ctx.cluster_of_panel.get(j["panelA"])
        key = ("cluster", cluster.id) if cluster else ("panel", j["panelA"])
        groups.setdefault(key, (cluster, []))[1].append(j)
    carcass_ids = [c.id for c in ctx.cluster_list if c.role == "carcass"]
    for meta, group in groups.values():
        slide_ids = {j["id"] for j in group}
        runners = [r for r in ctx.hardware_plan["runners"] if f"{r['panelA']}:{r['panelB']}:slide" in slide_ids]
        drawer_ids = list(dict.fromkeys(j["panelA"] for j in group))
        carcass_panel_ids = list(dict.fromkeys(j["panelB"] for j in group))
        em.emit({
            "verb": "slide_drawer",
            "params": {"drawerPanels": [ctx.code_of(i) for i in drawer_ids],
                       "carcassPanels": [ctx.code_of(i) for i in carcass_panel_ids]},
            "subassemblyRef": ({"role": meta.role, "ordinal": meta.ordinal} if meta else {"fallback": "drawer"}),
            "kind": "integrate", "phase": "integration", "orientation": "upright",
            "panelIds": [*drawer_ids, *carcass_panel_ids], "otherPanelIds": [], "jointIds": [j["id"] for j in group],
            "hardware": runners, "jointObjects": group,
            "subassemblyId": meta.id if meta else None, "subassemblyName": meta.name if meta else "Drawer assembly",
            "integrationSubassemblyIds": [i for i in [meta.id if meta else None, *carcass_ids] if i],
            "description": f"Slide the drawer box ({', '.join(ctx.code_of(i) for i in drawer_ids)}) into the carcass on its runners ({', '.join(ctx.code_of(i) for i in carcass_panel_ids)}).",
        })


def _hang_doors(ctx: Context, em: StepEmitter) -> None:
    for j in ctx.feature_joints:
        if j["kind"] != "door_hinge":
            continue
        hinges = [h for h in ctx.hardware_plan["hinges"] if f"{h['panelA']}:hinge" == j["id"]]
        door, carcass = ctx.cluster_of_panel.get(j["panelA"]), ctx.cluster_of_panel.get(j["panelB"])
        em.emit({
            "verb": "hang_door", "params": {"door": ctx.code_of(j["panelA"]), "carcass": ctx.code_of(j["panelB"])},
            "subassemblyRef": {"role": door.role, "ordinal": door.ordinal} if door else {"fallback": "door"},
            "kind": "integrate", "phase": "integration", "orientation": "upright",
            "subassemblyId": door.id if door else None, "subassemblyName": door.name if door else "Door assembly",
            "integrationSubassemblyIds": [c.id for c in (door, carcass) if c],
            "panelIds": [j["panelA"], j["panelB"]], "otherPanelIds": [], "jointIds": [j["id"]],
            "hardware": hinges, "jointObjects": [j],
            "description": f"Hang {ctx.code_of(j['panelA'])} on {ctx.code_of(j['panelB'])} using the pre-fitted hinges.",
        })


def run_integration(ctx: Context, em: StepEmitter) -> None:
    _fit_plinth(ctx, em)
    _slide_in_drawers(ctx, em)
    _hang_doors(ctx, em)  # hinges always last


STAGES: list[tuple[str, str, Callable[[Context, StepEmitter], None]]] = [
    ("doors", "Doors & handles", run_doors),
    ("drawers", "Drawer boxes, fronts & handles", run_drawers),
    ("guides", "Drawer guides on carcass panels", run_guides),
    ("plinth", "Plinth", run_plinth),
    ("carcass", "Main carcass", run_carcass),
    ("integration", "Final integration", run_integration),
]
