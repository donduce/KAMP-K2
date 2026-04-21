# Bed mesh override — restores upstream BED_MESH_CALIBRATE handler, with guard.
#
# Creality's prtouch_v3_wrapper.so registers its own cmd_BED_MESH_CALIBRATE
# which ignores MESH_MIN, MESH_MAX, PROBE_COUNT runtime parameters and
# crashes with IndexError when they are passed. This module re-registers
# the upstream bed_mesh.py BedMeshCalibrate.cmd_BED_MESH_CALIBRATE with a
# safety guard: bare calls (no MESH_MIN/MESH_MAX) are no-ops instead of
# triggering a default full 11x11 mesh.
#
# KAMP compat: if a gcode_macro BED_MESH_CALIBRATE is present at connect
# time (KAMP's wrapper), we override KAMP's inner rename target so KAMP
# stays the user-facing entry point and calls through to our guarded
# upstream. install_k2.py patches KAMP's Adaptive_Meshing.cfg to rename
# to `_BMC_KAMP_INNER` (unique name, avoids colliding with Creality's
# pre-registered `_BED_MESH_CALIBRATE` on some firmware variants). We
# detect which name got used (prefer `_BMC_KAMP_INNER`, fall back to the
# stock `_BED_MESH_CALIBRATE`). Without KAMP, we override BED_MESH_CALIBRATE
# directly.
#
# Why the guard: Creality's master-server daemon fires raw BED_MESH_CALIBRATE
# during print prep. Without the guard, that would run a full default mesh
# even with the override active — undoing any adaptive gain.
#
# Loaded via [restore_bed_mesh] in printer.cfg, AFTER [bed_mesh] and
# [prtouch_v3] sections so it can override their registration.
#
# 2026-04-06 initial; 2026-04-20 guard added; 2026-04-20 KAMP compat;
# 2026-04-20 unique rename target (_BMC_KAMP_INNER) to avoid prtouch collision;
# 2026-04-21 bypass prtouch subclass override (IndexError at wrapper:1922 on
# K2 Plus/F008): call upstream BedMeshCalibrate.cmd_BED_MESH_CALIBRATE as an
# unbound class method on the bmc instance, so Creality's subclass override
# (where present) is skipped. Fixes IndexError when KAMP passes MESH_MIN/MAX
# to a `bmc` whose concrete class is Creality's PRTouch BedMeshCalibrate.

import logging


class BedMeshOverride:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.upstream_cmd = None
        self.printer.register_event_handler(
            "klippy:connect", self._handle_connect)

    def _handle_connect(self):
        try:
            gcode = self.printer.lookup_object('gcode')
            bed_mesh = self.printer.lookup_object('bed_mesh')
            bmc = getattr(bed_mesh, 'bmc', None)
            if bmc is None:
                logging.error(
                    "bed_mesh_override: bed_mesh.bmc not found, abort")
                return
            # Grab upstream's cmd_BED_MESH_CALIBRATE as an unbound class method.
            # Why: on K2 Plus (F008) Creality's prtouch_v3_wrapper replaces
            # `bed_mesh.bmc` with a subclass that overrides cmd_BED_MESH_CALIBRATE
            # with a broken regional-parse path (crashes `IndexError: list index
            # out of range` at prtouch_v3_wrapper.py:1922 when called with
            # MESH_MIN/MESH_MAX but no GCODE_FILE — which is exactly how KAMP
            # calls it). Fetching the method from `bmc` (instance-level lookup)
            # would return the subclass override; fetching from the upstream
            # class bypasses it. Bound to the existing bmc instance via __get__
            # so the method sees the printer's actual bed_mesh state.
            try:
                from extras.bed_mesh import BedMeshCalibrate as _UpstreamBMC
            except ImportError as e:
                logging.error(
                    "bed_mesh_override: cannot import upstream "
                    "BedMeshCalibrate: %s", e)
                return
            upstream_unbound = getattr(
                _UpstreamBMC, 'cmd_BED_MESH_CALIBRATE', None)
            if upstream_unbound is None:
                logging.error(
                    "bed_mesh_override: upstream BedMeshCalibrate has no "
                    "cmd_BED_MESH_CALIBRATE, abort")
                return
            help_text = getattr(
                _UpstreamBMC, 'cmd_BED_MESH_CALIBRATE_help',
                "Perform Mesh Bed Leveling")
            self.upstream_cmd = upstream_unbound.__get__(bmc, type(bmc))
            logging.info(
                "bed_mesh_override: upstream bound to %s via class "
                "BedMeshCalibrate (bypasses any subclass override)",
                type(bmc).__name__)

            # KAMP detection: if a gcode_macro named BED_MESH_CALIBRATE is
            # registered, KAMP's wrapper is installed. KAMP-K2's installer
            # rewrites KAMP's rename_existing target to `_BMC_KAMP_INNER`
            # (avoids colliding with Creality's pre-registered
            # `_BED_MESH_CALIBRATE` on some firmware variants). Fall back to
            # the stock name for people who installed the cfg by hand.
            kamp_macro = self.printer.lookup_object(
                'gcode_macro BED_MESH_CALIBRATE', None)
            if kamp_macro is not None:
                all_cmds = set(getattr(gcode, 'ready_gcode_handlers', {}).keys())
                all_cmds.update(getattr(gcode, 'base_gcode_handlers', {}).keys())
                if '_BMC_KAMP_INNER' in all_cmds:
                    target = '_BMC_KAMP_INNER'
                else:
                    target = '_BED_MESH_CALIBRATE'
                mode = 'KAMP'
            else:
                target = 'BED_MESH_CALIBRATE'
                mode = 'direct'

            try:
                gcode.register_command(target, None)
            except Exception:
                pass
            gcode.register_command(
                target,
                self._guarded_cmd_BED_MESH_CALIBRATE,
                desc=help_text)
            logging.info(
                "bed_mesh_override: %s re-registered to guarded upstream "
                "(%s mode; bare calls are no-ops; MESH_MIN/MAX required "
                "to run)" % (target, mode))
        except Exception:
            logging.exception("bed_mesh_override: failed to override")

    def _guarded_cmd_BED_MESH_CALIBRATE(self, gcmd):
        mesh_min = gcmd.get('MESH_MIN', None)
        mesh_max = gcmd.get('MESH_MAX', None)
        if mesh_min is None or mesh_max is None:
            gcmd.respond_info(
                "BED_MESH_CALIBRATE deferred (no MESH_MIN/MESH_MAX supplied)."
                " Adaptive mesh runs inside START_PRINT.")
            logging.info(
                "bed_mesh_override: bare BED_MESH_CALIBRATE call suppressed"
                " (no MESH_MIN/MAX)")
            return
        # Slicer-driven adaptive call with explicit bounds — pass through.
        self.upstream_cmd(gcmd)


def load_config(config):
    return BedMeshOverride(config)
