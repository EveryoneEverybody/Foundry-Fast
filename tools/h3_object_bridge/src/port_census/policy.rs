//! Reviewed initial planning policy, kept separate from schema evidence.
use super::{
    graph::{Graph, extension},
    scenario,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

pub fn strategy(group: &str, local: bool) -> (&'static str, &'static str, &'static str) {
    match group {
        "scenario" => (
            "TRANSLATE_FIXUP",
            "PARTIAL",
            "Generate a Reach scenario from source authored data; rebuild resources and validate names/indices",
        ),
        "scenario_structure_bsp" | "structure_design" | "scenario_structure_lighting_info" => (
            "REBUILD",
            "SOURCE_DECODE_ONLY",
            "Source geometry/lighting metadata is not Reach-native resource data; Tool/Faux rebuild required",
        ),
        "render_model" | "collision_model" | "physics_model" => (
            "REBUILD",
            "PARTIAL",
            "Existing H3 object/JMS decoding and Foundry import provide source representation; per-asset Reach export remains unvalidated",
        ),
        "model" | "scenery" | "crate" | "device_machine" | "machine" | "device_control"
        | "control" | "biped" | "equipment" | "effect_scenery" | "sound_scenery"
        | "device_terminal" => (
            "TRANSLATE_FIXUP",
            "PARTIAL",
            "Remap references around rebuilt resources and Reach gameplay semantics",
        ),
        "vehicle" | "giant" => (
            "TRANSLATE_FIXUP",
            "PARTIAL",
            "Review Reach vehicle systems, seats, damage, AI and animation behavior; stock system replacement may be preferable",
        ),
        "weapon" => (
            "REPLACE",
            "NOT_APPLICABLE",
            "Prefer reviewed Reach gameplay replacement initially; H3 visuals may be rebuilt later",
        ),
        "model_animation_graph" => (
            "REBUILD",
            "PARTIAL",
            "Existing animation helper decodes supported resources; events, networks, skeleton correspondence and stored poses need review",
        ),
        "bitmap" => (
            "REBUILD",
            "PARTIAL",
            "Existing bitmap decoder supports source pixels for supported formats; Reach bitmap import and resource generation remain future work",
        ),
        "shader" => (
            "REBUILD",
            "PARTIAL",
            "Ordinary shaders can reach native Reach node staging when their source snapshot resolves; final tag parity is unproven",
        ),
        g if g.starts_with("shader_") => (
            "REBUILD",
            "SOURCE_DECODE_ONLY",
            "Shader-class-specific reconstruction required; terrain preview is not ordinary Reach node staging",
        ),
        "sky" => (
            "REBUILD",
            "PARTIAL",
            "Use actual source sky geometry/materials and Reach lighting; source preview is not a built Reach sky",
        ),
        "scenario_lightmap" | "scenario_lightmap_bsp_data" => (
            "DROP",
            "NOT_APPLICABLE",
            "Drop source baked lighting payloads and regenerate Reach-native lighting through Faux",
        ),
        "sound" | "sound_looping" | "sound_environment" if local => (
            "REBUILD",
            "SOURCE_DECODE_ONLY",
            "Preserve mission-unique audio through a future source-audio and Reach FSB import pipeline",
        ),
        "sound" | "sound_looping" | "sound_environment" | "dialogue" | "sound_mix"
        | "sound_classes" => (
            "REPLACE",
            "NOT_APPLICABLE",
            "Review a Reach-native generic audio replacement; no FSBs rebuilt by census",
        ),
        "effect" if local => (
            "TRANSLATE_FIXUP",
            "SOURCE_DECODE_ONLY",
            "Mission-local effects need event-specific review and resource rebuilding",
        ),
        "effect" | "particle" | "particle_model" | "projectile" | "damage_effect"
        | "area_screen_effect" => (
            "REPLACE",
            "NOT_APPLICABLE",
            "Prefer a reviewed Reach-native generic effect/gameplay replacement",
        ),
        "character" | "style" => (
            "REPLACE",
            "NOT_APPLICABLE",
            "Prefer Reach-native character/style behavior around the selected H3 visuals and animations",
        ),
        "light" | "light_volume" => (
            "TRANSLATE_FIXUP",
            "SOURCE_DECODE_ONLY",
            "Authored source lighting metadata exists; verified units and Reach authoring mappings remain required",
        ),
        "cinematic" | "cinematic_scene" | "cinematic_scene_data" => (
            "STUB",
            "SOURCE_DECODE_ONLY",
            "Preserve progression control flow; review unsupported cinematic systems individually",
        ),
        "render_method_definition"
        | "render_method_option"
        | "render_method_template"
        | "pixel_shader"
        | "vertex_shader"
        | "global_pixel_shader"
        | "global_vertex_shader" => (
            "REPLACE",
            "NOT_APPLICABLE",
            "Use Reach renderer definitions and shader programs, not H3 runtime shader resources",
        ),
        "scenario_ai_resource" | "scenario_scenery_resource" | "scenario_devices_resource" => (
            "TRANSLATE_FIXUP",
            "SOURCE_DECODE_ONLY",
            "Scenario resource fields require reattachment and target-side validation",
        ),
        _ => (
            "MANUAL",
            "NOT_APPLICABLE",
            "No reviewed automatic policy for this encountered group; inspect schema and ownership evidence",
        ),
    }
}
pub fn capabilities() -> Value {
    json!([
        {"asset":"render geometry / collision / physics","status":"PARTIAL","evidence":["tools/h3_object_bridge/src/main.rs","blender/addons/io_scene_foundry/h3_import/builder.py","tests/blender_h3_import_smoke.py"],"limit":"Decoded/imported assets have not been validated through Reach Tool in this census"},
        {"asset":"scenario / BSP / sky","status":"SOURCE_DECODE_ONLY","evidence":["tools/h3_object_bridge/src/scenario_geometry.rs","blender/addons/io_scene_foundry/h3_import/scenario_content.py","tests/blender_h3_scenario_units_smoke.py"],"limit":"Inspection objects are excluded from Foundry export"},
        {"asset":"ordinary materials","status":"PARTIAL","evidence":["blender/addons/io_scene_foundry/h3_import/reach_materials.py","tests/blender_h3_reach_smoke.py","docs/h3_reach_staging.md"],"limit":"Native nodes only; no proven shader-tag parity"},
        {"asset":"terrain","status":"SOURCE_DECODE_ONLY","evidence":["tests/blender_h3_scenario_materials_smoke.py","docs/h3-scenario-content.md"],"limit":"Specialized source preview; ordinary Reach staging accepts rmsh only"},
        {"asset":"animation / attachments","status":"PARTIAL","evidence":["tools/h3_animation_bridge","tests/blender_h3_animation_smoke.py","tests/blender_h3_scenario_references_smoke.py"],"limit":"Stored-pose codec, pose-dependent attachments and runtime event equivalence remain unresolved"},
        {"asset":"lights","status":"SOURCE_DECODE_ONLY","evidence":["tools/h3_object_bridge/src/semantic.rs","docs/h3-scenario-references.md"],"limit":"No invented intensity/unit mappings"}
    ])
}

fn closure(graph: &Graph, seeds: &[String], allowed: &[&str]) -> Vec<String> {
    let mut visited = BTreeSet::new();
    let mut pending = VecDeque::from(seeds.to_vec());
    while let Some(p) = pending.pop_front() {
        if !visited.insert(p.clone()) {
            continue;
        }
        if let Some(scan) = graph.scans.get(&p) {
            for next in scan.refs.keys() {
                if allowed.contains(&extension(next)) {
                    pending.push_back(next.clone());
                }
            }
        }
    }
    visited.into_iter().collect()
}
pub fn minimum_sets(graph: &Graph, scenario_path: &str) -> (Value, Value) {
    let source = &graph.scans[scenario_path];
    let bsps: Vec<_> = source
        .reference_fields
        .iter()
        .filter(|r| scenario::section(r["address"].as_str().unwrap_or("")) == "structure bsps")
        .filter_map(|r| {
            super::graph::ref_path(
                r["value"]["group"].as_u64()? as u32,
                r["value"]["path"].as_str()?,
            )
            .ok()
        })
        .filter(|p| extension(p) == "scenario_structure_bsp")
        .collect();
    let shaders = [
        "scenario_structure_bsp",
        "structure_design",
        "model",
        "render_model",
        "collision_model",
        "physics_model",
        "bitmap",
        "shader",
        "shader_terrain",
        "shader_foliage",
        "shader_water",
        "shader_custom",
        "shader_environment",
        "light",
        "scenario_structure_lighting_info",
    ];
    let mut boot_candidates = Vec::new();
    let skies: Vec<_> = source
        .reference_fields
        .iter()
        .filter(|r| scenario::section(r["address"].as_str().unwrap_or("")) == "skies")
        .filter_map(|r| {
            super::graph::ref_path(
                r["value"]["group"].as_u64()? as u32,
                r["value"]["path"].as_str()?,
            )
            .ok()
        })
        .collect();
    for bsp in &bsps {
        let mut seeds = vec![bsp.clone()];
        seeds.extend(skies.clone());
        let assets = closure(graph, &seeds, &shaders);
        boot_candidates.push(json!({"bsp":bsp,"source_assets":assets,"selection_basis":"One authored BSP entry and source sky references; access/spawn/zone-set suitability unvalidated"}));
    }
    let mut assets = if let Some(c) = boot_candidates.first() {
        c["source_assets"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|v| v.as_str().map(str::to_owned))
            .collect::<Vec<_>>()
    } else {
        vec![]
    };
    assets.push(scenario_path.into());
    assets.sort();
    assets.dedup();
    let boot = json!({"status":"PROVISIONAL","selection":"lowest_authored_bsp_index_candidate","source_assets":assets,"bsp_candidates":boot_candidates,"required_target_systems":["Generated Reach scenario and matching zone set","Reach-generated BSP render/collision/pathfinding resources","Valid Reach player biped, globals, starting location and spawn configuration","Reach shaders/bitmaps and authored lighting/sky","Reach Faux lighting output or independently validated loadable lighting configuration"],"omitted_source_systems":["optional scenery palettes","full combat graph","cinematics","generic weapon/vehicle/effect resource trees"],"derivation":"Filtered environment/material closure of the first authored BSP, plus generated target requirements. Other BSPs remain candidates. Not a claim of a proven mathematical minimum or loader dependency closure.","proven_target_status":"NOT_TESTED"});
    let squads = scenario::entities(source, "squads");
    let groups = scenario::entities(source, "squad groups");
    let characters = scenario::entities(source, "character palette");
    let weapons = scenario::entities(source, "weapon palette");
    let vehicles = scenario::entities(source, "vehicle palette");
    let mut clusters: BTreeMap<i64, Vec<Value>> = BTreeMap::new();
    for squad in squads {
        let parent = scenario::field(&squad, "parent")
            .and_then(Value::as_i64)
            .unwrap_or(-1);
        clusters.entry(parent).or_default().push(squad);
    }
    let mut candidates = Vec::new();
    for (parent, squads) in clusters {
        let mut seeds = BTreeSet::new();
        let mut team_rows = Vec::new();
        for squad in &squads {
            for row in squad["records"].as_array().unwrap() {
                if let Some(index) = row["value"].as_i64().filter(|n| *n >= 0) {
                    let palette = match row["name"].as_str().unwrap_or("") {
                        "character type" => Some(&characters),
                        "initial weapon" | "initial secondary weapon" => Some(&weapons),
                        "vehicle type" => Some(&vehicles),
                        _ => None,
                    };
                    if let Some(palette) = palette {
                        let matched = palette.iter().find(|v| {
                            v["address"]
                                .as_str()
                                .is_some_and(|a| a.ends_with(&format!("[{index}]")))
                        });
                        if let Some(entry) = matched {
                            if let Some(reference) = scenario::field(entry, "name") {
                                if let (Some(group), Some(name)) =
                                    (reference["group"].as_u64(), reference["path"].as_str())
                                {
                                    if let Ok(p) = super::graph::ref_path(group as u32, name) {
                                        seeds.insert(p);
                                    }
                                }
                            }
                        }
                        team_rows.push(row.clone());
                    }
                }
            }
        }
        let seeds: Vec<_> = seeds.into_iter().collect();
        let set = closure(
            graph,
            &seeds,
            &[
                "character",
                "style",
                "biped",
                "weapon",
                "vehicle",
                "model",
                "render_model",
                "collision_model",
                "physics_model",
                "model_animation_graph",
                "bitmap",
                "shader",
                "shader_terrain",
            ],
        );
        let group = groups.iter().find(|v| {
            v["address"]
                .as_str()
                .is_some_and(|a| a.ends_with(&format!("[{parent}]")))
        });
        candidates.push(json!({"parent_group_index":parent,"parent_group_name":group.and_then(|g|g["name"].as_str()),"squads":squads.iter().map(|s|json!({"name":s["name"],"address":s["address"],"fields":s["fields"]})).collect::<Vec<_>>(),"actor_palette_evidence":team_rows,"source_asset_seeds":seeds,"additional_source_assets":set,"selection_confidence":"UNKNOWN","mission_script_slice":"Unselected; join squad names to scripts.scenario_symbol_uses and inspect activation control flow","required_target_systems":["Reach-native character/style behavior","One traversable combat space and pathfinding","Reviewed weapons and vehicles","Essential Reach sounds/effects or rebuilt mission-specific equivalents"]}));
    }
    let combat = json!({"status":"PROVISIONAL","selected_encounter":null,"base":"minimum_boot_set","candidate_encounter_clusters":candidates,"derivation":"Authored squad-group membership and actor/weapon/vehicle palette indices. Static data alone does not establish which cluster is an early, reachable encounter.","proven_target_status":"NOT_TESTED"});
    (boot, combat)
}

pub fn blockers(graph: &Graph, scripts: &Value, boot: &Value, source: &str) -> Vec<Value> {
    let mut result = Vec::new();
    for (id, severity, message, groups) in [
        (
            "environment_resources",
            "BOOT_BLOCKER",
            "Reach-native BSP/collision/pathfinding and loadable lighting must be rebuilt",
            vec!["scenario_structure_bsp", "structure_design"],
        ),
        (
            "scenario_generation",
            "BOOT_BLOCKER",
            "A generated Reach scenario, valid spawn/player configuration and reference remapping are required",
            vec!["scenario"],
        ),
        (
            "ai_behavior",
            "COMBAT_BLOCKER",
            "Squads, navigation, character/style behavior and gameplay resources need Reach validation",
            vec!["character", "style", "biped", "vehicle", "giant"],
        ),
        (
            "animation_resources",
            "COMBAT_BLOCKER",
            "Animation resources, skeletons, events and vehicle seats require independent validation",
            vec!["model_animation_graph"],
        ),
        (
            "materials",
            "FIDELITY_BLOCKER",
            "Preview/node staging does not prove Reach shader tags or matching rendering",
            vec!["shader", "shader_terrain"],
        ),
        (
            "audio",
            "FIDELITY_BLOCKER",
            "Mission audio needs future decoding/import or reviewed Reach replacements",
            vec!["sound", "sound_looping"],
        ),
    ] {
        let tags: Vec<_> = graph
            .tags
            .keys()
            .filter(|p| groups.contains(&extension(p)))
            .cloned()
            .collect();
        if !tags.is_empty() {
            result.push(json!({"id":id,"severity":severity,"message":message,"source_tags":tags,"evidence_level":"PROVISIONAL","proven_target_status":"NOT_TESTED"}));
        }
    }
    let missing: Vec<_> = graph
        .tags
        .iter()
        .filter(|(_, v)| v["exists"] == false)
        .map(|(p, _)| p.clone())
        .collect();
    if !missing.is_empty() {
        let boot_missing = boot["source_assets"]
            .as_array()
            .unwrap()
            .iter()
            .any(|v| missing.iter().any(|m| v == m));
        result.push(json!({"id":"missing_sources","severity":if boot_missing{"BOOT_BLOCKER"}else{"UNKNOWN"},"message":"Referenced H3 files are missing; runtime necessity needs ownership review","source_tags":missing,"evidence_level":"VERIFIED"}));
    }
    let bad:Vec<_>=scripts["unsupported_call_sites"].as_array().into_iter().flatten().filter(|r|r["classification"]=="UNSUPPORTED"||r["classification"]=="SIGNATURE_CHANGE").map(|r|json!({"name":r["name"],"location":r["location"],"enclosing_script":r["enclosing_script"]})).collect();
    if !bad.is_empty() {
        result.push(json!({"id":"script_control_flow","severity":"MISSION_BLOCKER","message":"Unsupported or changed documented calls require call-site and progression review","call_sites":bad,"evidence_level":"PROVISIONAL"}));
    }
    let cortana: Vec<_> = scripts["unsupported_call_sites"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|r| {
            r["name"]
                .as_str()
                .is_some_and(|s| s.starts_with("cortana_"))
        })
        .map(|r| json!({"name":r["name"],"location":r["location"]}))
        .collect();
    if !cortana.is_empty() {
        result.push(json!({"id":"cortana_presentation","severity":"FIDELITY_BLOCKER","message":"Cortana moment calls lack a documented Reach match; visual stubs require control-flow review","call_sites":cortana,"evidence_level":"PROVISIONAL"}));
    }
    if graph.scans[source]
        .block_counts
        .get("node orientations")
        .is_some_and(|n| *n > 0)
    {
        result.push(json!({"id":"stored_poses","severity":"FIDELITY_BLOCKER","message":"H3 packed stored poses remain undecoded; rest-pose fallback only","evidence_level":"VERIFIED","source_tags":[source]}));
    }
    let failed: Vec<_> = graph
        .tags
        .iter()
        .filter(|(_, t)| {
            t["diagnostics"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|d| d["code"] == "tag_read_failed" || d["code"] == "reader_panicked")
        })
        .map(|(p, _)| p)
        .collect();
    if !failed.is_empty() {
        result.push(json!({"id":"incomplete_source_analysis","severity":"UNKNOWN","message":"Some source tags could not be parsed; declared dependencies may be incomplete","source_tags":failed,"evidence_level":"VERIFIED"}));
    }
    result.sort_by_key(|v| {
        let rank = match v["severity"].as_str().unwrap() {
            "BOOT_BLOCKER" => 0,
            "MISSION_BLOCKER" => 1,
            "COMBAT_BLOCKER" => 2,
            "FIDELITY_BLOCKER" => 3,
            "OPTIONAL" => 4,
            _ => 5,
        };
        (rank, v["id"].as_str().unwrap().to_owned())
    });
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn strategy_does_not_claim_preview_is_export_ready() {
        assert_eq!(strategy("shader_terrain", true).0, "REBUILD");
        assert_eq!(strategy("shader_terrain", true).1, "SOURCE_DECODE_ONLY");
        assert_eq!(strategy("unknown", false).0, "MANUAL");
        assert_eq!(strategy("scenario_lightmap", true).0, "DROP");
    }
}
