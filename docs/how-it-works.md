# How KAMP-K2 works (technical)

This doc explains the three layers of Creality K2 mesh hijacking, why each layer exists, and how KAMP-K2 threads the needle through all of them.

## The problem, layer by layer

### Layer 1 — `prtouch_v3_wrapper.so`

On any stock K2, Klipper loads `klippy/extras/prtouch_v3_wrapper.cpython-39.so` at startup. This compiled extras module registers its own `cmd_BED_MESH_CALIBRATE` **overriding the upstream handler from `bed_mesh.py`**. The wrapper's implementation:

- Ignores `MESH_MIN`, `MESH_MAX`, `PROBE_COUNT` runtime parameters.
- Runs a hardcoded full-bed mesh (7×7 on K2, 11×11 on K2 Plus).
- Crashes with `IndexError: list index out of range` at `prtouch_v3_wrapper.py:1922` when you do pass adaptive params.

So even upstream KAMP's `_BED_MESH_CALIBRATE mesh_min=X,Y mesh_max=A,B ...` calls blow up or get silently converted to a full mesh. KAMP assumes upstream `bed_mesh.BedMeshCalibrate` is present; on the K2, it isn't.

### Layer 2 — `master-server` daemon

`/usr/bin/master-server` is a Creality C++ service that orchestrates print lifecycle on behalf of the touchscreen UI and cloud. During every print's prep sequence, regardless of which slicer produced the gcode, master-server independently fires:

```
G29 BED_TEMP=NN
BED_MESH_CALIBRATE
BED_MESH_CALIBRATE_START_PRINT    (depending on code path)
BED_MESH_PROFILE LOAD=default
```

These fire **before** the slicer's own `START_PRINT` macro runs. So even a perfect slicer start-gcode that passes adaptive bounds gets pre-empted — the stock full-bed mesh has already run by the time your macro gets control.

Master-server also parses response strings. It scans for the literal text `[G29_TIME]Execution time:` as its "mesh complete" signal. If it doesn't see that substring, it treats the mesh as failed and pauses the print.

### Layer 3 — Klipper's `rename_existing` semantics

When KAMP is installed, its `Adaptive_Meshing.cfg` contains:

```
[gcode_macro BED_MESH_CALIBRATE]
rename_existing: _BED_MESH_CALIBRATE
gcode:
    ... KAMP's adaptive wrapper ...
    _BED_MESH_CALIBRATE mesh_min={x},{y} mesh_max={a},{b} ...
```

