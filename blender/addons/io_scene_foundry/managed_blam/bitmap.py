

from math import sqrt
import math
import os
import struct
import sys
import traceback
from pathlib import Path
import ctypes
import numpy as np

from ..constants import NormalType
from ..managed_blam import Tag
from .. import utils
import bpy

path_cache = set()
NORMAL_DEBUG_GAMMA = 2.2
NORMAL_DEBUG_GAMMA_LOOKUP = tuple(
    int(round(((i / 255.0) ** NORMAL_DEBUG_GAMMA) * 255.0))
    for i in range(256)
)
NORMAL_DEBUG_GAMMA_LOOKUP_NP = np.array(NORMAL_DEBUG_GAMMA_LOOKUP, dtype=np.uint8)

BITMAP_FORMAT_A8 = 0
BITMAP_FORMAT_Y8 = 1
BITMAP_FORMAT_AY8 = 2
BITMAP_FORMAT_A8Y8 = 3
BITMAP_FORMAT_R5G6B5 = 6
BITMAP_FORMAT_A1R5G5B5 = 8
BITMAP_FORMAT_A4R4G4B4 = 9
BITMAP_FORMAT_X8R8G8B8 = 10
BITMAP_FORMAT_A8R8G8B8 = 11

UNCOMPRESSED_BITMAP_FORMAT_NAMES = {
    BITMAP_FORMAT_A8: "A8",
    BITMAP_FORMAT_Y8: "Y8",
    BITMAP_FORMAT_AY8: "AY8",
    BITMAP_FORMAT_A8Y8: "A8Y8",
    BITMAP_FORMAT_R5G6B5: "R5G6B5",
    BITMAP_FORMAT_A1R5G5B5: "A1R5G5B5",
    BITMAP_FORMAT_A4R4G4B4: "A4R4G4B4",
    BITMAP_FORMAT_X8R8G8B8: "X8R8G8B8",
    BITMAP_FORMAT_A8R8G8B8: "A8R8G8B8",
}

UNCOMPRESSED_BITMAP_BYTES_PER_PIXEL = {
    BITMAP_FORMAT_A8: 1,
    BITMAP_FORMAT_Y8: 1,
    BITMAP_FORMAT_AY8: 1,
    BITMAP_FORMAT_A8Y8: 2,
    BITMAP_FORMAT_R5G6B5: 2,
    BITMAP_FORMAT_A1R5G5B5: 2,
    BITMAP_FORMAT_A4R4G4B4: 2,
    BITMAP_FORMAT_X8R8G8B8: 4,
    BITMAP_FORMAT_A8R8G8B8: 4,
}

def clear_path_cache():
    global path_cache
    path_cache.clear()
    
class BitmapInfo:
    def __init__(self):
        self.image: bpy.types.Image = None
        self.image_path = ""
        self.curve = 0
        self.for_normal = True
        self.cubemap = False
        self.sequence_length = 1
        self.shader_type = "default"
        
used_plate_paths = []
    
def bitmap_to_image(path: str | Path, always_extract_bitmaps=False) -> BitmapInfo:
    
    image = None
    
    data_dir = utils.get_data_path()
    tags_dir = utils.get_tags_path()
    
    rel_path = utils.relative_path(path)
    
    tag_path = Path(tags_dir, rel_path)
    
    info = BitmapInfo()
    
    if not tag_path.exists():
        return info
        
    system_tiff_path = Path(utils.get_data_path(), rel_path).with_suffix('.tiff')
    alt_system_tiff_path = system_tiff_path.with_suffix(".tif")
    
    try:
        with BitmapTag(path=rel_path) as bitmap:
            if not bitmap.has_bitmap_data(): return info
            if bitmap.is_cubemap:
                info.cubemap = True
                rel_path = f"{bitmap.tag_path.RelativePath}_equirectangular"
                system_tiff_path = Path(data_dir, rel_path).with_suffix('.tiff')
                alt_system_tiff_path = system_tiff_path.with_suffix(".tif")
            
            info.curve = bitmap.tag.SelectField("Block:bitmaps[0]/CharEnum:curve").Value
            info.for_normal = bitmap.used_as_normal_map()
            info.shader_type = bitmap.get_shader_type()
            if always_extract_bitmaps:
                info.image_path = bitmap.save_to_tiff(info.for_normal)
            else:
                if system_tiff_path.exists():
                    info.image_path = str(system_tiff_path)
                elif alt_system_tiff_path.exists():
                    info.image_path = str(alt_system_tiff_path)
                else:
                    info.image_path = bitmap.save_to_tiff(info.for_normal)
    except Exception as e:
        # Tool will save the day
        utils.print_error(traceback.format_exception_only(e)[0])
        utils.print_warning(f"Failed to read bitmap {rel_path} with ManagedBlam. Using Tool instead\n")
        system_tga_path = Path(system_tiff_path.parent, system_tiff_path.with_suffix("").name, system_tiff_path.with_suffix("").name).with_suffix(".tga")
        system_tga_path_array_processed = system_tga_path.with_name(f'{system_tga_path.with_suffix("").name}_00001.tga')
        system_tga_path_suffix = system_tga_path.with_name(f'{system_tga_path.with_suffix("").name}_00_00.tga')
        system_tga_path_array = system_tga_path.with_name(f'{system_tga_path.with_suffix("").name}_00_01.tga')
        
        suffix_less = str(Path(rel_path).with_suffix(""))
        
        if always_extract_bitmaps:
            if not system_tga_path.parent.exists():
                system_tga_path.parent.mkdir(parents=True)
            utils.run_tool(["export-bitmap-tga", suffix_less, str(system_tga_path_suffix.parent) + os.sep + os.sep])
        elif not system_tga_path_suffix.exists() and not system_tga_path_array_processed.exists():
            if not system_tga_path.parent.exists():
                system_tga_path.parent.mkdir(parents=True)
            utils.run_tool(["export-bitmap-tga", suffix_less, str(system_tga_path_suffix.parent) + os.sep + os.sep])
            
        if system_tga_path_array_processed.exists():
            info.image_path = str(system_tga_path.parent)
        elif system_tga_path_suffix.exists():
            if system_tga_path_array.exists():
                info.image_path = str(system_tga_path.parent)
                files = sorted(system_tga_path.parent.iterdir(), reverse=True)
                for f in files:
                    if f.is_file():
                        name, _, stem = f.stem.rpartition("_")
                        suffix = f.suffix
                        print(stem, stem.isdigit())
                        if stem.isdigit():
                            new_number = int(stem) + 1
                            new_stem = f"{new_number:05d}"
                            new_name = f"{name.rpartition('_')[0]}_{new_stem}{suffix}"
                            f.rename(system_tga_path.parent / new_name)
            else:
                info.image_path = str(system_tga_path_suffix)
            
        else:
            utils.print_warning("Failed to extract bitmap using Tool")
            
    if not info.image_path:
        return info
    
    # Check if this image is a plate
    plate_dir = Path(info.image_path).with_suffix("")
    if plate_dir.exists() and plate_dir.is_dir():
        tifs = list(plate_dir.iterdir())
        if len(tifs) > info.sequence_length:
            info.sequence_length = len(tifs)
            for tif in tifs:
                if tif in used_plate_paths:
                    continue
                used_plate_paths.append(tif)
                info.image_path = str(tif)
                break
            else:
                info.image_path = str(tifs[0])
            
    image = bpy.data.images.load(filepath=info.image_path, check_existing=True)
    image.nwo.filepath = utils.relative_path(info.image_path)
    image.nwo.shader_type = info.shader_type

    if info.for_normal:
        image.colorspace_settings.name = 'Non-Color'
    elif info.curve == 3:
        image.colorspace_settings.name = 'Linear Rec.709'
        image.alpha_mode = 'CHANNEL_PACKED'
    else:
        image.colorspace_settings.name = 'sRGB'
        image.alpha_mode = 'CHANNEL_PACKED'

    if info.sequence_length > 1:
        image.source = 'SEQUENCE'
        
    info.image = image
            
    return info

