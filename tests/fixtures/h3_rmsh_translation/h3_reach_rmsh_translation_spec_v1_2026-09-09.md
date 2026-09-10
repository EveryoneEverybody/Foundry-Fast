# H3 → Reach ordinary shader translation specification
## Draft v1 — 2026-09-09

Purpose: define a deterministic semantic boundary for Halo 3 ordinary `rmsh` materials before Foundry/Reach authoring. This specification is for base transpilation fidelity, not artistic enhancement.

## Architectural contract

`H3 resolved material record`
→ `H3MaterialRecord` (immutable source truth)
→ pure semantic translator
→ `ReachAuthoringPlan`
→ ReachStager / Foundry writer
→ Tool/Faux
→ native Reach tags

The translator must not mutate the H3 record. ReachStager is a writer, not a semantic decision-maker.

Unknown or unproven semantics fail closed as `UNRESOLVED_REQUIRES_RULE`. Silent node-menu fallback (`group_default`) is not valid in the correctness path.

Recommended field origins:

- `H3_DIRECT`
- `H3_TRANSFORM`
- `H3_REPACK`
- `REACH_DERIVED`
- `SYNTHESIZED`
- `UNRESOLVED`

## Shared exact Reach migration equations

### Power → roughness

`R = clamp(0.553772986 * clamp(P, 0.01, 2000)^(-0.4551), 0, 1)`

### Modern roughness → hidden compatibility power

`P = max(0, 0.272909999 * max(R, 0.01)^(-1.3973))`

These are directional engine-authored transforms and are intentionally not algebraic inverses.

### Common specular coefficient fold

For legacy material representations entering the Reach stage-2→3 migration:

- `ASC_new = ASC_old * SC_old`
- `Area_pre = Area_old * SC_old`
- `Env_new = Env_old * SC_old`
- `SC_new = 1`

This migration is not material-model-gated in the recovered Reach upgrader.

### Environment roughness bridge

When legacy `env_roughness_scale` and migrated `roughness` exist:

`env_roughness_offset = 0.5 + 0.5 * roughness * (env_roughness_scale - 1)`

### Analytical roughness synthesis

When legacy `roughness` exists and `analytical_roughness` is absent:

`analytical_roughness = roughness`

### Area normalization

`Area_new = Area_pre / π`

This stage is not material-model-gated in the recovered Reach upgrader.

## Rule: H3 single_lobe_phong → Reach two_lobe_phong

Rule ID:

`h3.single_lobe_phong_to_reach.two_lobe_phong.v1`

The legacy analytical normalization is model-specific:

`ASC_stage1 = ASC_source * roughness^4 * π²`

Then:

- destination model = `two_lobe_phong`
- `ASC_target = ASC_stage1 * SC_source`
- `Area_target = Area_source * SC_source / π`
- `Env_target = Env_source * SC_source`
- `SC_target = 1`
- `roughness_target = roughness_source`
- `analytical_roughness_target = roughness_source`
- derive `env_roughness_offset` from source scale when present

The `roughness^4 * π²` stage applies only to legacy model 7 (`single_lobe_phong`). It must never be applied to H3 two-lobe or Cook-Torrance.

### Single-lobe tint preservation

H3 single-lobe has one `specular_tint`; modern Reach two-lobe has an angle-dependent two-color representation.

For semantic preservation:

- `specular_color_by_angle.color0_normal = H3 specular_tint`
- `specular_color_by_angle.color1_glancing = H3 specular_tint`
- exponent may use the normal Reach default because equal endpoints make it visually irrelevant
- preserve zero albedo tint blend unless source semantics prove otherwise

This avoids losing non-white H3 single-lobe tint during the model migration.

Runtime validation fixture: Voi `asphalt_b`.

## Rule: H3 legacy two_lobe_phong → modern Reach two_lobe_phong

Rule ID:

`h3.two_lobe_phong_to_reach.two_lobe_phong.canonical_v1`

This is Bungie's canonical migration into the modern Reach representation. It is not a claim of pixel-identical H3 BRDF execution.

H3 legacy inputs:

- `normal_specular_power`
- `glancing_specular_power`
- `normal_specular_tint`
- `glancing_specular_tint`
- `fresnel_curve_steepness`
- `albedo_specular_tint_blend`
- `specular_coefficient`
- `analytical_specular_contribution`
- `area_specular_contribution`
- `environment_map_specular_contribution`
- optional `env_roughness_scale`

Target:

1. Material model remains `two_lobe_phong`.
2. Build modern angle-color semantic function:
   - color 0 = legacy `normal_specular_tint`
   - color 1 = legacy `glancing_specular_tint`
   - exponent = legacy `fresnel_curve_steepness`
3. `roughness = power_to_roughness(normal_specular_power)`
4. `glancing_roughness = power_to_roughness(glancing_specular_power)`
5. Fold common SC:
   - `ASC = source_ASC * source_SC`
   - `Area_pre = source_Area * source_SC`
   - `Env = source_Env * source_SC`
   - `SC = 1`
