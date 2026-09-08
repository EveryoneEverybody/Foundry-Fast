# Full 040_voi native scenario milestone

The scope now includes all authored scenario BSPs and zone sets, followed by
scenery, crates, device machines and device controls through shared object and
placement representations. Native output is isolated under
`levels/h3_port/040_voi/full_scenario`. The accepted Factory A environment and
all 50 proof_box files remain protected regression fixtures. No push or release
is authorized for this milestone.

Factory A lighting fidelity: **DEFERRED / technically responsive material-power
path but no meaningful visible runtime improvement from diagnostic Power25.**
Nate reports no perceptible difference in the clean Power25 runtime comparison.
No multiplier is accepted. Further attenuation, brightness and Low-bake
experiments are outside this session. The installed diagnostic files are
preserved as found; this is not lighting acceptance.

Nate's latest user-owned shader settings are warm self illumination 3 and cool
1. Protect the current installed bytes instead of restoring an earlier shader
manifest. The installed H3EK experimental `outtree_bark.shader` is also protected;
the preserved original source recipe remains authoritative for conversion.

`scenario_ir.py` separates complete source accounting from native generation.
All authored masks retain source and target indices. A decode union includes
every BSP but never becomes a synthetic all-active target zone. In particular,
the H3 zone named `all` does not imply every scenario BSP is active.

Machine-readable evidence starts at
`D:\HaloRE\PortCensus\voi_full_scenario_20260908`. Runtime status remains
`NOT_TESTED` until Nate tests the new target in Tag Test. AI, units, vehicles,
HSC, character animation and vehicle-specific physics remain deferred.
