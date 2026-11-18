"""Turns the stages' partial step descriptions into full AssemblyStep dicts (port of assembly/stepEmitter.js):
index, ids, wording, ergonomics, orientation / reposition tracking. Owns the running step list."""
from __future__ import annotations

from typing import Any

from ..js import js_round
from .context import Context
from .human import action_for_step, human_instruction, instruction_verb, warning_codes_for_step, warnings_for_step
from .roles import desired_orientation, role_of_step_panel
from .scoring import ergonomic_step_score

# Section title of the steps that are not a single component.
STAGE_TITLES = {"guides": "DRAWER GUIDES", "carcass": "CARCASS", "integration": "FINAL ASSEMBLY"}


def _reposition_cost(frm: str | None, to: str | None) -> int:
    if not frm or not to or frm == to or frm == "unknown" or to == "unknown":
        return 0
    return 1


class StepEmitter:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.steps: list[dict[str, Any]] = []
        self._index = 1
        self._orientation = "flat"
        self._stage: str | None = None
        self._unit: dict[str, Any] | None = None  # the component under construction (door, drawer...) or None

    def set_stage(self, stage_id: str) -> None:
        self._stage, self._unit = stage_id, None

    def set_unit(self, unit: dict[str, Any] | None) -> None:
        self._unit = unit

    def _push(self, partial: dict[str, Any]) -> None:
        ctx = self.ctx
        primary_id = partial["panelIds"][0] if partial.get("panelIds") else None
        sub = ctx.cluster_of_panel.get(primary_id) if primary_id is not None else None
        role = partial.get("role") or role_of_step_panel(primary_id, ctx.raw_by_id)
        index = self._index
        self._index += 1
        panel_codes = [ctx.code_of(i) for i in partial["panelIds"]]
        instruction = partial.get("instruction")
        if instruction is None:
            instruction = human_instruction(
                kind=partial["kind"], phase=partial["phase"], role=role,
                panel_code=panel_codes[0] if panel_codes else "",
                other_codes=[ctx.code_of(i) for i in partial.get("otherPanelIds") or []],
                hardware=partial.get("hardware"), description=partial["description"])
        action = partial.get("action")
        sub_id = partial.get("subassemblyId")
        sub_name = partial.get("subassemblyName")
        other_codes = [ctx.code_of(i) for i in partial.get("otherPanelIds") or []]
        verb = partial["verb"]
        i_verb = partial.get("instructionVerb") or (
            verb if partial.get("instruction") is not None
            else instruction_verb(kind=partial["kind"], phase=partial["phase"], role=role, other_codes=other_codes, verb=verb))
        derived = {
            "stepId": f"S{index:02d}",
            "order": index,
            "instructionVerb": i_verb,
            "warningCodes": list(dict.fromkeys([*(partial.get("warningCodes") or []),
                                                *warning_codes_for_step(kind=partial["kind"], phase=partial["phase"], role=role)])),
            "hardwareIds": [h["displayId"] for h in partial.get("hardware") or []],
            "role": role,
            "action": action if action is not None else action_for_step(partial["kind"], partial["phase"], role),
            "subassemblyId": sub_id if sub_id is not None else (sub.id if sub else None),
            "subassemblyName": sub_name if sub_name is not None else (sub.name if sub else None),
            "instruction": instruction,
            "warnings": list(dict.fromkeys([*(partial.get("warnings") or []),
                                            *warnings_for_step(kind=partial["kind"], phase=partial["phase"], role=role)])),
            "prerequisiteStepIds": partial.get("prerequisiteStepIds") or [],
            "subassemblyComplete": False,
        }
        self.steps.append({
            "index": index,
            "panelNames": [ctx.name_by_id.get(i, "?") for i in partial["panelIds"]],
            "panelCodes": panel_codes,
            **derived, **partial,
            **derived,  # the derived human-readable fields stay authoritative after the spread
        })

    def emit(self, partial: dict[str, Any]) -> None:
        ctx = self.ctx
        primary_id = partial["panelIds"][0] if partial.get("panelIds") else None
        primary_panel = ctx.raw_by_id.get(primary_id) if primary_id is not None else None
        primary_resolved = ctx.resolved_by_id.get(primary_id) if primary_id is not None else None
        primary_role = role_of_step_panel(primary_id, ctx.raw_by_id)
        orientation = partial.get("orientation") or desired_orientation(primary_role)
        cost = _reposition_cost(self._orientation, orientation)
        ergonomic = ergonomic_step_score(
            panel=primary_panel, resolved=primary_resolved, role=primary_role,
            joints=partial.get("jointObjects") or [], orientation=orientation,
            from_orientation=self._orientation, kind=partial.get("kind"))
        ergonomic["reposition"] = max(ergonomic["reposition"], cost * 2)
        ergonomic["score"] = js_round((ergonomic["score"] + cost * 4) * 10) / 10
        if orientation != "unknown":
            self._orientation = orientation
        primary_sub = ctx.cluster_of_panel.get(primary_id) if primary_id is not None else None

        unit = self._unit
        kind = partial.get("kind")
        default_phase = "integration" if kind == "integrate" else "prepare" if kind == "pre_install" else "subassembly"
        # Structured twin of the name: first source that supplies a NAME also supplies the reference.
        sources = [(partial.get("subassemblyName"), partial.get("subassemblyRef")),
                   ((unit or {}).get("subassemblyName"), (unit or {}).get("subassemblyRef")),
                   (primary_sub.name if primary_sub else None,
                    {"role": primary_sub.role, "ordinal": primary_sub.ordinal} if primary_sub else None)]
        sub_ref = next((ref for name, ref in sources if name is not None), None)
        component = (unit or {}).get("component") or ({"kind": self._stage} if self._stage in STAGE_TITLES else None)
        self._push({
            "component": component,
            "subassemblyRef": sub_ref,
            "componentKind": (unit or {}).get("kind") or self._stage,
            "componentTitle": (unit or {}).get("title") or STAGE_TITLES.get(self._stage or "") or None,
            "componentSubtitle": (unit or {}).get("subtitle"),
            # Panels shown in the manual diagram for this step; None = whole furniture.
            "unitPanelIds": (unit or {}).get("unitPanelIds"),
            "repeatCount": (unit or {}).get("repeatCount") or 1,
            "repeatLabels": (unit or {}).get("repeatLabels"),
            "phase": partial.get("phase") or default_phase,
            "stage": self._stage,
            "orientation": orientation,
            "requiresReposition": cost > 0,
            "repositionCost": cost,
            "ergonomic": ergonomic,
            "subassemblyId": _first((partial.get("subassemblyId")), (unit or {}).get("subassemblyId"),
                                    primary_sub.id if primary_sub else None),
            "subassemblyName": _first(partial.get("subassemblyName"), (unit or {}).get("subassemblyName"),
                                      primary_sub.name if primary_sub else None),
            "clusterKind": _first(partial.get("clusterKind"), primary_sub.role if primary_sub else None),
            **partial,
        })


def _first(*values: Any) -> Any:
    """JS `a ?? b ?? ... ?? null`."""
    return next((v for v in values if v is not None), None)
