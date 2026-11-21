"""Human-readable wording of the steps (port of assembly/humanModel.js).

LEGACY PROSE: these strings are what the modeller shows today and what the goldens freeze. The target design
(structured verb + warningCodes, rendered by the client's i18n layer) replaces them in phase 10; until then the
port reproduces them byte for byte.
"""
from __future__ import annotations

from typing import Any

Step = dict[str, Any]


def subassembly_label(role: str, ordinal: int) -> str:
    if role == "door":
        return f"Door assembly {ordinal}"
    if role == "drawer_box":
        return f"Drawer assembly {ordinal}"
    if role == "drawer_front":
        return f"Drawer front assembly {ordinal}"
    if role == "plinth":
        return "Plinth" if ordinal == 1 else f"Plinth assembly {ordinal}"
    if role == "carcass":
        return "Main carcass" if ordinal == 1 else f"Carcass assembly {ordinal}"
    return f"Sub-assembly {ordinal}"


def action_for_step(kind: str, phase: str, role: str) -> str:
    if kind == "pre_install":
        return "prepare"
    if kind == "integrate":
        return "integrate"
    if kind == "unattached":
        return "inspect"
    if phase == "closure":
        return "close"
    if role in ("door", "drawer_box", "drawer_front", "plinth"):
        return "assemble"
    return "install"


def human_instruction(*, kind: str, phase: str, role: str, panel_code: str, other_codes: list[str],
                      hardware: list[dict[str, Any]] | None, description: str) -> str:
    if kind == "pre_install":
        hw = hardware[0] if hardware else None
        spec = (hw or {}).get("hardware") or {}
        hw_name = (hw or {}).get("displayId") or spec.get("series") or spec.get("kind") or "hardware"
        return f"Prepare {panel_code}: install {hw_name} while the panel is separate and fully accessible."
    if kind == "integrate":
        return description
    if kind == "unattached":
        return f"Identify {panel_code} and set it aside; no assembly connection is currently modeled for this part."
    if phase == "closure" and role == "back":
        return f"Install {panel_code} as the back panel after all accessible internal components are installed."
    if phase == "closure" and role == "top":
        return f"Install {panel_code} as the top panel only after the internal assembly and back panel are complete."
    if role == "vertical":
        return f"Install {panel_code} as the vertical divider before installing the top panel."
    if role == "horizontal":
        return f"Install {panel_code} as a horizontal shelf before closing the rear with the back panel."
    if kind == "join" and other_codes:
        return f"Attach {panel_code} to {', '.join(other_codes)}."
    return description


# Stable codes for every warning, with the legacy English text they replace (the client renders the codes).
WARNING_TEXT: dict[str, str] = {
    "door_build_flat": "Build the door flat before hanging it on the carcass.",
    "door_support_hinges": "Support the door while connecting the pre-fitted hinges.",
    "drawer_complete_box": "Complete the drawer box before inserting it into the carcass.",
    "vertical_before_top": "Install vertical dividers before the top panel closes access.",
    "horizontal_before_back": "Install horizontal shelves before the back panel closes rear access.",
    "back_after_internals": "Do not install the back until all required internal components are in place.",
    "top_after_internals": "Do not install the top until the internal components and back panel are complete.",
    "keep_panel_separate": "Keep the panel separate while fitting this hardware.",
    "handle_fit_flat": "Fit the handle while the panel is flat on a protected surface.",
}
WARNING_CODES = tuple(WARNING_TEXT)


def warning_codes_for_step(*, kind: str, phase: str, role: str) -> list[str]:
    codes: list[str] = []
    if role == "door":
        codes.append("door_build_flat")
        if kind == "integrate":
            codes.append("door_support_hinges")
    if role == "drawer_box":
        codes.append("drawer_complete_box")
    if role == "vertical":
        codes.append("vertical_before_top")
    if role == "horizontal":
        codes.append("horizontal_before_back")
    if role == "back":
        codes.append("back_after_internals")
    if role == "top":
        codes.append("top_after_internals")
    if kind == "pre_install":
        codes.append("keep_panel_separate")
    return list(dict.fromkeys(codes))


def warnings_for_step(*, kind: str, phase: str, role: str) -> list[str]:
    return [WARNING_TEXT[c] for c in warning_codes_for_step(kind=kind, phase=phase, role=role)]


def instruction_verb(*, kind: str, phase: str, role: str, other_codes: list[str], verb: str) -> str:
    """Which verb template renders the INSTRUCTION of a step whose wording comes from `human_instruction` (the
    mirror of its branches). The description is always rendered from `verb`."""
    if kind == "pre_install":
        return "prepare_hardware"
    if kind == "integrate":
        return verb
    if kind == "unattached":
        return "identify_unattached"
    if phase == "closure" and role == "back":
        return "install_back"
    if phase == "closure" and role == "top":
        return "install_top"
    if role == "vertical":
        return "install_vertical"
    if role == "horizontal":
        return "install_horizontal"
    if kind == "join" and other_codes:
        return "attach_plain"
    return verb


_ORIENTATION = {
    "flat": "Work with the component flat on a supported surface.",
    "rear_access": "Keep the rear/open face accessible for this operation.",
    "front_access": "Keep the front face accessible for this operation.",
    "upright": "Work with the furniture upright and stable.",
    "unknown": "Use the orientation that keeps the joint and tool access clear.",
}


def orientation_instruction(orientation: str | None) -> str:
    return _ORIENTATION.get(orientation or "", "")


def finalize_human_readable_model(steps: list[Step]) -> list[Step]:
    """Stable step ids, prerequisites, orientation text, de-duplicated warnings and the 'set it aside' boundary of
    every independent sub-assembly. Mutates and returns `steps`."""
    last_build: dict[str, Step] = {}
    for step in steps:
        if step.get("subassemblyId") and step["action"] != "integrate":
            last_build[step["subassemblyId"]] = step

    for step in steps:
        step["stepId"] = f"S{step['index']:02d}"
        step["prerequisiteStepIds"] = []
        warnings = list(step.get("warnings") or [])

        if step["action"] == "integrate" and step.get("subassemblyId"):
            for sub_id in step.get("integrationSubassemblyIds") or []:
                last = last_build.get(sub_id)
                if last and last["stepId"] != step["stepId"]:
                    step["prerequisiteStepIds"].append(last["stepId"])

        if step["role"] == "back":
            prior = [s for s in steps if s["index"] < step["index"] and s["phase"] == "internal"]
            if prior:
                step["prerequisiteStepIds"].append(prior[-1]["stepId"])
        if step["role"] == "top":
            prior = [s for s in steps if s["index"] < step["index"] and (s["role"] == "back" or s["phase"] == "internal")]
            if prior:
                step["prerequisiteStepIds"].append(prior[-1]["stepId"])

        step["prerequisiteStepIds"] = list(dict.fromkeys(step["prerequisiteStepIds"]))
        step["orientationInstruction"] = orientation_instruction(step["orientation"])
        step["warnings"] = list(dict.fromkeys(warnings))

    for step in last_build.values():
        if step["phase"] in ("subassembly", "prepare"):
            step["subassemblyComplete"] = True
            if step["action"] != "integrate":
                step["completionRef"] = step.get("subassemblyRef")
                step["completionInstruction"] = (
                    f"Sub-assembly complete: {step['subassemblyName']}. Set it aside until final integration.")
    return steps