At config-load time, Klipper:
1. Looks up whatever is currently registered as `BED_MESH_CALIBRATE` (prtouch's wrapper).
2. Renames it to `_BED_MESH_CALIBRATE`.
3. Registers KAMP's macro under the name `BED_MESH_CALIBRATE`.

So KAMP becomes the user-facing entry point, and when KAMP calls `_BED_MESH_CALIBRATE`, it reaches prtouch's wrapper. But prtouch's wrapper is still the broken one — so the call still fails or does a full mesh. KAMP isn't enough on its own.

## The KAMP-K2 fix

Three additive pieces, each tackling one layer.

### Piece 1 — `restore_bed_mesh.py`

A Klipper extras module that runs at `klippy:connect` (after config-load completes) and:

1. Looks up the real upstream handler — `bed_mesh.bmc.cmd_BED_MESH_CALIBRATE`. This is the actual `BedMeshCalibrate.cmd_BED_MESH_CALIBRATE` from upstream `bed_mesh.py`; it's still there as a Python method on the `bmc` attribute of the `bed_mesh` object, even though the gcode name `BED_MESH_CALIBRATE` was stolen by prtouch then renamed by KAMP.
2. Wraps it with a guard: calls with `MESH_MIN` / `MESH_MAX` pass through; bare calls are no-op'd with a log message.
3. **Detects KAMP**: if a gcode_macro named `BED_MESH_CALIBRATE` exists (KAMP's wrapper), `restore_bed_mesh` registers its guard as `_BED_MESH_CALIBRATE` — overriding the prtouch wrapper that KAMP renamed to that name. KAMP stays the user-facing entry, and its inner call now reaches our guarded upstream instead of prtouch.
4. Without KAMP: registers the guard as `BED_MESH_CALIBRATE` directly.

The section name `[restore_bed_mesh]` is deliberately chosen to **not** start with `bed_mesh` — Klipper's `bed_mesh.ProfileManager.__init__` iterates `config.get_prefix_sections('bed_mesh')` and splits each section name on spaces. A section like `[bed_mesh_override]` matches the prefix and crashes with `IndexError` on the split. `restore_bed_mesh` doesn't match, so we dodge this.

### Piece 2 — G29 and BED_MESH_CALIBRATE_START_PRINT macro hijacks

Master-server's pre-slicer firing of `G29 BED_TEMP=NN` and `BED_MESH_CALIBRATE_START_PRINT` happens outside KAMP's reach (those names aren't what KAMP wraps). We replace both with no-op macros that:

- Clear any existing mesh (harmless, quick).
- Respond with a fake `[G29_TIME]Execution time: 0.0 seconds, Time spent at each point: 0.0` line.

That's the exact substring master-server scans for. It thinks the mesh succeeded; we haven't actually done one. The real mesh runs later, inside our slicer-controlled `START_PRINT`, where KAMP has access to exclude_object metadata.

### Piece 3 — `START_PRINT` integration

Stock K2 `START_PRINT` doesn't call `BED_MESH_CALIBRATE` directly — the mesh was always done via the master-server-fired path. KAMP-K2 inserts a bare `BED_MESH_CALIBRATE` call inside `START_PRINT`, after the prepare/homing sequence. With KAMP in place, that bare call dispatches to KAMP's macro, which:

1. Reads `printer.exclude_object.objects` (populated from `EXCLUDE_OBJECT_DEFINE` lines that appeared earlier in the sliced gcode).
2. Computes adapted `mesh_min` / `mesh_max` from the union bounding box of the objects' polygons, with `mesh_margin` applied.
3. Calls `_BED_MESH_CALIBRATE mesh_min=X,Y mesh_max=A,B ALGORITHM=bicubic PROBE_COUNT=N,M`.

That `_BED_MESH_CALIBRATE` call is now our guarded upstream handler (Piece 1). It sees the `MESH_MIN` / `MESH_MAX` params, lets the call through, and upstream Klipper's real `BedMeshCalibrate.cmd_BED_MESH_CALIBRATE` runs — probing just the objects' area.

Then `LINE_PURGE` runs immediately after temps are reached, drawing a purge line along the print area's edge instead of a static always-same-spot line. Same adaptive-bounds logic as the mesh, just applied to purging instead of probing.

## The flow end to end

On a print start:

```
Touchscreen [Print] ⟶ master-server
  master-server fires G29 BED_TEMP=NN
    → G29 macro (hijacked) → BED_MESH_CLEAR, fake [G29_TIME], done in ~10ms
  master-server fires BED_MESH_CALIBRATE_START_PRINT
    → macro (hijacked) → BED_MESH_CLEAR, fake [G29_TIME], done in ~10ms
  master-server fires BED_MESH_PROFILE LOAD=default
    → harmless (just loads whatever mesh is stored, which was cleared; no-op effectively)
  master-server fires START_PRINT EXTRUDER_TEMP=... BED_TEMP=...
    → START_PRINT macro begins:
       G28 → prtouch's Z home runs → its internal probe happens (brief, ≤10 points)
       ... temps reach print set points ...
       BED_MESH_CALIBRATE (bare)
         → KAMP wrapper
           → reads exclude_object.objects (populated from gcode EXCLUDE_OBJECT_DEFINE at top of file)
           → calculates adapted bounds from object polygons
           → _BED_MESH_CALIBRATE mesh_min=X,Y mesh_max=A,B ...
             → restore_bed_mesh guard
               → MESH_MIN/MAX present → upstream bed_mesh.BedMeshCalibrate.cmd_BED_MESH_CALIBRATE
                 → real adaptive probe walks just the print area (takes ~30-40s instead of ~100s)
       LINE_PURGE
         → draws purge line at object edge instead of a fixed position
       ... slicer's gcode body begins, first layer prints ...
```

Everything is still under Creality's print-state supervision (master-server watches responses, power-loss recovery, etc.); we just narrowly redirected two commands to get the adaptive behaviour upstream Klipper always supported.

## Why this is reversible

Nothing in this fork modifies:
- Any `.so` binary
- Any compiled klipper internals
- The `bed_mesh` module itself
- The prtouch wrapper

All changes are:
- **Additive**: one new Python file (`restore_bed_mesh.py`), three new config files (the KAMP ones), three macro replacements, one include line in `printer.cfg`.
- **Live-overridable**: `restore_bed_mesh.py` calls `register_command` at `klippy:connect`; delete the file and the section, restart Klippy, and prtouch's `BED_MESH_CALIBRATE` is back as before.

The installer saves a full backup of `printer.cfg` and `gcode_macro.cfg` before making any changes. Pointing `git diff` at them will show exactly what changed.

## Why no `Smart_Park`

Upstream KAMP's Smart_Park parks the nozzle near the first-layer starting coordinate to let it reach temperature without drooling on a random spot. The K2's `BOX_GO_TO_EXTRUDE_POS` macro (part of Creality's CFS filament-change flow) already moves to a sensible location (`X=115, Y=291.5` on K2 Plus — over the filament waste area) during print prep. Adding Smart_Park means moving the nozzle **back** into the print area before the first layer, which is redundant — the slicer's gcode will move there anyway as the first non-purge operation.

If you have a specific reason to enable Smart_Park, uncomment the `[include Smart_Park.cfg]` line in `KAMP_Settings.cfg` post-install and add `SMART_PARK` at the top of your `START_PRINT` body.
