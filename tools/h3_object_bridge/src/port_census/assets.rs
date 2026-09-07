use super::graph::{Graph, extension, normalized};
use anyhow::{Context, Result};
use blam_tags::{
    TagFile,
    render_method::{RenderMethod, RenderMethodDefinition},
};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::PathBuf,
};
#[path = "../material_description.rs"]
mod material_description;
use material_description::OptionSource;

fn lookup<'a>(index: &'a BTreeMap<String, PathBuf>, name: &str, ext: &str) -> Result<&'a PathBuf> {
    index
        .get(&normalized(&format!("{name}.{ext}"))?)
        .with_context(|| format!("Missing source {name}.{ext}"))
}
pub fn materials(graph: &Graph, index: &BTreeMap<String, PathBuf>) -> Vec<Value> {
    let mut rows = Vec::new();
    let mut definitions: BTreeMap<String, RenderMethodDefinition> = BTreeMap::new();
    let mut options: BTreeMap<String, OptionSource> = BTreeMap::new();
    for (path, tag_row) in &graph.tags {
        let group = extension(path);
        if group != "shader" && !group.starts_with("shader_") {
            continue;
        }
        let mut row = json!({"source_path":path,"shader_class":group,"users":tag_row["referenced_by"],"number_of_users":tag_row["referenced_by"].as_array().map(Vec::len),"user_count_basis":"Unique referring tags, not geometry triangle or instance count","preview_status":"UNKNOWN","reach_node_staging_status":"BLOCKED","native_reach_node_staging_capability":group=="shader","native_reach_nodes_created":false,"proven_reach_tag_buildable":"NOT_TESTED","likely_reach_shader_type":if group=="shader_terrain"{"shader_terrain"}else{group},"unresolved_parameters":[],"animated_runtime_parameters":[],"bitmaps":[],"unsupported_behavior":["runtime extern evaluation","animated parameter reconstruction","final Reach tag parity"]});
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<()> {
            let file = index.get(path).context("Missing shader source")?;
            let tag = TagFile::read(file)?;
            let rm = RenderMethod::from_tag(&tag)?;
            let root = tag.root();
            let rm_struct = root.descend("render_method").unwrap_or(root);
            let inherited = rm_struct.read_tag_ref_path("reference").unwrap_or_default();
            if !definitions.contains_key(&rm.definition_path) {
                let definition = RenderMethodDefinition::from_tag(&TagFile::read(lookup(
                    index,
                    &rm.definition_path,
                    "render_method_definition",
                )?)?)?;
                definitions.insert(rm.definition_path.clone(), definition);
            }
            let definition = &definitions[&rm.definition_path];
            let mut selected = BTreeMap::new();
            let mut errors = Vec::new();
            for (i, category) in definition.categories.iter().enumerate() {
                let n = rm.options.get(i).copied().unwrap_or(0);
                if let Some(option) = usize::try_from(n)
                    .ok()
                    .and_then(|n| category.options.get(n))
                {
                    if !option.option_path.is_empty() {
                        let key = &option.option_path;
                        if !options.contains_key(key) {
                            match lookup(index, key, "render_method_option")
                                .and_then(|p| Ok(OptionSource::from_tag(&TagFile::read(p)?)?))
                            {
                                Ok(v) => {
                                    options.insert(key.clone(), v);
                                }
                                Err(e) => errors.push(format!("{e:#}")),
                            }
                        }
                        if let Some(value) = options.get(key) {
                            selected.insert(key.clone(), value.clone());
                        }
                    }
                } else {
                    errors.push(format!("Invalid option {n} for {}", category.category_name));
                }
            }
            let description = if group == "shader" && inherited.is_empty() {
                material_description::describe(&rm, definition, &selected)
            } else {
                material_description::failed(
                    "unsupported_staging_class_or_inheritance",
                    "Ordinary rmsh without reference inheritance is the proven node-staging entry point",
                )
            };
            let description = material_description::finish(path, Some(&tag), description);
            let mut bitmaps = BTreeSet::new();
            for p in &rm.parameters {
                if !p.bitmap_path.is_empty() {
                    bitmaps.insert(normalized(&format!("{}.bitmap", p.bitmap_path))?);
                }
            }
            for p in description["parameters"].as_array().into_iter().flatten() {
                if let Some(bitmap) = p["resolved"]["bitmap"].as_str() {
                    bitmaps.insert(normalized(bitmap)?);
                }
            }
            row["bitmaps"] = json!(
                bitmaps
                    .iter()
                    .map(
                        |p| json!({"path":p,"exists":index.contains_key(p),"pixels_decoded":false})
                    )
                    .collect::<Vec<_>>()
            );
            row["source_description"] = description.clone();
            row["definition"] = json!(rm.definition_path);
            row["reference_shader"] = json!(inherited);
            row["animated_runtime_parameters"] = json!(
                description["parameters"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter(|p| p["animated"] == true || p["origin"] == "engine_extern")
                    .cloned()
                    .collect::<Vec<_>>()
            );
            row["unresolved_parameters"] =
                json!({"load_errors":errors,"diagnostics":description["diagnostics"]});
            let complete = description["parameters"].is_array()
                && description["diagnostics"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .all(|d| {
                        matches!(
                            d["code"].as_str(),
                            Some(
                                "runtime_dependency"
                                    | "animation_not_converted"
                                    | "global_options_not_merged"
                                    | "postprocess_not_applied"
                            )
                        )
                    })
                && errors.is_empty()
                && bitmaps.iter().all(|p| index.contains_key(p));
            row["preview_status"] = json!(if group == "shader_terrain" && errors.is_empty() {
                "TERRAIN_PREVIEW_CAPABLE_NOT_RENDERED"
            } else if complete {
                "SOURCE_SNAPSHOT_RESOLVED_NOT_RENDERED"
            } else {
                "PARTIAL_OR_UNSUPPORTED"
            });
            row["reach_node_staging_status"] = json!(if group == "shader" && complete {
                "SOURCE_ELIGIBLE_TARGET_SOCKETS_UNCHECKED"
            } else {
                "BLOCKED"
            });
            row["evidence"] = json!([
                "Existing material_description::describe/finish",
                "reach_materials.validate_shader supports ordinary rmsh resolved snapshots only",
                "Current source bitmap existence; no pixel decoding or native node creation during census"
            ]);
            Ok(())
        }));
        match outcome {
            Ok(Ok(())) => {}
            Ok(Err(e)) => row["error"] = json!(format!("{e:#}")),
            Err(_) => row["error"] = json!("Material metadata decoder panicked"),
        };
        rows.push(row);
    }
    rows
}

