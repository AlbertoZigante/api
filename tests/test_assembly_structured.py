"""Phase 10 server side: every human-readable string of an assembly step has a STRUCTURED twin (verb + params,
warningCodes, component / subassemblyRef, toolCodes) that is enough to rebuild the legacy English prose exactly.

The English templates below are the reference the modeller's client templates (src/i18n/stepStrings.js) are checked
against, from the other side, by tests/stepsI18n.test.mjs on fixtures exported from this API. If a template here and
the prose in the planner ever disagree, one of the two is wrong — fixing the prose is a rules change.
"""
import random
import re
from typing import get_args

import pytest

from app.rules.assembly.ergonomics import TOOL_CATALOG, TOOL_CODES
from app.rules.assembly.human import WARNING_CODES, WARNING_TEXT, orientation_instruction, subassembly_label
from app.schemas.engine import ComponentKind, StepVerb, ToolCode, ToolNoteCode, WarningCode
from tests.golden_harness import designs, load
from tests.test_assembly_differential import cabinet_layout
from tests.test_assembly_unit import full_cabinet

JOIN = ", ".join
PLACEMENT = {"vertical_left": "vertical, on the left edge (opposite the hinges)",
             "vertical_right": "vertical, on the right edge (opposite the hinges)",
             "horizontal": "horizontal, centred on the front"}

# verb -> (description template | None, instruction template | None); None = same as the other / not used for it
EN: dict[str, tuple[str | None, str | None]] = {
    "prepare_hardware": ("Prepare {panel} with {brand} {series} hardware ({hardware}) before the panel joins the assembly.",
                         "Prepare {panel}: install {hardwareName} while the panel is separate and fully accessible."),
    "fit_guide_box_left": ("Fit drawer guide {guide} on the left side {panel}.",
                           "Fit drawer guide {guide} on the left side {panel} while it is still loose."),
    "fit_guide_box_right": ("Fit drawer guide {guide} on the right side {panel}.",
                            "Fit drawer guide {guide} on the right side {panel} while it is still loose."),
    "mount_guide_shelf": ("Mount drawer guide {guide} on {panel} before the panel joins the carcass.",
                          "Mount drawer guide {guide} on shelf {panel} while it is loose and fully accessible."),
    "mount_guide_panel": ("Mount drawer guide {guide} on {panel} before the panel joins the carcass.",
                          "Mount drawer guide {guide} on panel {panel} while it is loose and fully accessible."),
    "start_door": ("Start the door with {panel}.", None),
    "start_drawer": ("Start the drawer with {panel}.", None),
    "start_plinth": ("Start the plinth with {panel}.", None),
    "start_subassembly": ("Start the sub-assembly with {panel}.", None),
    "set_aside": ("Prepare {panel} and set it aside ready for final integration.", None),
    "place_loose": ("Place {panel} — no structural joint or hardware association found for it yet (see the known-gap note).", None),
    "attach_to": ("Attach {panel} to {others} ({jointTypes}).", None),
    "attach_plain": ("Attach {panel} to {others}.", "Attach {panel} to {others}."),
    "install_closure_back": ("Install {panel} as a back closure after all accessible internal components are in place.", None),
    "install_closure_top": ("Install {panel} as a top closure after all accessible internal components are in place.", None),
    "fit_handle_door": ("Fit handle {handle} on door {panel}.", "Fit handle {handle} ({series}) on {panel}: {placement}."),
    "fit_handle_drawer_front": ("Fit handle {handle} on drawer front {panel}.", "Fit handle {handle} ({series}) on {panel}: {placement}."),
    "fit_plinth": ("Fit the plinth ({plinthPanels}) under the finished carcass.", None),
    "fit_plinth_to": ("Fit the plinth ({plinthPanels}) under the finished carcass ({carcassPanels}).", None),
    "slide_drawer": ("Slide the drawer box ({drawerPanels}) into the carcass on its runners ({carcassPanels}).", None),
    "hang_door": ("Hang {door} on {carcass} using the pre-fitted hinges.", None),
    "install_back": (None, "Install {panel} as the back panel after all accessible internal components are installed."),
    "install_top": (None, "Install {panel} as the top panel only after the internal assembly and back panel are complete."),
    "install_vertical": (None, "Install {panel} as the vertical divider before installing the top panel."),
    "install_horizontal": (None, "Install {panel} as a horizontal shelf before closing the rear with the back panel."),
    "drawer_attach_left": (None, "Lay the drawer front {front} face down, then attach the left side {panel} to it."),
    "drawer_attach_right": (None, "Attach the right side {panel} to the drawer front {front}."),
    "drawer_attach_back": (None, "Attach the back panel {panel} between the two sides."),
    "drawer_attach_bottom": (None, "Fit the drawer bottom {panel} into the box."),
    "identify_unattached": (None, "Identify {panel} and set it aside; no assembly connection is currently modeled for this part."),
}
# keys each verb's params MUST carry (the client renders from these alone)
PARAMS: dict[str, set[str]] = {v: set(re.findall(r"\{(\w+)\}", " ".join(t for t in pair if t))) for v, pair in EN.items()}
PARAMS["fit_handle_door"] = PARAMS["fit_handle_drawer_front"] = {"handle", "panel", "series", "placement"}
for _v in ("install_back", "install_top", "install_vertical", "install_horizontal", "attach_plain"):
    PARAMS[_v] = {"panel"} if _v != "attach_plain" else {"panel", "others"}
