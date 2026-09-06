"""Persistent bitmap worker. Only the private spool directory is writable here."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codec import load_codec
from protocol import VERSION, JOB_ID, atomic_json, digest, reservation, validate_recipe


def parent_alive(pid):
    if os.name != 'nt':
        return os.getppid() == pid
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel.CloseHandle(handle)


def process(folder, request, codec, fingerprint):
    token = request['id']
    if not isinstance(token, str) or JOB_ID.fullmatch(token) is None:
        raise ValueError('Invalid bitmap job identity')
    job = folder.parent / token
    started = time.perf_counter()
    result = {'version': VERSION, 'id': token, 'pid': os.getpid(), 'codec': fingerprint}
    try:
        if request['version'] != VERSION:
            raise ValueError('Bitmap worker protocol mismatch')
        recipe = validate_recipe(request['recipe'])
        payload_path = job / 'pixels.bin'
        if payload_path.stat().st_size != request['payload_size']:
            raise ValueError('Bitmap payload length mismatch')
        if reservation(recipe, request['payload_size']) > request['budget']:
            raise ValueError('Bitmap job exceeds reservation')
        if digest(payload_path) != request['payload_sha256']:
            raise ValueError('Bitmap payload checksum mismatch')
        pixels = payload_path.read_bytes()
        begin = time.perf_counter()
        width, height = recipe['width'], recipe['height']
        rgba = codec._decode_bitmap_rgba(width, height * (6 if recipe['cubemap'] else 1),
                                         recipe['format'], pixels)
        if rgba is None:
            raise ValueError('Bitmap decoder rejected the payload')
        result['decode_seconds'] = time.perf_counter() - begin
        begin = time.perf_counter()
        if recipe['convert']:
            rgba = codec._convert_xrgb_rgba_to_srgb(rgba, recipe['gamma'])
        result['color_seconds'] = time.perf_counter() - begin
        begin = time.perf_counter()
        codec._write_rgba_tiff(str(job / 'raw.tiff'), width, height * (6 if recipe['cubemap'] else 1), rgba)
        result['write_seconds'] = time.perf_counter() - begin
        result['cubemap_seconds'] = 0.0
        outputs = ['raw.tiff']
        if recipe['cubemap']:
            begin = time.perf_counter()
            eq = codec._cubemap_vertical_rgba_to_equirectangular(rgba, width)
            result['cubemap_seconds'] = time.perf_counter() - begin
            begin = time.perf_counter()
            codec._write_rgba_tiff(str(job / 'equirectangular.tiff'), width * 4, height * 2, eq)
            result['write_seconds'] += time.perf_counter() - begin
            outputs.append('equirectangular.tiff')
        result['files'] = {name: {'bytes': (job / name).stat().st_size, 'sha256': digest(job / name)}
                           for name in outputs}
        result['ok'] = True
    except Exception as error:
        result.update(ok=False, error=f'{type(error).__name__}: {error}')
    result['elapsed_seconds'] = time.perf_counter() - started
    atomic_json(job / 'result.json', result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', required=True)
    parser.add_argument('--parent', type=int, required=True)
    args = parser.parse_args()
    folder = Path(args.folder).resolve()
    codec, fingerprint = load_codec()
    if any(name in sys.modules for name in ('bpy', 'clr', 'pythonnet')):
        raise RuntimeError('Host API imported into bitmap worker')
    atomic_json(folder / 'ready.json', {'version': VERSION, 'codec': fingerprint, 'pid': os.getpid()})
    previous = None
    while parent_alive(args.parent) and not (folder / 'stop').exists():
        request_path = folder / 'request.json'
        if request_path.exists():
            request = json.loads(request_path.read_text(encoding='utf-8'))
            if request.get('id') != previous:
                process(folder, request, codec, fingerprint)
                previous = request['id']
        time.sleep(0.01)


if __name__ == '__main__':
    main()
