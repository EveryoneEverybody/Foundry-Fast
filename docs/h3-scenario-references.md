# H3 scenario references, prototype 1.9.43

This checkpoint extends 1.9.42. It does not complete the stored-pose acceptance
criterion and is not a claim of Sapien or runtime parity. Inspection remains
separate from Reach conversion. No source or destination tag writing is added.

## Materials

Existing terrain equations remain unchanged when all active bases and supported
blend operations are available. Missing layers, a missing blend map, or an unknown
blend operation now keep the first usable active base in source layer order.
The report calls this a base fallback. It does not invent replacement weights.
No usable active base still produces an explicitly diagnosed placeholder.
Each material report adds BSP index and per-texture source bitmap and connection
status. Original shader descriptions and distinct material identities remain.

## Reference frames

The pinned H3 schema defines an object identifier, node index, projection axis,
and projection-sign flags. It has no parent-frame field. The resolver matches
all four identifier components, validates object and node hierarchy, and combines
the placement transform with the model-space node matrix already consumed by
the existing JMS object builder. It does not apply hierarchy twice.

This is a derived visualization in the placed model's rest pose. Projection
metadata is retained; no 2D navigation projection or runtime object animation is
simulated. Frames requiring an unresolved stored pose are rejected. Missing,
ambiguous, cyclic, mirrored, and invalid dependencies retain explicit reasons.
Raw source positions, frame indices, source object addresses and source frame
fields remain separate from visualization points and matrices.

The detached 040_voi inventory/model check resolves 77 of 79 frame definitions.
Frames 33 and 34 refer to BSP-owned identifiers absent from the scenario placement
table, and remain unresolved. The resulting plan has 572 squad starts, 409 area
means, 4,612 firing positions, 295 script points, two Giant sectors and one rail.
These counts verify joins and computation, not visual or runtime correctness.
The model-node transform interpretation still needs the user's combined 040_voi
visual acceptance test. A Giant hint does not establish a scripted route.

## Child attachments and semantic sources

The existing object helper now retains the child's full tag class and selected
variant. A dependency queue extracts each source once, and the same BuildSession
constructs shared child templates. Unique parent/child marker pairs determine
the relative transform. Missing or ambiguous markers, missing source classes,
unknown variants, and recursive cycles remain diagnostics. Pose-dependent
attachment motion and marker permutation filters remain unsupported.

Sound scenery and light tags return a source-only semantic description instead
of a geometry error. Objects with no model or no render-model reference follow
the same path. Semantic descriptions retain named fields, source addresses,
typed scalar values and raw data blocks. Blender uses reference empties, with
source descriptions packed into Text datablocks. Sound distance and Blender
light energy are not invented. Light color, range and cone displays still need
verified unit and field mappings. Missing files remain distinct from valid
non-render sources and are extracted/reported once per unique source.

## Stored poses: still unsupported

The schema is a node count, signed-byte bit vector and signed-short stream.
Real 040_voi has 63-, 103- and 105-short streams as well as four-aligned streams.
The existing Reach importer disables its quaternion-only decoder with an early
return. Copying it, truncating the stream, or applying by node count alone would
not establish a valid H3 pose. This checkpoint retains the exact stream, validates
ranges and node counts, and explains the fallback. It applies zero stored poses.
A verified rotation/translation codec and node correspondence are still required.

## Diagnostics, timing and remaining work

The detailed content report retains source-specific diagnostics. Console output
groups capability notices and failures by category/count with at most three
representative reasons per category. It does not discard the full report.
Blender phase timings distinguish inclusive/exclusive calls and exclude modal
suspension when measured through a generator. Extraction elapsed time explicitly
includes helper/UI waits. Helper shader timings separate bitmap extraction from
metadata work; BSP timing identifies decode plus source table reads. Unmeasured
phases are absent, not estimates. Separate firing-position, script-point, placement, semantic-object and packed-pose
validation timings are included. Final UI cleanup remains outside the builder
report. Pose application is explicitly unsupported, not reported as a zero-time
success.

Object-relative trigger volumes and parent-relative scenario placements remain
retained without guessed geometry. Their resolver support is not yet enabled in
the placement/trigger visualization path. Script call/reference indexing, further
Reach importer parity, and 070_waste comparison remain follow-up work. 070_waste
must follow successful 040_voi acceptance.

Schema evidence: [pinned scenario definitions](https://github.com/camden-smallwood/definitions/blob/0b21715e93110a28aaf53bc7122bba5d96b496aa/halo3_mcc/scenario.json)
and [model definitions](https://github.com/camden-smallwood/definitions/blob/0b21715e93110a28aaf53bc7122bba5d96b496aa/halo3_mcc/model.json).
