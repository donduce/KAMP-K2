# Tuning guide

KAMP-K2 works out of the box with Creality's stock settings. This document covers **optional** tweaks that can make adaptive meshing more effective for your print style. Skip this if the defaults are fine — nothing here is required.

## Reduce `[bed_mesh] probe_count` for faster adaptive meshes

### TL;DR

If your `printer.cfg` has `probe_count: 11,11` (or higher) under `[bed_mesh]`, consider dropping it to `7,7`. Cuts mesh time roughly in half on full-bed prints and scales the adapted counts down proportionally for small parts.

### Why

KAMP sizes the adapted probe count as a ratio of the print-area bounding box to the full bed area, capped by your `[bed_mesh] probe_count` ceiling. A higher ceiling means more probe points for the same print area.

Example on a 255mm square bed:

| `probe_count` | Full bed | Typical part (~200×180mm) | Small part (~80×80mm) |
|---|---|---|---|
| `11,11` | 121 pts | ~10×9 = 90 pts | ~6×6 = 36 pts |
| `9,9` | 81 pts | ~7×7 = 49 pts | ~5×5 = 25 pts |
| `7,7` (stock K2 default) | 49 pts | ~6×6 = 36 pts | ~3×3 = 9 pts |
| `5,5` | 25 pts | ~4×4 = 16 pts | ~3×3 = 9 pts |

### First-layer quality considerations

**7,7 is unlikely to hurt first-layer quality on a normal K2.** Reasoning:

- 7×7 on 255mm = ~42mm point spacing. Real bed flatness variations on K2 (PEI spring steel on aluminum) happen on scales of ~50-100mm — centre bulge, corner dips, thermal deformation. Smooth gradients, not sharp features.
- `mesh_pps: 2, 2` with `algorithm: bicubic` interpolates each grid cell 2× in each axis. Effective compensation resolution is ~21mm between interpolated points.
- Creality ships 7,7 as the stock F021 default — they had access to real bed flatness data across production units and chose this value.
- For adapted small-part meshes, **probe density actually goes up**. An 80mm part at 3×3 = 27mm spacing is denser than a full-bed 7×7 at 42mm.

**When a higher probe count might help** (rare):

- Localized bed damage (dent or scratch under 25mm in size)
- Severe warp pattern you've mapped and know requires dense sampling
- Glass bed with optical irregularities

### How to change it

1. SSH into the printer or edit via Fluidd/Mainsail.
2. Open `/mnt/UDISK/printer_data/config/printer.cfg`.
3. Find the `[bed_mesh]` section:

    ```
    [bed_mesh]
    speed: 100
    mesh_min: 5,5
    mesh_max: 255,255
    probe_count: 11,11   <-- change this line
    mesh_pps: 2, 2
    fade_start: 5.0
    fade_end: 50.0
    algorithm: bicubic
    horizontal_move_z: 5
    ```

4. Change to `probe_count: 7,7` (or `9,9` if you want a middle ground).
5. `FIRMWARE_RESTART` from the gcode console, or reboot the printer.
6. Next print will show `Default probe count: 7,7` in the console during mesh generation.

### How to revert

Set it back to `11,11` (or whatever you had) and FIRMWARE_RESTART. No other changes needed — KAMP-K2 picks up the new ceiling automatically.

## Skip the mesh for tiny test prints

Pass `MESH=0` as a slicer start-gcode parameter:

```
START_PRINT EXTRUDER_TEMP=[...] BED_TEMP=[...] MESH=0
```

START_PRINT will emit `Mesh skipped (MESH=0 from slicer)` and use the previously saved default mesh (or no mesh if none saved). Useful for repeat prints of calibration models where you've already meshed recently.
