# Voi runtime stabilization

Nate accepted prototype 1.9.49 for core BSP conversion at `789848bd1fb7ab88d6507a6b792d298d030eefb8`. Preserve the working collision, ladders, breakable glass, materials and sunlight. The earlier 1.9.48 proof_box runtime acceptance remains valid.

This pass is limited to visible H3 sky rendering, the cause of missing BSP010 tunnel illumination, Tag Test seam/leaky/duplicate-triangle diagnostics, and classification of missing Keyship/Voi portal content as sky versus scenario/cinematic resources. AI, HSC and general scenario-object conversion remain outside scope.

Reported symptoms: sunlight works; distant Voi cliffs and their glowing elements are visible in a dark sky; tunnel light textures are visible but do not adequately illuminate the tunnel. These observations are runtime evidence, separate from the previous Tool/Faux/native-readback checks.

The installed scenario tag differs from the packaged 1.9.49 hash. Preserve and inspect that edit before any tag write. The remaining 979 generated files and all 50 proof_box outputs match the preserved build. The local acceptance receipt, runtime-log copies and subsequent investigation live under `D:\HaloRE\PortCensus\voi_runtime_stabilization_20260907`. The existing native archive remains the immutable build backup.
