from pathlib import Path
import bpy

class ToolPatcher:
    def __init__(self, tool_path: str | Path):
        self.tool_path = str(tool_path)
        
    def _normalise_patch_args(self, offsets: list[int] | int, patches: list[bytes] | bytes, originals: list[bytes] | bytes):
        if not isinstance(offsets, list):
            offsets = [offsets]

        if not isinstance(patches, list):
            patches = [patches] * len(offsets)

        if not isinstance(originals, list):
            originals = [originals] * len(offsets)

        assert len(offsets) == len(patches) == len(originals)
        return offsets, patches, originals

    def _patch(self, offsets: list[int] | int, patches: list[bytes] | bytes, originals: list[bytes] | bytes):
        self._toggle_patch(offsets, patches, originals, True)

    def _toggle_patch(self, offsets: list[int] | int, patches: list[bytes] | bytes, originals: list[bytes] | bytes, enabled: bool):
        try:
            if not bpy.context.preferences.addons[__package__].preferences.allow_tool_patches:
                return

            offsets, patches, originals = self._normalise_patch_args(offsets, patches, originals)

            with open(self.tool_path, "r+b") as f:
                for offset, patch, original in zip(offsets, patches, originals):
                    assert len(patch) == len(original)
                    expected = original if enabled else patch
                    replacement = patch if enabled else original
                    f.seek(offset)
                    data = f.read(len(expected))
                    if data == expected:
                        f.seek(offset)
                        f.write(replacement)
        except:
            print("Failed to patch Tool")
        
    def reach_lightmap_color(self): 
        original0 = b"\xE8\x4D\x54\x29\x00"
        original1 = b"\xE8\x37\x54\x29\x00"
        original2 = b"\xE8\x1C\x54\x29\x00"
        original3 = b"\xE8\xC7\x53\x29\x00"
        original4 = b"\xE8\xB1\x53\x29\x00"
        original5 = b"\xE8\x96\x53\x29\x00"
        patch = b"\x90\x90\x90\x90\x90"
        address0 = 0xF2A02
        address1 = 0xF2A18
        address2 = 0xF2A33
        address3 = 0xF2A88
        address4 = 0xF2A9E
        address5 = 0xF2AB9
            
        self._patch([address0, address1, address2, address3, address4, address5], patch, [original0, original1, original2, original3, original4, original5])
        
    def reach_plane_builder(self):
        patch = b"\xEB"
        if self.tool_path.lower().endswith("_fast.exe"):
            addresses = [0x19A775, 0x19A789, 0x19A79A, 0x1A0C86]
            originals = [b"\x77", b"\x77", b"\x77", b"\x73"]
        else:
            addresses = [0x220CE5, 0x220D55, 0x220DBB]
            originals = b"\x77"
            
        self._patch(addresses, patch, originals)
        
    def reach_wetness_data(self):
        original0 = b"\x74"
        patch0 = b"\xEB"
        original1 = b"\x25"
        patch1 = b"\x10"
        if self.tool_path.lower().endswith("_fast.exe"):
            return
        else:
            address0 = 0xB04F12
            address1 = 0x382557
            
        self._patch([address0, address1], [patch0, patch1], [original0, original1])

    def reach_ignore_node_depth_sort(self):
        prefs = bpy.context.preferences.addons[__package__].preferences
        if not self.tool_path.lower().endswith("_fast.exe"):
            return

        # Reach tool_fast.exe node comparators. These patches skip the depth
        # early-outs so node sorting falls through to frame ID, then name.
        render_address = 0x1CC3B0
        render_original = b"\x8B\x14\x80\x41\xFF\xC2\x45\x2B\xCA\x75\x5B\x44\x8B\x49\x14\x44"
        render_patch = b"\x8B\x14\x80\x41\xFF\xC2\x45\x2B\xCA\x90\x90\x44\x8B\x49\x14\x44"

        animation_address = 0x1D60CB
        animation_original = b"\x8B\x41\x18\x2B\x42\x18\x75\x49\x8B\x81\xF8\x01\x00\x00\x2B\x82"
        animation_patch = b"\x8B\x41\x18\x2B\x42\x18\x90\x90\x8B\x81\xF8\x01\x00\x00\x2B\x82"

        self._toggle_patch(
            [render_address, animation_address],
            [render_patch, animation_patch],
            [render_original, animation_original],
            prefs.patch_tool_node_depth_sort,
        )