for _v in ("drawer_attach_left", "drawer_attach_right", "drawer_attach_back", "drawer_attach_bottom"):
    PARAMS[_v] = {"panel", "front"} if _v in ("drawer_attach_left", "drawer_attach_right") else {"panel"}


def fill(template: str, params: dict) -> str:
    def val(key: str) -> str:
        v = params[key]
        if key == "placement":
            return PLACEMENT[v]
        return JOIN(v) if isinstance(v, list) else str(v)
    return re.sub(r"\{(\w+)\}", lambda m: val(m.group(1)), template)


def render_description(step: dict) -> str:
    return fill(EN[step["verb"]][0], step["params"])


def render_instruction(step: dict) -> str:
    desc, instr = EN[step["instructionVerb"]]
    return fill(instr or desc, step["params"])


def sub_name(ref: dict | None) -> str | None:
    if ref is None:
        return None
    if "role" in ref and ref["role"]:
        return subassembly_label(ref["role"], ref["ordinal"])
    if ref.get("drawers"):
        return f"Drawers {JOIN(map(str, ref['drawers']))} (×{ref['count']})"
    if ref.get("drawer") is not None:
        return f"Drawer {ref['drawer']}"
    return {"drawer": "Drawer assembly", "door": "Door assembly"}[ref["fallback"]]


def component_title(c: dict | None) -> str | None:
    if c is None:
        return None
    k = c["kind"]
    if k in ("door", "plinth"):
        return k.upper() + (f" {c['ordinal']}" if c.get("ordinal") is not None else "")
    if k == "drawer":
        return f"DRAWER {c['number']}"
    if k == "drawers":
        return f"DRAWER ×{c['count']}"
    return {"guides": "DRAWER GUIDES", "carcass": "CARCASS", "integration": "FINAL ASSEMBLY"}[k]


def component_subtitle(c: dict | None) -> str | None:
    if c and c["kind"] == "drawers":
        return f"Drawers {JOIN(map(str, c['numbers']))} are identical — build this drawer {c['count']} times"
    return None


def check_plan(plan: dict) -> int:
    """Every prose string of every step equals its structured rendering. Returns the number of steps checked."""
    for s in plan["steps"]:
        ctx = f"step {s['stepId']} {s['verb']}/{s['instructionVerb']} {s['params']}"
        assert set(s["params"]) >= PARAMS[s["verb"]], ctx
        assert render_description(s) == s["description"], ctx
        assert render_instruction(s) == s["instruction"], ctx
        assert [WARNING_TEXT[c] for c in s["warningCodes"]] == s["warnings"], ctx
        assert component_title(s["component"]) == s["componentTitle"], ctx
        assert component_subtitle(s["component"]) == s["componentSubtitle"], ctx
        assert sub_name(s["subassemblyRef"]) == s["subassemblyName"], ctx
        assert orientation_instruction(s["orientation"]) == s["orientationInstruction"], ctx
        assert s["hardwareIds"] == [h["displayId"] for h in s["hardware"]], ctx
        assert s["order"] == s["index"], ctx
        assert [t for c in s["toolCodes"] for t in [c]] == s["toolCodes"] and len(set(s["toolCodes"])) == len(s["toolCodes"])
        assert [TOOL_CATALOG[c]["note"] for c in s["toolNoteCodes"]] == s["toolNotes"], ctx
        if "completionInstruction" in s:
            assert s["completionInstruction"] == f"Sub-assembly complete: {sub_name(s['completionRef'])}. Set it aside until final integration.", ctx
        else:
            assert "completionRef" not in s
    for c in plan["clusters"]:
        assert subassembly_label(c["role"], c["ordinal"]) == c["name"]
    return len(plan["steps"])


