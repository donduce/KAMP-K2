#!/usr/bin/env python3
"""
KAMP-K2 slicer start-gcode generator.

Emits the exact "Machine start G-code" block users need to paste into their
slicer after installing KAMP-K2. Handles placeholder-syntax differences
between Orca/Bambu and Prusa/Super, and includes the matching bed-mesh
configuration hints (mesh_max differs between K2 variants).

Runs standalone (no dependencies beyond the Python stdlib):

    python3 slicer_gcode.py                    # Orca, K2/Combo/Pro defaults
    python3 slicer_gcode.py --slicer prusa     # Prusa/Super variant
    python3 slicer_gcode.py --board F008       # K2 Plus (mesh_max 345,345)
    python3 slicer_gcode.py --no-mesh          # print MESH=0 skip-mesh form
    python3 slicer_gcode.py --list             # show supported slicers

install.sh and install.ps1 call this at the end of a successful fresh
install so the user doesn't have to find the README.

Why a standalone file: install_k2.py is already 1000+ lines and talks to a
printer. This one is pure string templating; keeping it separate means
users can run it without paramiko, on any Python 3, including on the
printer's own Klipper host if they want.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from typing import Dict, NamedTuple


class SlicerSpec(NamedTuple):
    """Per-slicer placeholder syntax + where to paste the block."""
    label: str              # display name
    nozzle_temp: str        # initial-layer nozzle temp placeholder
    bed_temp: str           # initial-layer bed temp placeholder
    initial_tool: str       # active tool at print start
    paste_location: str     # UI path where the block goes
    label_objects_hint: str # UI path for the Label Objects setting
    notes: str              # slicer-specific caveats


SLICERS: Dict[str, SlicerSpec] = {
    "orca": SlicerSpec(
        label="OrcaSlicer",
        nozzle_temp="[nozzle_temperature_initial_layer]",
        bed_temp="[bed_temperature_initial_layer_single]",
        initial_tool="[initial_no_support_extruder]",
        paste_location="Printer Settings -> Machine G-code -> Machine start G-code",
        label_objects_hint="Print Settings -> Others -> Label objects (tick the checkbox)",
        notes="Fully tested. Default placeholder syntax.",
    ),
    "bambu": SlicerSpec(
        label="Bambu Studio",
        nozzle_temp="[nozzle_temperature_initial_layer]",
        bed_temp="[bed_temperature_initial_layer_single]",
        initial_tool="[initial_no_support_extruder]",
        paste_location="Printer Settings -> Machine G-code -> Machine start G-code",
        label_objects_hint="Print Settings -> Others -> Label objects (tick the checkbox)",
        notes="Same engine as Orca, placeholders identical. Untested but expected to work.",
    ),
    "prusa": SlicerSpec(
        label="PrusaSlicer",
        nozzle_temp="[first_layer_temperature_0]",
        bed_temp="[first_layer_bed_temperature]",
        initial_tool="{initial_tool}",
        paste_location="Printer Settings -> Custom G-code -> Start G-code",
        label_objects_hint="Print Settings -> Output options -> Label objects",
        notes=("Uses PrusaSlicer's placeholder syntax. The {initial_tool} "
               "curly-brace form resolves on recent PrusaSlicer (2.6+); "
               "on older versions use `T0` as a literal."),
    ),
    "super": SlicerSpec(
        label="SuperSlicer",
        nozzle_temp="[first_layer_temperature_0]",
        bed_temp="[first_layer_bed_temperature]",
        initial_tool="{initial_tool}",
        paste_location="Printer Settings -> Custom G-code -> Start G-code",
        label_objects_hint="Print Settings -> Output options -> Label objects",
        notes="PrusaSlicer fork; same placeholder syntax.",
    ),
}


# Mesh-max differs by board. mesh_min is always 5,5 on every K2 variant.
BOARD_MESH_MAX = {
    "F021": ("255, 255", "K2 / K2 Combo / K2 Pro (260 mm bed)"),
    "F008": ("345, 345", "K2 Plus (350 mm bed)"),
}


def ansi(code: str, *, enabled: bool) -> str:
    return f"\033[{code}m" if enabled else ""


def render(slicer_key: str, board: str, mesh_off: bool, color: bool) -> str:
    spec = SLICERS[slicer_key]
    mesh_max, board_label = BOARD_MESH_MAX[board]

    bold = ansi("1", enabled=color)
    cyan = ansi("36", enabled=color)
    green = ansi("32", enabled=color)
    gray = ansi("90", enabled=color)
    reset = ansi("0", enabled=color)

    # The START_PRINT line optionally gains MESH=0 to skip adaptive meshing
    # (useful for calibration prints the user doesn't want meshed).
    mesh_arg = " MESH=0" if mesh_off else ""
    start_print = (
        f"START_PRINT EXTRUDER_TEMP={spec.nozzle_temp} "
        f"BED_TEMP={spec.bed_temp}{mesh_arg}"
    )

    # Block to paste (no colour inside — users will copy this verbatim).
    gcode_block = "\n".join([
        start_print,
        f"T{spec.initial_tool}",
        "LINE_PURGE",
        "M204 S2000",
        "M83",
    ])

    # Header + footer wrap the block with colour and instructions.
    header = (
        f"{cyan}================================================================{reset}\n"
        f"{bold} KAMP-K2 start-gcode for {spec.label}{reset}"
        + (f"  {gray}(MESH=0 skip-mesh variant){reset}" if mesh_off else "")
        + f"\n"
        f"{cyan}================================================================{reset}\n"
        f"\n"
        f"{bold}Paste into:{reset} {spec.paste_location}\n"
        f"{gray}(replace any existing block -- Creality's default won't work with KAMP){reset}\n"
    )

    footer = textwrap.dedent(f"""\

        {bold}Also in your slicer:{reset}
          - {spec.label_objects_hint}
          - Bed mesh min: 5, 5
          - Bed mesh max: {mesh_max}   {gray}({board_label}){reset}
          - Probe point distance: 50, 50
          - Mesh margin: 5

        {bold}Why these exact lines, in this order:{reset}
          {gray}- START_PRINT runs heating, homing, adaptive mesh, nozzle clean.
          - T<n> triggers the CFS / direct loader to pull filament to the nozzle.
          - LINE_PURGE must come AFTER T<n> (see issue #1) -- otherwise you
            get an empty purge followed by an un-purged start.
          - M204 S2000 + M83 set accel and relative extrusion for the print.{reset}

        {bold}Slicer note:{reset}
          {gray}{spec.notes}{reset}

        {cyan}================================================================{reset}
    """)

    return header + "\n" + gcode_block + "\n" + footer


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Print KAMP-K2 slicer start-gcode ready to paste.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              slicer_gcode.py                      # Orca, K2/Combo/Pro
              slicer_gcode.py --slicer prusa       # PrusaSlicer variant
              slicer_gcode.py --board F008         # K2 Plus (mesh 345,345)
              slicer_gcode.py --no-mesh            # skip-mesh variant
              slicer_gcode.py --list               # list supported slicers
        """),
    )
    ap.add_argument("--slicer", choices=list(SLICERS), default="orca",
                    help="Slicer flavour (default: orca)")
    ap.add_argument("--board", choices=list(BOARD_MESH_MAX), default="F021",
                    help="Board variant: F021 = K2/Combo/Pro (default), "
                         "F008 = K2 Plus")
    ap.add_argument("--no-mesh", action="store_true",
                    help="Emit the MESH=0 skip-mesh variant of START_PRINT")
    ap.add_argument("--list", action="store_true",
                    help="List supported slicers and exit")
    ap.add_argument("--no-color", action="store_true",
                    help="Disable ANSI colour output")
    args = ap.parse_args()

    if args.list:
        print("Supported slicers:")
        for key, spec in SLICERS.items():
            print(f"  {key:8} {spec.label:14}  {spec.notes}")
        return 0

    # Auto-disable colour if stdout isn't a terminal (piped into a file,
    # or captured by the installer). Honour NO_COLOR too.
    import os
    color = (
        sys.stdout.isatty()
        and not args.no_color
        and "NO_COLOR" not in os.environ
    )

    sys.stdout.write(render(args.slicer, args.board, args.no_mesh, color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
