# Troubleshooting

## "It's still doing a full mesh"

Expected signs that adaptive mesh **is** active:

```
// Algorithm: bicubic.
// Adapted probe count: 4,4.          ← smaller than configured 11,11
// Adapted mesh bounds: (x1, y1), (x2, y2).   ← tighter than (5,5)..(255,255)
// Happy KAMPing!
```

If the probe walks the full bed (11×11 or 7×7 grid), one of these is wrong:

1. **`EXCLUDE_OBJECT_DEFINE` isn't in the gcode, or appears after `START_PRINT`.**
   Check the sliced gcode file directly:
   ```sh
   grep -n "EXCLUDE_OBJECT_DEFINE\|^START_PRINT" path/to/file.gcode | head
   ```
   `EXCLUDE_OBJECT_DEFINE` must appear on a line **before** `START_PRINT`. In OrcaSlicer, enable **Print Settings → Others → Output options → Label objects** to produce these lines.

2. **Override loaded in `direct mode` instead of `KAMP mode`.**
   ```sh
   ssh root@PRINTER tail -100 /mnt/UDISK/printer_data/logs/klippy.log | grep bed_mesh_override
   ```
   If it says `direct mode`, KAMP's macro isn't being loaded. Check:
   - `[include KAMP/KAMP_Settings.cfg]` in `printer.cfg`
   - `[include Adaptive_Meshing.cfg]` is uncommented inside `KAMP_Settings.cfg`
   - All three files exist in `/mnt/UDISK/printer_data/config/KAMP/`

3. **`BED_MESH_CALIBRATE deferred (no MESH_MIN/MESH_MAX supplied)` in the log.**
   This means a bare `BED_MESH_CALIBRATE` call reached our guard without going through KAMP first. Either:
   - KAMP is in `direct mode` (see above), or
   - You're calling `BED_MESH_CALIBRATE` from a macro that runs *before* KAMP's `rename_existing` takes effect (shouldn't happen in normal Klipper config flow, but custom macros might).

## "Klippy errors on startup with IndexError"

If klippy fails to start with:
```
ConfigError: ... IndexError: list index out of range
```
...it almost always means you named the config section `[bed_mesh_override]` or `[bed_mesh_something]`. Klipper's `ProfileManager` iterates `get_prefix_sections('bed_mesh')` and splits each match on whitespace — anything starting with `bed_mesh ` (with a space) or no space triggers this bug.

**Fix**: the section name **must** be `[restore_bed_mesh]` (doesn't start with `bed_mesh`). The installer writes this correctly; if you added it by hand, double-check.

## "Include file 'KAMP/Adaptive_Meshing.cfg' does not exist"

KAMP_Settings.cfg's stock include paths use `./KAMP/Adaptive_Meshing.cfg` which is relative to the top-level config directory. When the file is inside a `KAMP/` subdirectory, Klipper resolves includes relative to the including file, so the path becomes `config/KAMP/KAMP/Adaptive_Meshing.cfg` — which doesn't exist.

**Fix**: in `/mnt/UDISK/printer_data/config/KAMP/KAMP_Settings.cfg`, change `[include ./KAMP/Adaptive_Meshing.cfg]` to `[include Adaptive_Meshing.cfg]` (and same for Line_Purge). The installer does this automatically.

## "Print cancels with 'BED_MESH_CALIBRATE fail'"

Master-server watches for `[G29_TIME]Execution time:` in gcode responses as its "mesh complete" signal. If it doesn't see that, it treats the mesh call as failed and may cancel the print.

**Check**: your hijacked `G29` and `BED_MESH_CALIBRATE_START_PRINT` macros both emit:
```
M118 [G29_TIME]Execution time: 0.0 seconds, Time spent at each point: 0.0
```
If you removed or changed this line, put it back. The exact substring `[G29_TIME]Execution time:` is what master-server greps for.

## "LINE_PURGE runs at (0, 0) or a weird location"

KAMP's `LINE_PURGE` computes purge start from the object bounding box. If it ends up at `(0, 0)`, `printer.exclude_object.objects` was empty when `LINE_PURGE` ran — same root cause as the mesh going full-bed.

**Fix**: same as the mesh troubleshoot above. Make sure `EXCLUDE_OBJECT_DEFINE` is in the gcode before `START_PRINT`.

## "I need the default Creality behavior back"

Two options:

**Option A — Restore from backup** (recommended):
```sh
ssh root@PRINTER
ls /mnt/exUDISK/.system/kamp_k2_backup_*    # or /mnt/UDISK/printer_data/config/backups/
cp /mnt/exUDISK/.system/kamp_k2_backup_<DATE>/printer.cfg /mnt/UDISK/printer_data/config/
cp /mnt/exUDISK/.system/kamp_k2_backup_<DATE>/gcode_macro.cfg /mnt/UDISK/printer_data/config/
rm /usr/share/klipper/klippy/extras/restore_bed_mesh.py
rm -rf /mnt/UDISK/printer_data/config/KAMP
/etc/init.d/klipper restart
```

**Option B — Manual revert**:
- Delete `[restore_bed_mesh]` line from `printer.cfg`
- Delete `[include KAMP/KAMP_Settings.cfg]` line from `printer.cfg`
- Delete `/usr/share/klipper/klippy/extras/restore_bed_mesh.py`
- Delete `/mnt/UDISK/printer_data/config/KAMP/` directory
- Manually restore the original stock G29, BED_MESH_CALIBRATE_START_PRINT, and START_PRINT macros (you'll need a factory-clean gcode_macro.cfg as reference — one can be pulled from `/rom/usr/share/klipper/config/<your-model>/gcode_macro.cfg`)
- Restart Klippy

## "My firmware updated and the install disappeared"

Creality firmware updates occasionally wipe `/overlay`, which can take some customizations with them. The installer places backups at `/mnt/exUDISK/.system/` when the external SSD is present specifically because that location survives firmware updates.

After a firmware update that breaks the install:
```sh
cd KAMP-K2
python install_k2.py --host PRINTER_IP
```
Re-running is idempotent and safe. It'll detect what's already present and only re-apply missing pieces.

## "`install_k2.py` says anchor not found"

The installer's macro-patching uses pattern anchors that match stock K2 `gcode_macro.cfg`. If your `gcode_macro.cfg` was previously modified (by you, by another mod, by an earlier install of this fork, by a Creality firmware update that changed the stock macros), the anchors may not match. You'll see warnings like:

```
[!] START_PRINT: anchor not found, skipping mesh block insert (manual step may be needed)
```

This is recoverable:

1. Check whether the piece is already installed — search `gcode_macro.cfg` for the literal string `KAMP-K2: adaptive mesh` (inserted comment marker). If found, it's already there, warning is cosmetic.
2. If not found, follow the manual steps in [INSTALL_K2.md](INSTALL_K2.md) (Step 8) to insert the block by hand.

Future installer versions will detect more variants — please file an issue with your `gcode_macro.cfg` snippet (scrubbed of anything personal) if you hit this on a stock-ish install.

## Getting help

Open an issue at the repository with:
- Printer model
- Firmware version (touchscreen → Settings → About)
- Output of `tail -200 /mnt/UDISK/printer_data/logs/klippy.log`
- Contents of the three edited files (`printer.cfg`, `gcode_macro.cfg`, `KAMP/KAMP_Settings.cfg`) — strip any personal details
- The sliced gcode file header (first 200 lines, showing EXCLUDE_OBJECT_DEFINE placement)
