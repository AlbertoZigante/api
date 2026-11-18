"""ASSEMBLY SEQUENCING (port of engine/assembly/sequence.js + buildAssemblyPlan of engine/ergonomics.js).

Two kinds of edges: a structural Joint (corner_butt / t_butt / face_to_face) rigidly joins two panels into the same
sub-assembly, built panel by panel; a FeatureJoint (door_hinge / drawer_slide) connects two ALREADY-COMPLETE
sub-assemblies. So: cluster by structural joints only, order each cluster, then schedule integration.
Hardware that fastens onto a single panel is installed while that panel is still loose.

Stage order (always): doors+handles, drawers, guides, plinth, carcass, integration (stages.py).
"""
from __future__ import annotations

from typing import Any

from ...schemas.panels import RawPanelNode
from .context import create_assembly_context
from .emitter import StepEmitter
from .ergonomics import annotate_steps_with_tools, score_ergonomics
from .human import finalize_human_readable_model
from .stages import STAGES

PHASES = [
    {"id": "prepare", "name": "Prepare components"},
    {"id": "subassembly", "name": "Build independent sub-assemblies"},
    {"id": "internal", "name": "Build internal carcass components"},
    {"id": "closure", "name": "Close the carcass"},
    {"id": "integration", "name": "Final integration"},
]


def build_assembly_sequence(panels: list[RawPanelNode], resolved: list[dict[str, Any]]) -> dict[str, Any]:
    """`resolved` = resolve_constraints(panels). Returns {steps, clusters, stages, phases}. Pure, deterministic."""
    ctx = create_assembly_context(panels, resolved)
    emitter = StepEmitter(ctx)
    for stage_id, _name, run in STAGES:
        emitter.set_stage(stage_id)
        run(ctx, emitter)
    finalize_human_readable_model(emitter.steps)
    return {
        "steps": emitter.steps,
        "clusters": [{"id": c.id, "role": c.role, "name": c.name, "ordinal": c.ordinal, "panelIds": list(c.ids)} for c in ctx.cluster_list],
        "stages": [{"id": sid, "name": name} for sid, name, _ in STAGES],
        "phases": PHASES,
        "_resolved_by_id": ctx.resolved_by_id,
    }


def build_assembly_plan(panels: list[RawPanelNode], resolved: list[dict[str, Any]]) -> dict[str, Any]:
    """Sequence + tools + ergonomics in one pass: {steps, clusters, toolsSummary}."""
    sequence = build_assembly_sequence(panels, resolved)
    with_tools, tools_summary, tools_codes = annotate_steps_with_tools(sequence["steps"])
    ergonomics = score_ergonomics(sequence["_resolved_by_id"], sequence["steps"])
    steps = [{**s, "ergonomics": e} for s, e in zip(with_tools, ergonomics, strict=True)]
    return {"steps": steps, "clusters": sequence["clusters"], "toolsSummary": tools_summary, "toolsSummaryCodes": tools_codes}