6. Derive environment offset when `env_roughness_scale` exists.
7. `analytical_roughness = roughness`
8. `Area = Area_pre / π`
9. Preserve `albedo_specular_tint_blend`.
10. Reach postprocess may regenerate hidden `normal_specular_power`, `glancing_specular_power`, and `analytical_power` from the modern roughness representation.

### Important representation caveat

Current Reach two-lobe RMOP does not expose `glancing_roughness` as a normal visible authoring field, but ManagedBlam explicitly creates and consumes it in the legacy migration bridge. Therefore `ReachAuthoringPlan` must be able to carry migration/compatibility parameters separately from ordinary visible RMOP inputs. The writer must not silently drop it.

### H3 vs Reach BRDF difference

H3:
- interpolates normal/glancing power for analytical/simple lighting
- interpolates normal/glancing tint, then blends the result with albedo

Modern Reach:
- uses separate `analytical_power` for point/simple lighting
- uses wide `roughness` for area lighting
- computes normal endpoint blended with albedo first, then interpolates toward glancing tint

Therefore exact per-pixel H3 equality is not representable by simply copying parameters. The rule above intentionally reproduces Bungie's canonical modernization.

## Rule: diffuse_only

Status: direct candidate.

No specular parameters should be synthesized merely because generic H3 records contain them. Emit only the target contract for the selected Reach diffuse-only RMOP.

## Cook-Torrance

Status: `UNRESOLVED_FOR_EXACT_BASE_TRANSLATION`.

The common energy migration (SC fold, area normalization, analytical roughness synthesis, environment-offset derivation) is mechanically known, but H3 and modern Reach changed the color/Fresnel semantics:

H3 CT:
- `fresnel_color` is physical F0
- `specular_tint` is an overall specular tint multiplier
- Fresnel is physically evaluated
- `albedo_blend` alters F0 before Fresnel

Modern Reach CT:
- `specular_tint` is the normal-angle artist endpoint
- `fresnel_color` is the glancing artist endpoint
- `fresnel_curve_steepness` controls artist Fresnel interpolation
- albedo blend is applied to the normal endpoint

This is not a field rename. Exact H3 CT cannot be represented by the current Reach CT parameterization for arbitrary albedo/tint values without either a documented approximation or a compatibility shader.

Voi has 11 CT materials and all use `use_material_texture = false`, so the H3 RGBA material-texture incompatibility does not block Voi's dominant shader families.

Do not let Codex invent a CT mapping in v1.

## Material-texture Cook-Torrance

H3 CT material texture:
- R = specular coefficient
- G = albedo blend
- B = environment contribution
- A = roughness

Modern Reach CT material texture uses alpha primarily as an analytical-roughness/specular modifier.

These are not equivalent. Mark H3 CT material-texture cases `UNRESOLVED_REQUIRES_REPACK_OR_COMPAT_SHADER`.

## Runtime/function policy

Resolved constant/value functions may provide effective scalar/color values to the semantic translator, but actual nonconstant/time/external-driven functions must retain their function semantics or be marked unresolved. Do not permanently flatten them to a time-zero sample.

BRDF translation and unrelated self-illumination animation should be tracked separately.

## Voi dependency-closure census

Actual `environment.plan.json` closure:

- `two_lobe_phong`: 140
- `diffuse_only`: 38
- `single_lobe_phong`: 12
- `cook_torrance`: 11
- `.shader_terrain`: 7
- foliage material model: 6
- none: 1
- `.shader_foliage`/default: 1
- glass: 1
- total: 217

The first semantic implementation should target the proven ordinary-rmsh families. Terrain, specialized foliage, glass, halogram/PBR/function blockers remain separate lanes.

## Required tests before regenerating Voi

1. H3 source record remains byte/JSON-identical after translation.
2. `single_lobe_phong` always explicitly selects Reach `two_lobe_phong`.
3. Only single-lobe receives `roughness^4 * π²`.
4. Legacy two-lobe converts both normal and glancing powers through exact `power_to_roughness`.
5. Angle-color endpoints preserve normal→color0 and glancing→color1 ordering.
6. SC folding occurs exactly once.
7. Area normalization occurs exactly once.
8. Missing legacy analytical roughness is derived from migrated roughness.
9. Environment offset is derived from migrated roughness and legacy env scale.
10. `glancing_roughness` cannot be silently lost.
11. Unknown/unproven models fail closed.
12. Existing Reach material staging tests continue to pass.
13. No generated Voi HREK tags are patched in place as the implementation mechanism.
14. Regeneration happens from source through the corrected pipeline.

## Local checkout safety for Codex

Before any Codex edit:

- inspect current local `HEAD`
- inspect `git status`
- preserve all local commits and files
- do not reset, clean, checkout, force-sync, or replace the live local checkout with the older remote prototype branch
- the reported later local HEAD is `896fba134b0ebbba79e7180cde5b66e90be1e18e`, pushed=false; verify locally rather than assuming
