from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
import os
from time import perf_counter

import bpy

from . import foundry_output, preferences as preferences_module, utils
from .managed_blam.connected_geometry import (
    BSPCollisionMaterial,
    Cluster,
    Instance,
    InstanceDefinition,
    InstancePhysics,
    Material,
    Mesh,
    StructureCollision,
)
from .managed_blam.scenario_structure_bsp import ScenarioStructureBspTag
from .managed_blam.scenario_structure_lighting_info import ScenarioStructureLightingInfoTag
from .tools import importer as importer_module
from .tools import shader_reader as shader_reader_module


_PROGRESS_INTERVAL_SECONDS = 0.10
_MATERIAL_PROGRESS_INTERVAL_SECONDS = 0.50
_LIVE_VERBOSE_PROPERTY = "live_verbose_import_output"


@dataclass
class _BspPerfSample:
    name: str
    timings: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    progress_calls: int = 0
    progress_emitted: int = 0
    progress_suppressed: int = 0

    def add(self, label: str, elapsed: float) -> None:
        self.timings[label] += elapsed
        self.counts[label] += 1


@dataclass
class _MaterialPerfSample:
    total_materials: int = 0
    processed_materials: int = 0
    built_materials: int = 0
    copied_materials: int = 0
    timings: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    slow_materials: list[tuple[float, str, str]] = field(default_factory=list)
    last_progress_emit: float = 0.0

    def add(self, label: str, elapsed: float) -> None:
        self.timings[label] += elapsed
        self.counts[label] += 1


class NWO_OT_OpenFoundryDetailLog(bpy.types.Operator):
    bl_idname = "nwo.open_foundry_detail_log"
    bl_label = "Open Detailed Import Log"
    bl_description = "Open the complete import log, including messages hidden from live output"

    def execute(self, context):
        path = foundry_output.detail_log_path()
        try:
            os.startfile(str(path))
        except (AttributeError, OSError) as error:
            self.report({"ERROR"}, f"Unable to open detailed log: {error}")
            return {"CANCELLED"}
        return {"FINISHED"}


_active_bsp_samples: list[_BspPerfSample] = []
_active_material_samples: list[_MaterialPerfSample] = []
_originals: list[tuple[object, str, object]] = []
_progress_last_emit: dict[tuple[str, int], float] = {}
_registered = False
_live_verbose_property_added = False


def _current_bsp_sample() -> _BspPerfSample | None:
    return _active_bsp_samples[-1] if _active_bsp_samples else None


def _current_material_sample() -> _MaterialPerfSample | None:
    return _active_material_samples[-1] if _active_material_samples else None


def _patch_attr(owner, name: str, replacement) -> None:
    _originals.append((owner, name, getattr(owner, name)))
    setattr(owner, name, replacement)


def _timed_bsp_method(owner, name: str, label: str) -> None:
    original = getattr(owner, name)

    @wraps(original)
    def wrapped(*args, **kwargs):
        sample = _current_bsp_sample()
        if sample is None:
            return original(*args, **kwargs)

        started = perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            sample.add(label, perf_counter() - started)

    _patch_attr(owner, name, wrapped)


def _timed_bsp_function(owner, name: str, label: str) -> None:
    _timed_bsp_method(owner, name, label)


def _timed_material_function(owner, name: str, label: str) -> None:
    original = getattr(owner, name)

    @wraps(original)
    def wrapped(*args, **kwargs):
        sample = _current_material_sample()
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
        sample = _current_bsp_sample()
        if sample is not None:
            sample.progress_calls += 1

        completed_value = int(completed)
        total_value = int(total)
        boundary = completed_value <= 0 or completed_value >= total_value
        key = (str(message), total_value)
        now = perf_counter()
        last_emit = _progress_last_emit.get(key, 0.0)

        if boundary or now - last_emit >= _PROGRESS_INTERVAL_SECONDS:
            _progress_last_emit[key] = now
            if sample is not None:
                sample.progress_emitted += 1
            try:
                return original(message, spinner, completed, total)
            finally:
                if completed_value >= total_value:
                    _progress_last_emit.pop(key, None)

        if sample is not None:
            sample.progress_suppressed += 1
        return None

    _patch_attr(utils, "update_job_count", throttled)


