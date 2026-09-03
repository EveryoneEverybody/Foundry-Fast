"""Low-risk import performance instrumentation and progress throttling.

This module intentionally does not change imported geometry or tag semantics. It
only throttles the very hot console progress path while a scenario BSP is being
imported and records inclusive timings for the main Blender-side phases.

The goal is to identify the real bottleneck before making invasive importer
changes. Remove this module once the measurements have been folded into a
proper optimisation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter

from . import utils
from .managed_blam.connected_geometry import Cluster, Instance, InstanceDefinition
from .managed_blam.scenario_structure_bsp import ScenarioStructureBspTag
from .managed_blam.scenario_structure_lighting_info import ScenarioStructureLightingInfoTag


# Human-visible console output does not need to be refreshed hundreds of times
# per second. Ten updates per second still looks continuous while avoiding a
# large number of Python -> terminal writes during instance-definition loops.
_PROGRESS_INTERVAL_SECONDS = 0.10


@dataclass
class _BspPerfSample:
    name: str
    timings: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    progress_calls: int = 0
    progress_emitted: int = 0
    progress_suppressed: int = 0
    progress_last_emit: dict[tuple[str, int], float] = field(default_factory=dict)

    def add(self, label: str, elapsed: float) -> None:
        self.timings[label] += elapsed
        self.counts[label] += 1


_active_samples: list[_BspPerfSample] = []
_originals: list[tuple[object, str, object]] = []
_registered = False


def _current_sample() -> _BspPerfSample | None:
    return _active_samples[-1] if _active_samples else None


def _patch_attr(owner, name: str, replacement) -> None:
    _originals.append((owner, name, getattr(owner, name)))
    setattr(owner, name, replacement)


def _timed_method(owner, name: str, label: str) -> None:
    original = getattr(owner, name)

    @wraps(original)
    def wrapped(*args, **kwargs):
        sample = _current_sample()
        if sample is None:
            return original(*args, **kwargs)

        started = perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            sample.add(label, perf_counter() - started)

    _patch_attr(owner, name, wrapped)


def _timed_function(owner, name: str, label: str) -> None:
    original = getattr(owner, name)

    @wraps(original)
    def wrapped(*args, **kwargs):
        sample = _current_sample()
        if sample is None:
            return original(*args, **kwargs)

        started = perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            sample.add(label, perf_counter() - started)

    _patch_attr(owner, name, wrapped)


def _install_progress_throttle() -> None:
    original = utils.update_job_count

    @wraps(original)
    def throttled(message, spinner, completed, total):
        sample = _current_sample()
        if sample is None:
            return original(message, spinner, completed, total)

        sample.progress_calls += 1

        # Always show the start and final state. Intermediate updates are
        # rate-limited by message/total so separate jobs do not starve each
        # other.
        boundary = completed <= 0 or completed >= total
        key = (str(message), int(total))
        now = perf_counter()
        last_emit = sample.progress_last_emit.get(key, 0.0)

        if boundary or now - last_emit >= _PROGRESS_INTERVAL_SECONDS:
            sample.progress_last_emit[key] = now
            sample.progress_emitted += 1
            try:
                return original(message, spinner, completed, total)
            finally:
                if completed >= total:
                    sample.progress_last_emit.pop(key, None)

        sample.progress_suppressed += 1
        return None

    _patch_attr(utils, "update_job_count", throttled)


def _print_sample(sample: _BspPerfSample, total: float) -> None:
    print(f"\n[Foundry perf] BSP {sample.name}: {total:.3f}s total")

    ordered_labels = (
        "lighting objects",
        "instance definitions",
        "instance placements",
        "clusters",
        "structure join",
        "face attribute consolidation",
        "material consolidation",
    )

    for label in ordered_labels:
        elapsed = sample.timings.get(label, 0.0)
        count = sample.counts.get(label, 0)
        if not count:
            continue
        percent = (elapsed / total * 100.0) if total > 0.0 else 0.0
        print(f"  {label:<30} {elapsed:8.3f}s  {percent:6.1f}%  ({count} calls)")

    if sample.progress_calls:
        print(
            "  progress updates"
            f"                 {sample.progress_emitted}/{sample.progress_calls} emitted"
            f" ({sample.progress_suppressed} suppressed)"
        )

    print("  Note: phase timings are inclusive and can overlap when one measured operation calls another.\n")


def _install_bsp_timer() -> None:
    original = ScenarioStructureBspTag.to_blend_objects

    @wraps(original)
    def timed_bsp_import(self, *args, **kwargs):
        try:
            name = self.tag_path.ShortName
        except Exception:
            name = "<unknown>"

        sample = _BspPerfSample(name=name)
        _active_samples.append(sample)
        started = perf_counter()
        try:
            return original(self, *args, **kwargs)
        finally:
            total = perf_counter() - started
            if _active_samples and _active_samples[-1] is sample:
                _active_samples.pop()
            else:
                try:
                    _active_samples.remove(sample)
                except ValueError:
                    pass
            _print_sample(sample, total)

    _patch_attr(ScenarioStructureBspTag, "to_blend_objects", timed_bsp_import)


def register():
    global _registered
    if _registered:
        return

    # First install the top-level BSP context, then the inner probes. The
    # top-level wrapper activates the sample before any inner operation runs.
    _install_bsp_timer()
    _install_progress_throttle()

    _timed_method(ScenarioStructureLightingInfoTag, "to_blender", "lighting objects")
    _timed_method(InstanceDefinition, "create", "instance definitions")
    _timed_method(Instance, "create", "instance placements")
    _timed_method(Cluster, "create", "clusters")
    _timed_function(utils, "join_objects", "structure join")
    _timed_function(utils, "consolidate_face_attributes", "face attribute consolidation")
    _timed_function(utils, "consolidate_materials", "material consolidation")

    _registered = True
    print("[Foundry perf] Scenario BSP instrumentation enabled; progress output throttled to 10 Hz during BSP import")


def unregister():
    global _registered
    if not _registered:
        return

    for owner, name, original in reversed(_originals):
        setattr(owner, name, original)
    _originals.clear()
    _active_samples.clear()
    _registered = False
