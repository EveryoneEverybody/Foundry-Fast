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
experiments are outside this session. At Nate's subsequent request, the four
diagnostic BSP010 lighting files were restored to their baseline hashes. The
current warm/cool shader files and all 50 proof_box hashes were verified after
that switch (`restore-baseline-result.json`).

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

The complete source plan now resolves nine BSPs, eight structure designs,
nineteen authored zones and ten seams. The zone named `all` retains mask 255;
BSP008 belongs to specific later zones. No synthetic mask-511 zone is created.
Source vertex indices preserve seam topology across bounded XML/compile
coordinate differences. Native no-way portal authoring preserves visibility
barriers. One mixed glass/frame definition has a verified material partition:
both parts retain the source transform, with unified glass and solid frame
collision authored separately. Six invalid source lighting-row indices retain
their embedded properties and explicit deferred lighting status.

Forty-two focused Python checks passed at this checkpoint (scenario translation,
campaign selection, glass/seam contracts). Source-plan acceptance does not imply
native Tool acceptance or runtime success. The first complete native build is
the next validation stage.

The shared object decoder has inspected 136 distinct scenery/crate/machine/
control dependencies. The current source plan admits 91: 28 scenery, 50 crates,
10 machines and 3 controls. Remaining objects retain exact missing-dependency,
material-function, physics or source-group blockers. Device animations are
decoded through the existing H3 animation helper into normal JMA authoring;
native graph and button/door validation remain pending at this checkpoint.
No unit or vehicle animation path is introduced.

`run_h3_scenario_objects.py` shares the environment's exact-file ownership
manifest and target lock. Source metadata, material staging, object dependency
authoring and scenario placements are separate reusable layers. Native enums
and flags match by name, since H3 and Reach bit orders differ. Eight object
identity/type tests and the 26 scenario/remaining-rule checks passed locally.
Native validation will decide which planned objects enter the scenario.

The placement adapter explicitly records a bind-pose approximation for packed
H3 stored poses (404 source crate placements); no packed pose stream is copied.
Unsupported parents close over their dependent placements instead of silently
detaching them. Source device-group indices and duplicate group names survive.
Emission animation on otherwise supported object materials is staticized at
the pinned source state; BSP lighting is unaffected.