class BitmapTag(Tag):
    tag_ext = 'bitmap'
    
    def _read_fields(self):
        self.longenum_usage = self.tag.SelectField('LongEnum:Usage')
        self.charenum_usage = self.tag.SelectField('CharEnum:curve mode')
        self.block_usage_override = self.tag.SelectField("Block:usage override")
        self.block_bitmaps = self.tag.SelectField("Block:bitmaps")
        self.is_cubemap = self.block_bitmaps.Elements.Count > 0 and self.block_bitmaps.Elements[0].SelectField("CharEnum:type").Value == 2
        
    def new_bitmap(self, bitmap_name, bitmap_type, color_space):
        def get_type_from_name(bitmap_name):
            suffix = bitmap_name.rpartition("_")[2].lower()
            if suffix and "_" in bitmap_name.strip("_"):
                if suffix.startswith(("orm", "mro", "mtr", "rmo", "control", "arm")):
                    return "Material Map"
                elif suffix.startswith("3d"):
                    return "3D Texture"
                elif suffix.startswith("blend"):
                    return "Blend Map (linear for terrains)"
                elif suffix.startswith("bump"):
                    return "Bump Map (from Height Map)"
                elif suffix.startswith(("cc", "change")):
                    return "Change Color Map"
                elif suffix.startswith("cube"):
                    return "Cube Map (Reflection Map)"
                elif suffix.startswith(("detailb", "detail_b")):
                    return "Detail Bump Map (from Height Map - fades out)"
                elif suffix.startswith(("detailn", "detail_n")):
                    return "Detail Normal Map"
                elif suffix.startswith("det"):
                    return "Detail Map"
                elif suffix.startswith("dsprite"):
                    return "Sprite (Double Multiply, Gray Background)"
                elif suffix.startswith("float"):
                    return "Float Map (WARNING)"
                elif suffix.startswith("height"):
                    return "Height Map (for Parallax)"
                elif suffix.startswith(("illum", "self", "emm")):
                    return "Self-Illum Map"
                elif suffix.startswith("msprite"):
                    return "Sprite (Blend, White Background)"
                elif suffix.startswith("spec"):
                    return "Specular Map"
                elif suffix.startswith("sprite"):
                    return "Sprite (Additive, Black Background)"
                elif suffix.startswith("ui"):
                    return "Interface Bitmap"
                elif suffix.startswith("vec"):
                    return "Vector Map"
                elif suffix.startswith("warp"):
                    return "Warp Map (EMBM)"
                elif suffix.startswith(("zbump", "dx_normal", 'dxnormal', 'normaldx', 'normal_dx')):
                    return "ZBrush Bump Map (from Bump Map)"
                elif suffix.startswith(("nor", "nm", "nrm")):
                    if self.corinth:
                        return "Normal Map (from Standard Orientation of Maya, Modo, Zbrush)"
                    else:
                        return "Normal Map (aka zbump)"
                    
            return "Diffuse Map"
        
        if bitmap_type == 'default':
            bitmap_type = get_type_from_name(bitmap_name)
            
        normal_bitmap_types = (
            "ZBrush Bump Map (from Bump Map)",
            "Normal Map (aka zbump)",
            "Normal Map (from Standard Orientation of Maya, Modo, Zbrush)",
        )

        self.longenum_usage.SetValue(bitmap_type)
        self.charenum_usage.SetValue('force PRETTY')
        if not self.block_usage_override.Elements.Count:
             self.block_usage_override.AddElement()
        override = self.block_usage_override.Elements[0]
        # Running this command sets up needed default values for the bitmap type
        override.SelectField("reset usage override").RunCommand()
        source_gamma = override.SelectField('source gamma')
        if bitmap_type in normal_bitmap_types:
            source_gamma_value = 1.0
        else:
            source_gamma_value = self._source_gamma_from_color_space(color_space)
        source_gamma.Data = source_gamma_value
        bitmap_curve = override.SelectField("bitmap curve")
        if source_gamma_value > 2.0:
            bitmap_curve.SetValue("sRGB (gamma 2.2)")
        elif source_gamma_value > 1:
            bitmap_curve.SetValue("xRGB (gamma about 2.0)")
        else:
            bitmap_curve.SetValue("linear")
            
        flags = override.SelectField("flags")
        flags.SetBit("Ignore Curve Override", True)
        bitmap_format = override.SelectField('bitmap format')
        if bitmap_type in ("Material Map", "Diffuse Map", "Blend Map (linear for terrains)", "Self-Illum Map", "Cube Map (Reflection Map)", "Detail Map"):
            bitmap_format.SetValue('DXT5 (Compressed Color + Compressed 8-bit Alpha)')
            # bitmap_format.SetValue('Best Uncompressed Color Format')
            if bitmap_type == 'Material Map':
                override.SelectField('mipmap limit').Data = -1
        elif bitmap_type in normal_bitmap_types:
            bitmap_format.SetValue('DXN Compressed Normals (better)')
            
        self.tag_has_changes = True
        
    def get_granny_data(self, fill_alpha: bool, calc_blue_channel: bool) -> object | None:
        from System import Array, Byte # type: ignore
        from System.Runtime.InteropServices import Marshal # type: ignore
        from System.Drawing import Rectangle # type: ignore
        from System.Drawing.Imaging import ImageLockMode, PixelFormat # type: ignore
        from System.Runtime.InteropServices import GCHandle, GCHandleType # type: ignore
        game_bitmap = self._GameBitmap()
        bitmap = game_bitmap.GetBitmap()
        game_bitmap.Dispose()
        
        if bitmap.PixelFormat != PixelFormat.Format32bppArgb:
            return None
        
        gamma = self.get_gamma_name()
        
        width = bitmap.Width
        height = bitmap.Height

        bitmap_data = bitmap.LockBits(Rectangle(0, 0, width, height), ImageLockMode.ReadWrite, bitmap.PixelFormat)
        stride = bitmap_data.Stride
        total_bytes = abs(stride) * height
        bgra_array = Array.CreateInstance(Byte, total_bytes)
        Marshal.Copy(bitmap_data.Scan0, bgra_array, 0, total_bytes)
        bitmap.UnlockBits(bitmap_data)
        
        if calc_blue_channel:
            rgba_array = self.bgra_to_rgba_with_calculated_blue(total_bytes, bgra_array, gamma, self.normal_type() == NormalType.OPENGL)
        elif fill_alpha:
            rgba_array = self.bgra_to_rgba_solid_alpha(total_bytes, bgra_array, gamma)
        else:
            rgba_array = self.bgra_to_rgba(total_bytes, bgra_array, gamma)
        
        handle = GCHandle.Alloc(rgba_array, GCHandleType.Pinned)
        rgba_ptr = None
        try:
            rgba_ptr = ctypes.c_void_p(handle.AddrOfPinnedObject().ToInt64())
        finally:
            if handle.IsAllocated:
                handle.Free()
        
        bitmap.Dispose()
        
        if rgba_ptr is None:
            return None
        
        return width, height, stride, rgba_ptr
    
    @staticmethod
    def bgra_to_rgba_solid_alpha(total_bytes, bgra_array, gamma):
        for i in range(0, total_bytes, 4):
            bgra_array[i + 3] = 255
            red = bgra_array[i + 2] / 255.0
            green = bgra_array[i + 1] / 255.0
            blue = bgra_array[i] / 255.0
            # match gamma:
            #     case 'linear':
            #         red = red ** 2.0
            #         green = green ** 2.0
            #         blue = blue ** 2.0
            #     case 'srgb':
            #         red = utils.linear_to_srgb(red ** 2.0)
            #         green = utils.linear_to_srgb(green ** 2.0)
            #         blue = utils.linear_to_srgb(blue ** 2.0)
                    
            bgra_array[i] = int(red * 255)
            bgra_array[i + 1] = int(green * 255)
            bgra_array[i + 2] = int(blue * 255)
            
        return bgra_array
    
    @staticmethod
    def bgra_to_rgba(total_bytes, bgra_array, gamma):
        for i in range(0, total_bytes, 4):
            red = bgra_array[i + 2] / 255.0
            green = bgra_array[i + 1] / 255.0
            blue = bgra_array[i] / 255.0
            # match gamma:
            #     case 'linear':
            #         red = red ** 2.0
            #         green = green ** 2.0
            #         blue = blue ** 2.0
            #     case 'srgb':
            #         red = utils.linear_to_srgb(red ** 2.0)
            #         green = utils.linear_to_srgb(green ** 2.0)
            #         blue = utils.linear_to_srgb(blue ** 2.0)
                    
            bgra_array[i] = int(red * 255)
            bgra_array[i + 1] = int(green * 255)
            bgra_array[i + 2] = int(blue * 255)
            
        return bgra_array
    
    @staticmethod
    def bgra_to_rgba_with_calculated_blue(total_bytes, bgra_array, _gamma, standard_orientation=False):
        for i in range(0, total_bytes, 4):
            if standard_orientation:
                red_byte = bgra_array[i + 1]
                green_byte = 255 - bgra_array[i + 2]
            else:
                red_byte = bgra_array[i + 2]
                green_byte = bgra_array[i + 1]

            red_byte = NORMAL_DEBUG_GAMMA_LOOKUP[red_byte]
            green_byte = NORMAL_DEBUG_GAMMA_LOOKUP[green_byte]
            red = red_byte / 255.0
            green = green_byte / 255.0
            blue_byte = int(calculate_z_vector(red, green) * 255 + 0.5)
                    
            bgra_array[i] = red_byte
            bgra_array[i + 1] = green_byte
            bgra_array[i + 2] = blue_byte
            
        return bgra_array
    
        # faces = {
        #     "back": bitmap.Clone(Rectangle(f * 3, f, f, f), bitmap.PixelFormat), # CUBEMAP: 0,1 HALO: 3,1
        #     "left": bitmap.Clone(Rectangle(0, f, f, f), bitmap.PixelFormat), # CUBEMAP: 1,1 HALO: 0,1
        #     "front": bitmap.Clone(Rectangle(f, f, f, f), bitmap.PixelFormat), # CUBEMAP: 2,1 HALO: 1,1
        #     "right": bitmap.Clone(Rectangle(2 * f, f, f, f), bitmap.PixelFormat), # CUBEMAP: 3,1 HALO: 2,1
        #     "bottom": bitmap.Clone(Rectangle(0, 2 * f, f, f), bitmap.PixelFormat), # CUBEMAP: 1,2 HALO: 0, 2
        #     "top": bitmap.Clone(Rectangle(0, 0, f, f), bitmap.PixelFormat), # CUBEMAP: 1,0 HALO: 0,0
        # }


    def extract_faces(self, cubemap, face_size):
        from System.Drawing import Rectangle # type: ignore
        faces = {
            "+Y": cubemap.Clone(Rectangle(0, 0, face_size, face_size), cubemap.PixelFormat),
            "-Y": cubemap.Clone(Rectangle(0, 2 * face_size, face_size, face_size), cubemap.PixelFormat),
            "+Z": cubemap.Clone(Rectangle(0, face_size, face_size, face_size), cubemap.PixelFormat),
            "-Z": cubemap.Clone(Rectangle(2 * face_size, face_size, face_size, face_size), cubemap.PixelFormat),
            "+X": cubemap.Clone(Rectangle(face_size, face_size, face_size, face_size), cubemap.PixelFormat),
            "-X": cubemap.Clone(Rectangle(3 * face_size, face_size, face_size, face_size), cubemap.PixelFormat)
        }
        return faces

    def sample_cubemap(self, faces, theta, phi, face_size):
        x = math.cos(phi) * math.cos(theta)
        y = math.sin(phi)
        z = math.cos(phi) * math.sin(theta)

        abs_x, abs_y, abs_z = abs(x), abs(y), abs(z)

        if abs_y >= abs_x and abs_y >= abs_z:
            face = "+Y" if y > 0 else "-Y"
            u = (x / abs_y + 1) / 2
            v = (z / abs_y + 1) / 2
        elif abs_x >= abs_y and abs_x >= abs_z:
            face = "+X" if x > 0 else "-X"
            u = (-z / abs_x + 1) / 2
            v = (-y / abs_x + 1) / 2
        else:
            face = "+Z" if z > 0 else "-Z"
            u = (x / abs_z + 1) / 2
            v = (-y / abs_z + 1) / 2

        u = max(0, min(int(u * (face_size - 1)), face_size - 1))
        v = max(0, min(int(v * (face_size - 1)), face_size - 1))

        return faces[face].GetPixel(u, v)

    @staticmethod
    def _equirectangular_face_type(height: int, width: int):
        if width % 8 != 0:
            raise ValueError("equirectangular cubemap width must be a multiple of 8")

        front, right, back, left, up, down = range(6)
        quarter_width = width // 4
        eighth_width = width // 8
        third_height = height // 3
        face_type = np.empty((height, width), dtype=np.int32)

        face_type[:, :eighth_width] = back
        face_type[:, eighth_width:eighth_width + quarter_width] = left
        face_type[:, eighth_width + quarter_width:eighth_width + 2 * quarter_width] = front
        face_type[:, eighth_width + 2 * quarter_width:eighth_width + 3 * quarter_width] = right
        face_type[:, eighth_width + 3 * quarter_width:] = back

        indices = np.linspace(-np.pi, np.pi, quarter_width, dtype=np.float32) / 4
        edge_rows = np.round(height / 2 - np.arctan(np.cos(indices)) * height / np.pi).astype(np.int32)
        row_indices = np.arange(third_height, dtype=np.int32)[:, None]
        top_mask = row_indices < edge_rows[None]
        bottom_mask = np.flip(top_mask, 0)

        face_type[:third_height, :eighth_width][top_mask[:, eighth_width:]] = up
        face_type[-third_height:, :eighth_width][bottom_mask[:, eighth_width:]] = down

        for index in range(3):
            start = eighth_width + index * quarter_width
            stop = start + quarter_width
            face_type[:third_height, start:stop][top_mask] = up
            face_type[-third_height:, start:stop][bottom_mask] = down

        remainder = width - stop
        face_type[:third_height, stop:][top_mask[:, :remainder]] = up
        face_type[-third_height:, stop:][bottom_mask[:, :remainder]] = down
        return face_type

    @staticmethod
    def _cubemap_equirectangular_coordinates(face_size: int, height: int, width: int):
        up, down = 4, 5
        u = np.linspace(-np.pi, np.pi, num=width, dtype=np.float32)
        v = np.linspace(np.pi / 2, -np.pi / 2, num=height, dtype=np.float32)
        u, v = np.meshgrid(u, v)

        face_type = BitmapTag._equirectangular_face_type(height, width)
        coor_x = np.empty((height, width), dtype=np.float32)
        coor_y = np.empty((height, width), dtype=np.float32)
        half_size = face_size / 2

        mask = face_type < up
        angles = u[mask] - (np.pi / 2 * face_type[mask])
        coor_x[mask] = half_size * np.tan(angles)
        coor_y[mask] = -half_size * np.tan(v[mask]) / np.cos(angles)

        mask = face_type == up
        distance = half_size * np.tan(np.pi / 2 - v[mask])
        coor_x[mask] = distance * np.sin(u[mask])
        coor_y[mask] = distance * np.cos(u[mask])

        mask = face_type == down
        distance = half_size * np.tan(np.pi / 2 - np.abs(v[mask]))
        coor_x[mask] = distance * np.sin(u[mask])
        coor_y[mask] = -distance * np.cos(u[mask])

        coor_x += half_size
        coor_y += half_size
        coor_x.clip(0, face_size, out=coor_x)
        coor_y.clip(0, face_size, out=coor_y)
        return face_type, coor_x, coor_y

    @staticmethod
    def _pad_cubemap_faces(cube_faces):
        front, right, back, left, up, down = range(6)
        padded = np.pad(cube_faces, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")

        padded[front, 0, 1:-1] = cube_faces[up, -1, :]
        padded[front, -1, 1:-1] = cube_faces[down, 0, :]
        padded[right, 0, 1:-1] = cube_faces[up, ::-1, -1]
        padded[right, -1, 1:-1] = cube_faces[down, :, -1]
        padded[back, 0, 1:-1] = cube_faces[up, 0, ::-1]
        padded[back, -1, 1:-1] = cube_faces[down, -1, ::-1]
        padded[left, 0, 1:-1] = cube_faces[up, :, 0]
        padded[left, -1, 1:-1] = cube_faces[down, ::-1, 0]
        padded[up, 0, 1:-1] = cube_faces[back, 0, ::-1]
        padded[up, -1, 1:-1] = cube_faces[front, 0, :]
        padded[down, 0, 1:-1] = cube_faces[front, -1, :]
        padded[down, -1, 1:-1] = cube_faces[back, -1, ::-1]

        padded[front, 1:-1, 0] = cube_faces[left, :, -1]
        padded[front, 1:-1, -1] = cube_faces[right, :, 0]
        padded[right, 1:-1, 0] = cube_faces[front, :, -1]
        padded[right, 1:-1, -1] = cube_faces[back, :, 0]
        padded[back, 1:-1, 0] = cube_faces[right, :, -1]
        padded[back, 1:-1, -1] = cube_faces[left, :, 0]
        padded[left, 1:-1, 0] = cube_faces[back, :, -1]
        padded[left, 1:-1, -1] = cube_faces[front, :, 0]
        padded[up, 1:-1, 0] = cube_faces[left, 0, :]
        padded[up, 1:-1, -1] = cube_faces[right, 0, ::-1]
        padded[down, 1:-1, 0] = cube_faces[left, -1, ::-1]
        padded[down, 1:-1, -1] = cube_faces[right, -1, :]

        return padded

    @staticmethod
    def _sample_cubemap_faces(cube_faces, face_type, coor_x, coor_y, mode: str):
        mode = mode.lower()
        if mode not in {"nearest", "linear", "bilinear"}:
            raise ValueError(f'unsupported cubemap interpolation mode "{mode}"')

        padded = BitmapTag._pad_cubemap_faces(cube_faces)
        coor_x = coor_x + 1
        coor_y = coor_y + 1

        if mode == "nearest":
            x = np.rint(coor_x).astype(np.int32)
            y = np.rint(coor_y).astype(np.int32)
            x.clip(0, padded.shape[2] - 1, out=x)
            y.clip(0, padded.shape[1] - 1, out=y)
            return padded[face_type, y, x]

        x0 = np.floor(coor_x).astype(np.int32)
        y0 = np.floor(coor_y).astype(np.int32)
        x1 = x0 + 1
        y1 = y0 + 1
        x0.clip(0, padded.shape[2] - 1, out=x0)
        x1.clip(0, padded.shape[2] - 1, out=x1)
        y0.clip(0, padded.shape[1] - 1, out=y0)
        y1.clip(0, padded.shape[1] - 1, out=y1)

        x_weight = (coor_x - x0)[..., None]
        y_weight = (coor_y - y0)[..., None]
        top_left = padded[face_type, y0, x0].astype(np.float32)
        top_right = padded[face_type, y0, x1].astype(np.float32)
        bottom_left = padded[face_type, y1, x0].astype(np.float32)
        bottom_right = padded[face_type, y1, x1].astype(np.float32)

        top = top_left * (1 - x_weight) + top_right * x_weight
        bottom = bottom_left * (1 - x_weight) + bottom_right * x_weight
        sampled = top * (1 - y_weight) + bottom * y_weight

        if np.issubdtype(cube_faces.dtype, np.integer):
            sampled = np.clip(sampled + 0.5, 0, np.iinfo(cube_faces.dtype).max)
            return sampled.astype(cube_faces.dtype)

        return sampled.astype(cube_faces.dtype, copy=False)

    @staticmethod
    def _cubemap_faces_to_equirectangular(faces: dict, height: int, width: int, mode: str):
        cube_faces = np.stack([faces[name] for name in "FRBLUD"], axis=0)
        if cube_faces.shape[1] != cube_faces.shape[2]:
            raise ValueError("cubemap faces must be square")

        face_type, coor_x, coor_y = BitmapTag._cubemap_equirectangular_coordinates(cube_faces.shape[1], height, width)
        return BitmapTag._sample_cubemap_faces(cube_faces, face_type, coor_x, coor_y, mode)

    def cubemap_to_equirectangular(self, bitmap, mode: str = "bilinear"):
        from System.Drawing import Bitmap # type: ignore
        from System import Array, Byte # type: ignore
        from System.Runtime.InteropServices import Marshal # type: ignore
        from System.Drawing import Rectangle, Imaging # type: ignore

        w, h = bitmap.Width, bitmap.Height
        bmp_data = bitmap.LockBits(
            Rectangle(0, 0, w, h),
            Imaging.ImageLockMode.ReadOnly,
            Imaging.PixelFormat.Format32bppArgb
        )
        stride = bmp_data.Stride
        buf = Array.CreateInstance(Byte, stride * h)
        Marshal.Copy(bmp_data.Scan0, buf, 0, buf.Length)
        bitmap.UnlockBits(bmp_data)

        np_buf = np.frombuffer(bytearray(buf), dtype=np.uint8)
        np_buf = np_buf.reshape((h, stride))[:, : w * 4] 
        img_rgba = np_buf.reshape((h, w, 4))
        img_rgb  = img_rgba[..., [2, 1, 0]]

        def face(x: int, y: int, size: int):
            return img_rgb[y * size:(y + 1) * size, x * size:(x + 1) * size]

        if w % 4 == 0 and h % 3 == 0 and w // 4 == h // 3:
            f = w // 4
            faces = {
                "U": face(0, 0, f),
                "D": face(0, 2, f),
                "F": face(0, 1, f),
                "R": face(1, 1, f),
                "B": face(2, 1, f),
                "L": face(3, 1, f),
            }
        elif h == w * 6:
            f = w
            order = ("R", "L", "U", "D", "F", "B")
            faces = {name: img_rgb[index * f:(index + 1) * f, 0:f] for index, name in enumerate(order)}
        elif w == h * 6:
            f = h
            order = ("R", "L", "U", "D", "F", "B")
            faces = {name: img_rgb[0:f, index * f:(index + 1) * f] for index, name in enumerate(order)}
        else:
            raise ValueError(f"unsupported cubemap bitmap layout {w}x{h}")


        out_h = f * 2
        out_w = f * 4

        equi = self._cubemap_faces_to_equirectangular(faces, out_h, out_w, mode)

        equi_bgr = equi[..., ::-1].copy(order='C')
        out_bmp  = Bitmap(out_w, out_h,
                        Imaging.PixelFormat.Format24bppRgb)
        out_data = out_bmp.LockBits(
            Rectangle(0, 0, out_w, out_h),
            Imaging.ImageLockMode.WriteOnly,
            out_bmp.PixelFormat
        )
        dest_stride = out_data.Stride
        row_bytes = out_w * 3
        for y in range(out_h):
            Marshal.Copy(
                Array[Byte](bytearray(equi_bgr[y].ravel())),
                0,
                out_data.Scan0 + y * dest_stride,
                row_bytes
            )
        out_bmp.UnlockBits(out_data)
        return out_bmp

    
    def _convert_cubemap(self, bitmap, suffix):
        equirect = self.cubemap_to_equirectangular(bitmap)
        return equirect, str(Path(self.data_dir, f"{self.tag_path.RelativePath}{suffix}_equirectangular").with_suffix('.tiff'))
    
    @staticmethod
    def _dotnet_bytes_to_bytes(data) -> bytes:
        if data is None:
            return b""
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray):
            return bytes(data)
        try:
            return bytes(data)
        except TypeError:
            return bytes(bytearray(data))

    @staticmethod
    def _select_int(element, field_path: str, default=0) -> int:
        try:
            field = element.SelectField(field_path)
        except Exception:
            return default
        for attr in ("Data", "Value"):
            if hasattr(field, attr):
                try:
                    return int(getattr(field, attr))
                except Exception:
                    pass
        try:
            return int(field.GetStringData())
        except Exception:
            return default

    @staticmethod
    def _expand_bits(values, bits: int):
        maximum = (1 << bits) - 1
        return ((values.astype(np.uint16) * 255 + maximum // 2) // maximum).astype(np.uint8)

    @classmethod
    def _decode_uncompressed_bitmap_rgba(cls, width: int, height: int, bitmap_format: int, data: bytes) -> bytes | None:
        bytes_per_pixel = UNCOMPRESSED_BITMAP_BYTES_PER_PIXEL.get(bitmap_format)
        if bytes_per_pixel is None:
            return None

        expected_size = width * height * bytes_per_pixel
        if width <= 0 or height <= 0 or len(data) < expected_size:
            return None

        data = data[:expected_size]
        rgba = np.empty((height, width, 4), dtype=np.uint8)

        match bitmap_format:
            case 0:  # A8
                alpha = np.frombuffer(data, dtype=np.uint8).reshape(height, width)
                rgba[..., 0] = 0
                rgba[..., 1] = 0
                rgba[..., 2] = 0
                rgba[..., 3] = alpha
            case 1:  # Y8
                luminance = np.frombuffer(data, dtype=np.uint8).reshape(height, width)
                rgba[..., 0] = luminance
                rgba[..., 1] = luminance
                rgba[..., 2] = luminance
                rgba[..., 3] = 255
            case 2:  # AY8
                value = np.frombuffer(data, dtype=np.uint8).reshape(height, width)
                rgba[..., 0] = value
                rgba[..., 1] = value
                rgba[..., 2] = value
                rgba[..., 3] = value
            case 3:  # A8Y8; source bytes are alpha, luminance.
                ay = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 2)
                rgba[..., 0] = ay[..., 1]
                rgba[..., 1] = ay[..., 1]
                rgba[..., 2] = ay[..., 1]
                rgba[..., 3] = ay[..., 0]
            case 6:  # R5G6B5
                values = np.frombuffer(data, dtype="<u2").reshape(height, width)
                rgba[..., 0] = cls._expand_bits((values >> 11) & 0x1F, 5)
                rgba[..., 1] = cls._expand_bits((values >> 5) & 0x3F, 6)
                rgba[..., 2] = cls._expand_bits(values & 0x1F, 5)
                rgba[..., 3] = 255
            case 8:  # A1R5G5B5
                values = np.frombuffer(data, dtype="<u2").reshape(height, width)
                rgba[..., 0] = cls._expand_bits((values >> 10) & 0x1F, 5)
                rgba[..., 1] = cls._expand_bits((values >> 5) & 0x1F, 5)
                rgba[..., 2] = cls._expand_bits(values & 0x1F, 5)
                rgba[..., 3] = np.where((values & 0x8000) != 0, 255, 0).astype(np.uint8)
            case 9:  # A4R4G4B4
                values = np.frombuffer(data, dtype="<u2").reshape(height, width)
                rgba[..., 0] = cls._expand_bits((values >> 8) & 0x0F, 4)
                rgba[..., 1] = cls._expand_bits((values >> 4) & 0x0F, 4)
                rgba[..., 2] = cls._expand_bits(values & 0x0F, 4)
                rgba[..., 3] = cls._expand_bits((values >> 12) & 0x0F, 4)
            case 10 | 11:  # X8R8G8B8 / A8R8G8B8; source bytes are BGRA.
                bgra = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)
                rgba[..., 0] = bgra[..., 2]
                rgba[..., 1] = bgra[..., 1]
                rgba[..., 2] = bgra[..., 0]
                rgba[..., 3] = bgra[..., 3] if bitmap_format == BITMAP_FORMAT_A8R8G8B8 else 255
            case _:
                return None

        return rgba.tobytes()

    @staticmethod
    def _tiff_entry(tag: int, field_type: int, count: int, value: int):
        if field_type == 3 and count == 1:
            value_data = struct.pack("<H", value) + b"\x00\x00"
        elif field_type == 4 and count == 1:
            value_data = struct.pack("<I", value)
        else:
            value_data = struct.pack("<I", value)
        return struct.pack("<HHI", tag, field_type, count) + value_data

    @classmethod
    def _write_rgba_tiff(cls, path: str, width: int, height: int, rgba: bytes):
        entries = 11
        ifd_offset = 8
        ifd_size = 2 + entries * 12 + 4
        bits_per_sample = struct.pack("<HHHH", 8, 8, 8, 8)
        extra_samples = struct.pack("<H", 2)
        bits_offset = ifd_offset + ifd_size
        extra_offset = bits_offset + len(bits_per_sample)
        pixel_offset = extra_offset + len(extra_samples)

        ifd = bytearray()
        ifd += struct.pack("<H", entries)
        ifd += cls._tiff_entry(256, 4, 1, width)              # ImageWidth
        ifd += cls._tiff_entry(257, 4, 1, height)             # ImageLength
        ifd += cls._tiff_entry(258, 3, 4, bits_offset)        # BitsPerSample
        ifd += cls._tiff_entry(259, 3, 1, 1)                  # Compression: none
        ifd += cls._tiff_entry(262, 3, 1, 2)                  # PhotometricInterpretation: RGB
        ifd += cls._tiff_entry(273, 4, 1, pixel_offset)       # StripOffsets
        ifd += cls._tiff_entry(277, 3, 1, 4)                  # SamplesPerPixel
        ifd += cls._tiff_entry(278, 4, 1, height)             # RowsPerStrip
        ifd += cls._tiff_entry(279, 4, 1, len(rgba))          # StripByteCounts
        ifd += cls._tiff_entry(284, 3, 1, 1)                  # PlanarConfiguration: chunky
        ifd += cls._tiff_entry(338, 3, 1, 2)  # ExtraSamples: unassociated alpha
        ifd += struct.pack("<I", 0)

        with open(path, "wb") as handle:
            handle.write(b"II")
            handle.write(struct.pack("<H", 42))
            handle.write(struct.pack("<I", ifd_offset))
            handle.write(ifd)
            handle.write(bits_per_sample)
            handle.write(extra_samples)
            handle.write(rgba)

    def _raw_tiff_save_path(self, suffix: str):
        if suffix:
            return str(Path(self.data_dir, self.tag_path.RelativePath, f"{self.tag_path.ShortName}{suffix}").with_suffix('.tiff'))
        return str(Path(self.data_dir, self.tag_path.RelativePath).with_suffix('.tiff'))

    def _save_single_raw_tiff(self, frame_index: int, suffix: str) -> str | None:
        if self.is_cubemap:
            return None

        bitmap_elements = self.block_bitmaps.Elements
        if frame_index < 0 or frame_index >= bitmap_elements.Count:
            return None

        bitmap_element = bitmap_elements[frame_index]
        width = self._select_int(bitmap_element, "ShortInteger:width")
        height = self._select_int(bitmap_element, "ShortInteger:height")
        bitmap_type = self._select_int(bitmap_element, "CharEnum:type")
        bitmap_format = self._select_int(bitmap_element, "ShortEnum:format", -1)
        pixels_offset = self._select_int(bitmap_element, "LongInteger:pixels offset", -1)
        pixels_size = self._select_int(bitmap_element, "LongInteger:pixels size", -1)

        if bitmap_type != 0 or bitmap_format not in UNCOMPRESSED_BITMAP_FORMAT_NAMES:
            return None
        if pixels_offset < 0 or pixels_size <= 0:
            return None

        processed_data_field = self.tag.SelectField("Data:processed pixel data")
        processed_data = self._dotnet_bytes_to_bytes(processed_data_field.GetData())
        end = pixels_offset + pixels_size
        if end > len(processed_data):
            return None

        rgba = self._decode_uncompressed_bitmap_rgba(width, height, bitmap_format, processed_data[pixels_offset:end])
        if rgba is None:
            return None

        save_path = self._raw_tiff_save_path(suffix)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        self._write_rgba_tiff(save_path, width, height, rgba)
        return save_path

    def _save_single(self, blue_channel_fix: bool, format: str, frame_index: int, suffix: str):
        if format == 'tiff':
            try:
                raw_tiff_path = self._save_single_raw_tiff(frame_index, suffix)
            except Exception as exc:
                utils.print_warning(f"Failed raw bitmap tiff export for {self.tag_path.RelativePath}: {exc}")
                raw_tiff_path = None
            if raw_tiff_path:
                return raw_tiff_path

        game_bitmap = self._GameBitmap(frame_index=frame_index)
        bitmap = game_bitmap.GetBitmap()
        game_bitmap.Dispose()
        
        from System.Drawing import Rectangle # type: ignore
        from System.Drawing.Imaging import ImageLockMode, ImageFormat, PixelFormat # type: ignore
        
        single_pixel = (game_bitmap.Height == 1 and game_bitmap.Width == 1)

        if bitmap.PixelFormat == PixelFormat.Format32bppArgb and (blue_channel_fix or self.curve.Value != 5):
            rectangle = Rectangle(0, 0, bitmap.Width, bitmap.Height)
            data = bitmap.LockBits(rectangle, ImageLockMode.ReadWrite, bitmap.PixelFormat)
            try:
                height, width = data.Height, data.Width
                stride = data.Stride

                address = data.Scan0.ToInt64() if sys.maxsize > 2**32 else data.Scan0.ToInt32()
                if stride < 0:
                    address += (height - 1) * (-stride)
                    stride = -stride

                rowbytes = width * 4
                total = stride * height

                buf_t = ctypes.c_ubyte * total
                buf = buf_t.from_address(address)

                array = np.ctypeslib.as_array(buf).reshape(height, stride)[:, :rowbytes].reshape(height, width, 4)

                B = array[..., 0]
                G = array[..., 1]
                R = array[..., 2]
                
                if blue_channel_fix:
                    if self.normal_type() == NormalType.OPENGL:
                        # ManagedBlam's debug plate stores standard-orientation normals with the axes swapped.
                        managed_r = R.copy()
                        managed_g = G.copy()
                        R[:] = managed_g
                        G[:] = 255 - managed_r

                    # ManagedBlam's debug plate is display-oriented; darken R/G back before reconstructing Z.
                    R[:] = NORMAL_DEBUG_GAMMA_LOOKUP_NP[R]
                    G[:] = NORMAL_DEBUG_GAMMA_LOOKUP_NP[G]

                    r = R.astype(np.float32) / 255.0
                    g = G.astype(np.float32) / 255.0
                    x = r * 2.0 - 1.0
                    y = g * 2.0 - 1.0
                    b = np.sqrt(np.clip(1.0 - x*x - y*y, 0.0, 1.0)) * 0.5 + 0.5
                    B[:] = (b * 255.0 + 0.5).astype(np.uint8)
                else:
                    if single_pixel or self.curve.Value == 3:
                        lookup_table = (np.round(((np.arange(256) / 255.0) ** 2.2) * 255)).astype(np.uint8)
                    elif self.curve.Value == 1:
                        lookup_table = (np.round(((np.arange(256) / 255.0)) * 255)).astype(np.uint8)
                    else:
                        lookup_table = (np.round(((np.arange(256) / 255.0) ** (2.2/2.0)) * 255)).astype(np.uint8)

                    r_linear = lookup_table[R]
                    g_linear = lookup_table[G]
                    b_linear = lookup_table[B]
                    
                    R[:] = r_linear
                    G[:] = g_linear
                    B[:] = b_linear

            finally:
                bitmap.UnlockBits(data)
        
        tiff_path = str(Path(self.data_dir, self.tag_path.RelativePath).with_suffix('.tiff'))
        if suffix: # we're dealing with a plate
            save_path = str(Path(self.data_dir, self.tag_path.RelativePath, f"{self.tag_path.ShortName}{suffix}").with_suffix('.tiff'))
        else:
            save_path = tiff_path
            
        tiff_dir = os.path.dirname(save_path)
        
        if not os.path.exists(tiff_dir):
            os.makedirs(tiff_dir, exist_ok=True)
        try:
            if self.is_cubemap:
                # save the original cubemap
                    match format:
                        case 'bmp':
                            bitmap.Save(save_path, ImageFormat.Bmp)
                        case 'png':
                            bitmap.Save(save_path, ImageFormat.Png)
                        case 'jpeg':
                            bitmap.Save(save_path, ImageFormat.Jpeg)
                        case 'tiff':
                            bitmap.Save(save_path, ImageFormat.Tiff)
                    try:
                        bitmap, tiff_path = self._convert_cubemap(bitmap, suffix)
                    except Exception as exc:
                        utils.print_warning(f"Failed to convert cubemap tiff: {save_path}: {exc}")
                        
                    save_path = tiff_path

            match format:
                case 'bmp':
                    bitmap.Save(save_path, ImageFormat.Bmp)
                case 'png':
                    bitmap.Save(save_path, ImageFormat.Png)
                case 'jpeg':
                    bitmap.Save(save_path, ImageFormat.Jpeg)
                case 'tiff':
                    bitmap.Save(save_path, ImageFormat.Tiff)
        except:
            utils.print_warning(f"Failed to save tiff: {save_path}")
                
        bitmap.Dispose()
        return tiff_path
        
    def save_to_tiff(self, blue_channel_fix=False, format='tiff') -> list[str]:
        global path_cache
        expected_tiff_path = Path(self.data_dir, self.tag_path.RelativePath).with_suffix('.tiff')
        expected_tif_path = expected_tiff_path.with_suffix('.tif')
        if expected_tiff_path in path_cache and expected_tiff_path.exists():
            return expected_tiff_path
        elif expected_tif_path in path_cache and expected_tif_path.exists():
            return expected_tif_path
        
        
        if self.block_bitmaps.Elements.Count <= 0:
            return
        gamma = self.get_gamma_value()
        self.curve = self.block_bitmaps.Elements[0].SelectField("CharEnum:curve")
        # if not blue_channel_fix and self.curve.Value != 3: #dxt5
        #     self.curve.Value = 5
        bitmap_elements = self.block_bitmaps.Elements
        if bitmap_elements.Count > 1:
            # array_length = bitmap_elements.Count
            for element in bitmap_elements:
                temp_path = self._save_single(blue_channel_fix, format, element.ElementIndex, f"_{element.ElementIndex + 1:05}")
                if element.ElementIndex == 0:
                    tiff_path = temp_path
            
            
            if not self.is_cubemap:
                full_tiff_path = Path(tiff_path)
                utils.run_tool(["plate", str(full_tiff_path.with_suffix(""))], null_output=True)
                # create plate but no longer use it blender
        else:
            tiff_path = self._save_single(blue_channel_fix, format, 0, "")
        
        
        path_cache.add(tiff_path)
        return tiff_path
    
    def normal_type(self):
        return NormalType.OPENGL if self.longenum_usage.Value == 36 else NormalType.DIRECTX
    
    def has_bitmap_data(self):
        return self.block_bitmaps.Elements.Count
    
    def is_linear(self):
        bm = self.block_bitmaps.Elements[0]
        return bm.SelectField('curve').Value == 3
    
    def used_as_normal_map(self):
        return self.longenum_usage.Value in {2, 3, 18, 19, 20, 21, 36, 38}
    
    def uses_srgb(self):
        return self.longenum_usage.Value in {0, 5, 7}
    
    def get_gamma_name(self) -> str:
        bm = self.block_bitmaps.Elements[0]
        match bm.SelectField('curve').Value:
            case 3:
                return 'linear'
            case 5:
                return 'srgb'
            case _:
                return 'xrgb'
            
    def get_gamma_value(self) -> str:
        bm = self.block_bitmaps.Elements[0]
        match bm.SelectField('curve').Value:
            case 0:
                return 1.95
            case 1:
                return 1.95
            case 2:
                return 2.0
            case 3:
                return 1.0
            case 4:
                return 1.0
            case 5:
                return 2.2
    
    def _source_gamma_from_color_space(self, color_space: str):
        match color_space:
            case 'sRGB':
                return 2.2
        
        return 1.0 # NOTE keeping this 1.0 as 0.96 seems dangerous and needs further testing. 0.96 produces more accurate colors than 1.0
    
    def get_shader_type(self):
        items = [i.DisplayName for i in self.longenum_usage.Items]
        return items[self.longenum_usage.Value]
            
def lerp(p1: float, p2: float, fraction: float) -> float:
    return (p1 * (1 - fraction)) + (p2 * fraction)

def calculate_z_vector(r: float, g: float) -> float:
    x = lerp(-1.0, 1.0, r)
    y = lerp(-1.0, 1.0, g)
    z = sqrt(max(0, 1 - x * x - y * y))

    return (z + 1) / 2
