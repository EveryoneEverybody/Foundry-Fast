"""Synthetic decoding benchmark; excludes ManagedBlam and Blender construction."""
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
from test_bitmap_workers import CODEC, payload, recipe, serial_outputs
from bitmap_workers.pool import Pool

size=int(sys.argv[1]) if len(sys.argv)>1 else 512
specs=[recipe(width=size,height=size,fmt=16,convert=True) for _ in range(8)]
inputs=[payload(r) for r in specs]
with tempfile.TemporaryDirectory() as folder:
    begin=perf_counter()
    expected=[serial_outputs(folder,r,p) for r,p in zip(specs,inputs)]
    serial=perf_counter()-begin
    results={}
    for workers in (2,4):
        begin=perf_counter();pool=Pool(sys.executable,workers=workers)
        try:
            next_job=0
            for i in range(len(specs)):
                while next_job<len(specs) and pool.room():
                    job=pool.submit(next_job,specs[next_job],inputs[next_job])
                    if job is None:break
                    next_job+=1
                output=pool.take(i)
                assert {name:path.read_bytes() for name,path in output.items()}==expected[i]
                pool.release(i)
        finally:pool.close()
        results[str(workers)]={'seconds':perf_counter()-begin,'stats':dict(pool.stats)}
    print(json.dumps({'fixture':f'8 distinct {size}x{size} DXT5 conversions, xRGB to sRGB',
                      'serial_seconds':serial,'parallel':results},indent=2))