def _print_bsp_sample(sample: _BspPerfSample, total: float) -> None:
    print(f"\n[Foundry perf] BSP {sample.name}: {total:.3f}s total")

    ordered_labels = (
        "lighting objects",
        "BSP material metadata",
        "collision material metadata",
        "instance definition parsing",
        "instance definition building",
        "raw mesh extraction",
        "Blender mesh creation",
        "instance placement parsing",
        "instance placement building",
        "instance physics parsing",
        "cluster parsing",
        "cluster building",
        "structure collision parsing",
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
        print(f"  {label:<32} {elapsed:8.3f}s  {percent:6.1f}%  ({count} calls)")

    if sample.progress_calls:
        print(
            "  progress updates"
            f"                   {sample.progress_emitted}/{sample.progress_calls} emitted"
            f" ({sample.progress_suppressed} suppressed)"
        )

    print("  Note: phase timings are inclusive and can overlap.\n")


def _install_bsp_timer() -> None:
    original = ScenarioStructureBspTag.to_blend_objects

    @wraps(original)
    def timed_bsp_import(self, *args, **kwargs):
        try:
            name = self.tag_path.ShortName
        except Exception:
            name = "<unknown>"

        sample = _BspPerfSample(name=name)
        _active_bsp_samples.append(sample)
        started = perf_counter()
        try:
            return original(self, *args, **kwargs)
        finally:
            total = perf_counter() - started
            if _active_bsp_samples and _active_bsp_samples[-1] is sample:
                _active_bsp_samples.pop()
            else:
                try:
                    _active_bsp_samples.remove(sample)
                except ValueError:
                    pass
            _print_bsp_sample(sample, total)

    _patch_attr(ScenarioStructureBspTag, "to_blend_objects", timed_bsp_import)


def _material_progress(sample: _MaterialPerfSample) -> None:
    total = max(sample.total_materials, sample.processed_materials)
    if total <= 0:
        return

    now = perf_counter()
    boundary = sample.processed_materials >= total
    if not boundary and now - sample.last_progress_emit < _MATERIAL_PROGRESS_INTERVAL_SECONDS:
        return

    sample.last_progress_emit = now
    utils.update_job_count(
        "  - Building Blender Materials",
        "",
        sample.processed_materials,
        total,
    )


def _install_material_conversion_timer() -> None:
    original = importer_module.tag_to_nodes

    @wraps(original)
    def timed_tag_to_nodes(corinth, mat, tag_path, *args, **kwargs):
        sample = _current_material_sample()
        if sample is None:
            return original(corinth, mat, tag_path, *args, **kwargs)

        started = perf_counter()
        try:
            return original(corinth, mat, tag_path, *args, **kwargs)
        finally:
            elapsed = perf_counter() - started
            sample.add("shader tag conversion", elapsed)
            sample.built_materials += 1
            sample.processed_materials += 1
            sample.slow_materials.append((elapsed, mat.name, str(tag_path)))
            _material_progress(sample)

    _patch_attr(importer_module, "tag_to_nodes", timed_tag_to_nodes)


def _install_material_copy_timer() -> None:
    original = utils.copy_material_nodes

    @wraps(original)
    def timed_copy_material_nodes(source, destination, *args, **kwargs):
        sample = _current_material_sample()
        if sample is None:
            return original(source, destination, *args, **kwargs)

        started = perf_counter()
        try:
            return original(source, destination, *args, **kwargs)
        finally:
            sample.add("copy reused node trees", perf_counter() - started)
            sample.copied_materials += 1
            sample.processed_materials += 1
            _material_progress(sample)

    _patch_attr(utils, "copy_material_nodes", timed_copy_material_nodes)


def _install_material_cleanup_timer() -> None:
    original = importer_module.clear_duplicate_materials

    @wraps(original)
    def timed_clear_duplicate_materials(*args, **kwargs):
        sample = _current_material_sample()
        if sample is None:
            return original(*args, **kwargs)

        started = perf_counter()
        try:
            result = original(*args, **kwargs)
        finally:
            sample.add("duplicate material cleanup", perf_counter() - started)

        sample.total_materials = sum(
            1
            for mat in result
            if mat.users and getattr(mat.nwo, "shader_path", "")
        )
        if sample.total_materials:
            utils.update_job_count("  - Building Blender Materials", "", 0, sample.total_materials)
        return result

    _patch_attr(importer_module, "clear_duplicate_materials", timed_clear_duplicate_materials)


def _print_material_sample(sample: _MaterialPerfSample, total: float) -> None:
    print(f"\n[Foundry perf] Blender materials: {total:.3f}s total")
    print(
        "  materials"
        f"                         {sample.built_materials} built,"
        f" {sample.copied_materials} copied"
    )

    ordered_labels = (
        "duplicate material cleanup",
        "shader path lookup",
        "shader tag conversion",
        "node layout",
        "copy reused node trees",
        "material function drivers",
        "emissive attributes",
    )

    for label in ordered_labels:
        elapsed = sample.timings.get(label, 0.0)
        count = sample.counts.get(label, 0)
        if not count:
            continue
        percent = (elapsed / total * 100.0) if total > 0.0 else 0.0
        print(f"  {label:<32} {elapsed:8.3f}s  {percent:6.1f}%  ({count} calls)")

    slowest = sorted(sample.slow_materials, reverse=True)[:10]
    if slowest:
        print("  slowest shader conversions")
        for elapsed, name, tag_path in slowest:
            print(f"    {elapsed:7.3f}s  {name}  [{tag_path}]")

    print(f"  detailed log                     {foundry_output.detail_log_path()}")
    print("  Note: phase timings are inclusive and can overlap.\n")


def _install_material_stage_timer() -> None:
    original = importer_module.setup_materials

    @wraps(original)
    def timed_setup_materials(
        context,
        importer,
        starting_materials,
        imported_objects,
        build_materials,
        always_extract_bitmaps=False,
        emissive_meshes=None,
    ):
        if not build_materials:
            return original(
                context,
                importer,
                starting_materials,
                imported_objects,
                build_materials,
                always_extract_bitmaps,
                emissive_meshes,
            )

        starting_set = starting_materials if isinstance(starting_materials, set) else set(starting_materials)
        sample = _MaterialPerfSample(
            total_materials=sum(
                1
                for mat in bpy.data.materials
                if mat not in starting_set and mat.users and getattr(mat.nwo, "shader_path", "")
            )
        )
        _active_material_samples.append(sample)
        started = perf_counter()
        completed = False
        try:
            result = original(
                context,
                importer,
                starting_materials,
                imported_objects,
                build_materials,
                always_extract_bitmaps,
                emissive_meshes,
            )
            completed = True
            return result
        finally:
            total = perf_counter() - started
            if completed and sample.total_materials:
                sample.processed_materials = max(sample.processed_materials, sample.total_materials)
                _material_progress(sample)
            if _active_material_samples and _active_material_samples[-1] is sample:
                _active_material_samples.pop()
            else:
                try:
                    _active_material_samples.remove(sample)
                except ValueError:
                    pass
            foundry_output.flush_detail()
            _print_material_sample(sample, total)

    _patch_attr(importer_module, "setup_materials", timed_setup_materials)


def _install_preferences() -> None:
    global _live_verbose_property_added
    preferences_class = preferences_module.FoundryPreferences

    if not hasattr(preferences_class, _LIVE_VERBOSE_PROPERTY):
        setattr(
            preferences_class,
            _LIVE_VERBOSE_PROPERTY,
            bpy.props.BoolProperty(
                name="Live Per-Item Import Output",
                description="Show detailed per-material import messages live. The full log is always saved",
                default=False,
            ),
        )
        _live_verbose_property_added = True

    original = preferences_class.draw

    @wraps(original)
    def draw_with_performance(self, context):
        original(self, context)
        box = self.layout.box()
        box.label(text="Performance")
        box.prop(self, _LIVE_VERBOSE_PROPERTY)
        box.operator(NWO_OT_OpenFoundryDetailLog.bl_idname)

    _patch_attr(preferences_class, "draw", draw_with_performance)


def register():
    global _registered
    if _registered:
        return

    bpy.utils.register_class(NWO_OT_OpenFoundryDetailLog)
    _install_preferences()
    _install_bsp_timer()
    _install_progress_throttle()
    _install_material_stage_timer()
    _install_material_cleanup_timer()
    _install_material_conversion_timer()
    _install_material_copy_timer()

    _timed_bsp_method(ScenarioStructureLightingInfoTag, "to_blender", "lighting objects")
    _timed_bsp_method(Material, "__init__", "BSP material metadata")
    _timed_bsp_method(BSPCollisionMaterial, "__init__", "collision material metadata")
    _timed_bsp_method(InstanceDefinition, "__init__", "instance definition parsing")
    _timed_bsp_method(InstanceDefinition, "create", "instance definition building")
    _timed_bsp_method(Mesh, "_get_raw_mesh_data", "raw mesh extraction")
    _timed_bsp_method(Mesh, "_create_mesh", "Blender mesh creation")
    _timed_bsp_method(Instance, "__init__", "instance placement parsing")
    _timed_bsp_method(Instance, "create", "instance placement building")
    _timed_bsp_method(InstancePhysics, "__init__", "instance physics parsing")
    _timed_bsp_method(Cluster, "__init__", "cluster parsing")
    _timed_bsp_method(Cluster, "create", "cluster building")
    _timed_bsp_method(StructureCollision, "__init__", "structure collision parsing")
    _timed_bsp_function(utils, "join_objects", "structure join")
    _timed_bsp_function(utils, "consolidate_face_attributes", "face attribute consolidation")
    _timed_bsp_function(utils, "consolidate_materials", "material consolidation")

    _timed_material_function(importer_module, "find_shaders", "shader path lookup")
    _timed_material_function(shader_reader_module, "arrange", "node layout")
    _timed_material_function(importer_module, "add_function", "material function drivers")
    _timed_material_function(utils, "setup_emissive_attributes", "emissive attributes")

    _registered = True
    print("[Foundry perf] Import instrumentation enabled; progress output throttled to 10 Hz")


def unregister():
    global _registered, _live_verbose_property_added
    if not _registered:
        return

    for owner, name, original in reversed(_originals):
        setattr(owner, name, original)
    _originals.clear()

    if _live_verbose_property_added:
        try:
            delattr(preferences_module.FoundryPreferences, _LIVE_VERBOSE_PROPERTY)
        except (AttributeError, RuntimeError):
            pass
        _live_verbose_property_added = False

    try:
        bpy.utils.unregister_class(NWO_OT_OpenFoundryDetailLog)
    except RuntimeError:
        pass

    _active_bsp_samples.clear()
    _active_material_samples.clear()
    _progress_last_emit.clear()
    _registered = False