pub fn audio_category(path: &str, owners: &[String], local: bool) -> &'static str {
    let context = format!("{path} {}", owners.join(" ")).to_lowercase();
    if context.contains("music") {
        "music"
    } else if context.contains("cinematic") && context.contains("dialog") {
        "cinematic_dialogue"
    } else if context.contains("dialog")
        && (local || context.contains("mission_dialogue") || context.contains("sound/levels/"))
    {
        "mission_dialogue"
    } else if context.contains("ambien") {
        "ambience"
    } else if context.contains("weapons/") {
        "weapon_sound"
    } else if context.contains("vehicles/") {
        "vehicle_sound"
    } else if context.contains("characters/") {
        "ai_vocalization"
    } else if owners.iter().any(|p| extension(p) == "effect") {
        "effect_sound"
    } else if context.contains("environment") {
        "environmental_sound"
    } else {
        "unknown"
    }
}
pub fn inventories(graph: &Graph, mission_dir: &str) -> (Vec<Value>, Vec<Value>, Vec<Value>) {
    let mut audio = Vec::new();
    let mut effects = Vec::new();
    let mut ai = Vec::new();
    for (path, tag) in &graph.tags {
        let group = extension(path);
        let local = path.starts_with(&format!("{mission_dir}/"));
        let owners: Vec<String> = tag["referenced_by"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|v| v.as_str().map(str::to_owned))
            .collect();
        let scan = &graph.scans[path];
        if group.starts_with("sound") || group == "dialogue" || group == "ai_dialogue_globals" {
            let category = audio_category(path, &owners, local);
            let preserve = matches!(category, "mission_dialogue" | "cinematic_dialogue")
                || (local && matches!(category, "music" | "ambience"));
            let relevant: Vec<_> = scan
                .metadata
                .iter()
                .filter(|r| {
                    [
                        "permutation",
                        "pitch range",
                        "sample",
                        "bank",
                        "fsb",
                        "resource",
                        "codec",
                    ]
                    .iter()
                    .any(|k| {
                        r["address"]
                            .as_str()
                            .unwrap_or("")
                            .to_lowercase()
                            .contains(k)
                    })
                })
                .cloned()
                .collect();
            audio.push(json!({"source_path":path,"category":category,"category_evidence":"PROVISIONAL path and reverse-reference ownership classification","owners":owners,"block_counts":scan.block_counts,"resource_metadata":relevant,"fsb_identification":"Only serialized tag fields when present; external banks not scanned or extracted","strategy":if preserve{"REBUILD"}else{"REPLACE"},"native_replacement_candidates":tag["replacement_candidates"],"proven_target_status":"NOT_TESTED"}));
        }
        if [
            "effect",
            "particle",
            "particle_model",
            "damage_effect",
            "area_screen_effect",
        ]
        .contains(&group)
        {
            let context = format!("{path} {}", owners.join(" "));
            let class = if context.contains("cinematic") {
                "cinematic"
            } else if context.contains("weapons/") {
                "weapon"
            } else if context.contains("projectile") {
                "projectile"
            } else if context.contains("explosion") {
                "explosion"
            } else if context.contains("vehicles/") {
                "vehicle"
            } else if local {
                "mission_specific"
            } else if context.contains("ambient") {
                "ambient"
            } else if context.contains("environment") {
                "environment"
            } else {
                "unknown"
            };
            effects.push(json!({"source_path":path,"use":class,"owners":owners,"evidence_level":"PROVISIONAL","strategy":if local{"TRANSLATE_FIXUP"}else{"REPLACE"},"mission_critical":"UNKNOWN","native_replacement_candidates":tag["replacement_candidates"],"source_metadata":scan.metadata}));
        }
        if ["character", "style", "biped", "vehicle", "giant"].contains(&group) {
            ai.push(json!({"source_path":path,"group":group,"owners":owners,"references":tag["references"],"actor_metadata":scan.metadata,"proposed_policy":"H3 visual/skeleton/animation assets with reviewed Reach-native behavior where possible","replacement_candidates":tag["replacement_candidates"],"mission_specific_exception_review":local,"evidence_level":"PROVISIONAL","proven_target_status":"NOT_TESTED"}));
        }
    }
    (audio, effects, ai)
}
