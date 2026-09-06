import bpy
from . import startup
from . import foundry_output

from . import props
from . import tools
from . import ui
from . import export
from . import keymap
from . import icons
from . import preferences
from . import animation_fast
from . import compat_fixes
from . import fast_navigation
from . import perf_material_cleanup
from . import perf_bitmap_cache
from . import perf_patch
from . import scenario_reference
from . import fast_runtime
from . import h3_import
from .h3_import import volume_display
from .h3_import import animation_ops

modules = [
    preferences,
    props,
    ui,
    animation_fast,
    tools,
    export,
    keymap,
    icons,
    compat_fixes,
    fast_navigation,
    perf_material_cleanup,
    perf_bitmap_cache,
    perf_patch,
    fast_runtime,
    scenario_reference,
    h3_import,
    volume_display,
    animation_ops,
]
            
def register():
    scenario_reference.prepare()
    foundry_output.register()
    bpy.app.handlers.exit_pre.append(startup.managed_blam_exit)
    bpy.app.handlers.load_post.append(startup.load_handler)
    bpy.app.handlers.load_post.append(startup.load_set_output_state)
    bpy.app.handlers.save_post.append(startup.save_object_positions_to_tags)
    bpy.app.handlers.blend_import_post.append(startup.import_handler)
    for module in modules:
        module.register()
    startup.load_projects()

def unregister():
    bpy.app.handlers.blend_import_post.remove(startup.import_handler)
    bpy.app.handlers.save_post.remove(startup.save_object_positions_to_tags)
    bpy.app.handlers.load_post.remove(startup.load_set_output_state)
    bpy.app.handlers.load_post.remove(startup.load_handler)
    bpy.app.handlers.exit_pre.remove(startup.managed_blam_exit)
    for module in reversed(modules):
        module.unregister()
    foundry_output.unregister()