@pytest.mark.parametrize("design", designs("assembly"))
def test_structured_wording_rebuilds_the_legacy_prose_on_every_golden(client, design):
    r = client.post("/v1/assembly", json={"panels": load(design, "raw")})
    assert check_plan(r.json()) >= (0 if design == "empty" else 1)


def test_structured_wording_rebuilds_the_legacy_prose_on_random_cabinets(client):
    rng = random.Random(11)
    seen = set()
    for design in designs("assembly"):  # the goldens cover verbs the generator does not (multi-panel doors ...)
        plan = client.post("/v1/assembly", json={"panels": load(design, "raw")}).json()
        seen |= {s["verb"] for s in plan["steps"]} | {s["instructionVerb"] for s in plan["steps"]}
    for _ in range(300):
        graph = cabinet_layout(rng)
        plan = client.post("/v1/assembly", json={"panels": graph}).json()
        check_plan(plan)
        seen |= {s["verb"] for s in plan["steps"]} | {s["instructionVerb"] for s in plan["steps"]}
    # start_door is unreachable today (a door is never joined to another panel structurally: it stays a 1-panel
    # cluster); it is kept because the JS has the branch, and covered by the template / enum tests.
    assert seen == set(EN) - {"start_door"}, f"verbs never produced: {set(EN) - seen}"


def test_full_cabinet_structured(client):
    assert check_plan(client.post("/v1/assembly", json={"panels": full_cabinet()}).json()) > 20


# ------------------------------------------------------------------ the contract enums are the single list of codes
def test_enums_match_the_rules():
    assert set(get_args(StepVerb)) == set(EN)
    assert set(get_args(WarningCode)) == set(WARNING_CODES) == set(WARNING_TEXT)
    assert set(get_args(ToolCode)) == set(TOOL_CODES)
    assert set(get_args(ToolNoteCode)) == set(TOOL_CATALOG)
    assert {c for k in TOOL_CATALOG.values() for c in k["toolCodes"]} == set(TOOL_CODES)
    assert set(get_args(ComponentKind)) == {"door", "drawer", "drawers", "plinth", "guides", "carcass", "integration"}


def test_openapi_exposes_the_enums(client):
    spec = client.get("/openapi.json").json()["components"]["schemas"]["AssemblyStep"]["properties"]
    assert set(spec["verb"]["enum"]) == set(EN)
    assert set(spec["warningCodes"]["items"]["enum"]) == set(WARNING_CODES)


def test_plan_tools_summary_codes_match_tools_summary(client):
    plan = client.post("/v1/assembly", json={"panels": full_cabinet()}).json()
    assert plan["toolsSummaryCodes"] and len(plan["toolsSummaryCodes"]) >= 3
    assert set(plan["toolsSummaryCodes"]) == {c for s in plan["steps"] for c in s["toolCodes"]}


# ------------------------------------------------------------------ the modeller's exported fixtures are current
def test_modeller_step_fixtures_are_in_sync(client):
    """3d_modeler/fixtures/api-steps is the API's own output for every golden design (scripts/export_steps_fixtures.py);
    the modeller's i18n tests render it. A planner change without re-exporting would test stale data."""
    import json

    from tests.test_joints_differential import MODELLER

    folder = MODELLER / "fixtures" / "api-steps"
    if not folder.is_dir():
        pytest.skip("modeller repo not found (MODELLER_DIR)")
    for name in designs("assembly"):
        r = client.post("/v1/assembly", json={"panels": load(name, "raw")})
        expected = json.dumps(r.json(), indent=1, sort_keys=True) + "\n"
        assert (folder / f"{name}.assembly.json").read_text(encoding="utf-8") == expected, (
            f"{name}: stale — run `python scripts/export_steps_fixtures.py --out ../3d_modeler/fixtures/api-steps`")
