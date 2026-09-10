//! Membership in observed planning closures is not runtime reachability proof.
use super::{
    graph::{Graph, extension},
    hsc_context,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

pub fn select_factory_a(combat: &mut Value, scripts: &Value, source: &str) {
    if source != "levels/solo/040_voi/040_voi.scenario" {
        return;
    }
    let declared = scripts["declarations"].as_array().unwrap();
    if !declared.iter().any(|d| d["name"] == "factory_a_start") {
        return;
    }
    let Some(candidate) = combat["candidate_encounter_clusters"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["parent_group_name"] == "tank_room_a_covies")
        .cloned()
    else {
        return;
    };
    let squads: BTreeSet<_> = candidate["squads"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|s| s["name"].as_str())
        .collect();
    let required = [
        "factory_a_init_grunts01",
        "factory_a_init_grunts02",
        "factory_a_jackals01",
        "factory_a_jackals02",
        "tank_room_a_rein_front",
        "tank_room_a_commander",
        "tank_room_a_commander02",
        "tank_room_a_com_jacks",
    ];
    if !required.iter().all(|s| squads.contains(s)) {
        return;
    }
    let mut reachable = BTreeSet::new();
    let mut queue = VecDeque::from(["factory_a_start".to_owned()]);
    while let Some(name) = queue.pop_front() {
        if !reachable.insert(name.clone()) {
            continue;
        }
        for edge in scripts["user_script_calls"].as_array().unwrap() {
            if edge["enclosing_script"] == name
                && edge["resolution"] != "AMBIGUOUS_USER_ENGINE_COLLISION"
            {
                if let Some(target) = edge["name"].as_str() {
                    queue.push_back(target.into());
                }
            }
        }
    }
    let symbol_uses: Vec<_> = scripts["scenario_symbol_uses"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|r| r["symbol"].as_str().is_some_and(|n| squads.contains(n)))
        .collect();
    let calls:Vec<_>=scripts["call_sites"].as_array().unwrap().iter().filter(|c|c["enclosing_script"].as_str().is_some_and(|s|reachable.contains(s))).map(|c|json!({"name":c["name"],"location":c["location"],"enclosing_script":c["enclosing_script"],"classification":c["classification"],"signature_match":c["signature_match"],"proposed_reach_counterpart":c["proposed_reach_counterpart"],"call_site_role":c["call_site_role"],"blocker_severity":c["blocker_severity"],"requires_review":c["requires_review"]})).collect();
    combat["selected_encounter"] = json!({"name":"Factory A / tank room","parent_group_name":"tank_room_a_covies","root_script":"factory_a_start","additional_source_assets":candidate["additional_source_assets"],"source_asset_seeds":candidate["source_asset_seeds"],"squads":candidate["squads"],"script_dependencies":reachable,"script_call_sites":calls,"squad_script_uses":symbol_uses,"selection_confidence":"HIGH","evidence":["User-selected first combat candidate; authored Factory A activation flow","Actual squad-group membership, palettes and factory_a_start declaration"],"limitations":["No encounter implemented or runtime tested","Script edges are conservative static calls/wakes/command-script/cleanup references, not execution proof","Other clusters are retained; asset count is not the selection criterion"]});
    combat["derivation"] = json!(
        "Preserved reviewed Factory A candidate, validated against authored script and squad membership; target combat is NOT_TESTED"
    );
}
fn set(value: &Value) -> BTreeSet<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|v| v.as_str().map(str::to_owned))
        .collect()
}
pub fn missing(graph: &Graph, boot: &Value, combat: &Value, source: &str) -> Vec<Value> {
    let boot = set(&boot["source_assets"]);
    let combat = set(&combat["selected_encounter"]["additional_source_assets"]);
    // Find paths that do not cross a cinematic container. A missing dependency
    // reached by even one ordinary path can never be labeled cinematic-only.
    let mut ordinary = BTreeSet::new();
    let mut queue = VecDeque::from([source.to_owned()]);
    while let Some(path) = queue.pop_front() {
        if !ordinary.insert(path.clone()) {
            continue;
        }
        if matches!(
            extension(&path),
            "cinematic" | "cinematic_scene" | "cinematic_scene_data"
        ) {
            continue;
        }
        if let Some(row) = graph.tags.get(&path) {
            for next in row["references"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
            {
                queue.push_back(next.into());
            }
        }
    }
    graph.tags.iter().filter(|(_,r)|r["exists"]==false).map(|(path,row)| {
        let relevance=if boot.contains(path){"REQUIRED_BY_BOOT_SET"}else if combat.contains(path){"REQUIRED_BY_SELECTED_COMBAT_SET"}else if !ordinary.contains(path){"CINEMATIC_ONLY"}else if matches!(extension(path),"bitmap"|"shader"|"shader_terrain"|"render_method_template"|"pixel_shader"|"vertex_shader"){"FIDELITY_ONLY"}else{"UNKNOWN"};
        let severity=if relevance=="REQUIRED_BY_BOOT_SET" && matches!(extension(path),"scenario"|"scenario_structure_bsp"|"structure_design"|"collision_model"){"BOOT_BLOCKER"}else if matches!(extension(path),"bitmap"|"shader"|"shader_terrain"|"render_method_template"|"pixel_shader"|"vertex_shader")||relevance=="CINEMATIC_ONLY"{"FIDELITY_BLOCKER"}else if relevance=="REQUIRED_BY_SELECTED_COMBAT_SET"{"COMBAT_BLOCKER"}else{"UNKNOWN"};
        json!({"source_path":path,"dependency_relevance":relevance,"blocker_severity":severity,"evidence":[{"kind":"SCHEMA_MATCH","source":"observed dependency graph and provisional planning-set membership","referenced_by":row["referenced_by"],"first_reached_by":row["first_reached_by"]}],"confidence":"PROVISIONAL","runtime_required":"UNKNOWN","notes":"REQUIRED_BY_* means membership in the selected planning closure, not proven loader necessity. Cinematic-only means all observed paths cross a cinematic container. Visual-resource loss is separated from load-critical geometry; optional/unreached and mission-progression membership are not fabricated."})
    }).collect()
}
pub fn script_blockers(scripts: &Value) -> Vec<Value> {
    let mut groups: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for row in scripts["call_sites"]
        .as_array()
        .into_iter()
        .flatten()
        .chain(
            scripts["unresolved_call_sites"]
                .as_array()
                .into_iter()
                .flatten(),
        )
        .filter(|r| r["requires_review"] == true)
    {
        let severity = row["blocker_severity"].as_str().unwrap_or("UNKNOWN");
        groups.entry(severity.into()).or_default().push(json!({"name":row["name"],"source_function":row["name"],"location":row["location"],"enclosing_script":row["enclosing_script"],"original_source_expression":row["original_source_expression"],"classification":row["classification"],"proposed_reach_counterpart":row["proposed_reach_counterpart"],"call_site_role":row["call_site_role"],"blocker_severity":severity,"evidence":row["evidence"],"confidence":row["confidence"],"notes":row["reason"],"impact_evidence":row["impact_evidence"],"impact_confidence":row["impact_confidence"],"impact_notes":row["impact_notes"]}));
    }
    groups.into_iter().map(|(severity,calls)|json!({"id":format!("script_{}",severity.to_lowercase()),"severity":severity,"message":"Call-site review requirements; API compatibility and contextual impact are independent","call_sites":calls,"evidence_level":"PROVISIONAL","context_review_format":hsc_context::bundled()["format"]})).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_visual_and_combat_references_do_not_inherit_a_boot_blocker() {
        let names = [
            (
                "root.scenario",
                true,
                vec![
                    "missing.scenario_structure_bsp",
                    "missing.bitmap",
                    "missing.biped",
                    "scene.cinematic",
                    "unknown.sound",
                ],
            ),
            ("missing.scenario_structure_bsp", false, vec![]),
            ("missing.bitmap", false, vec![]),
            ("missing.biped", false, vec![]),
            ("scene.cinematic", true, vec!["cine_missing.sound"]),
            ("cine_missing.sound", false, vec![]),
            ("unknown.sound", false, vec![]),
        ];
        let tags=names.into_iter().map(|(path,exists,refs)|(path.into(),json!({"exists":exists,"references":refs,"referenced_by":[],"first_reached_by":["root.scenario",path]}))).collect();
        let graph = Graph {
            tags,
            scans: BTreeMap::new(),
            edges: vec![],
            cache_hits: 0,
        };
        let boot = json!({"source_assets":["root.scenario","missing.scenario_structure_bsp","missing.bitmap"]});
        let combat = json!({"selected_encounter":{"additional_source_assets":["missing.biped"]}});
        let rows = missing(&graph, &boot, &combat, "root.scenario");
        let lookup: BTreeMap<_, _> = rows
            .iter()
            .map(|r| (r["source_path"].as_str().unwrap(), r))
            .collect();
        assert_eq!(
            lookup["missing.scenario_structure_bsp"]["blocker_severity"],
            "BOOT_BLOCKER"
        );
        assert_eq!(
            lookup["missing.bitmap"]["dependency_relevance"],
            "REQUIRED_BY_BOOT_SET"
        );
        assert_eq!(
            lookup["missing.bitmap"]["blocker_severity"],
            "FIDELITY_BLOCKER"
        );
        assert_eq!(
            lookup["missing.biped"]["blocker_severity"],
            "COMBAT_BLOCKER"
        );
        assert_eq!(
            lookup["cine_missing.sound"]["dependency_relevance"],
            "CINEMATIC_ONLY"
        );
        assert_eq!(lookup["unknown.sound"]["dependency_relevance"], "UNKNOWN");
        assert!(rows.iter().all(|r| r["runtime_required"] == "UNKNOWN"));
    }
    #[test]
    fn ordinary_reference_prevents_cinematic_only_claim() {
        let graph = Graph {
            tags: BTreeMap::from([
                (
                    "root.scenario".into(),
                    json!({"exists":true,"references":["a.cinematic","shared.sound"]}),
                ),
                (
                    "a.cinematic".into(),
                    json!({"exists":true,"references":["shared.sound"]}),
                ),
                (
                    "shared.sound".into(),
                    json!({"exists":false,"references":[]}),
                ),
            ]),
            scans: BTreeMap::new(),
            edges: vec![],
            cache_hits: 0,
        };
        assert_eq!(
            missing(&graph, &json!({}), &json!({}), "root.scenario")[0]["dependency_relevance"],
            "UNKNOWN"
        );
    }
    #[test]
    fn factory_a_selection_uses_authored_identity_not_smallest_cluster() {
        let squads = [
            "factory_a_init_grunts01",
            "factory_a_init_grunts02",
            "factory_a_jackals01",
            "factory_a_jackals02",
            "tank_room_a_rein_front",
            "tank_room_a_commander",
            "tank_room_a_commander02",
            "tank_room_a_com_jacks",
        ];
        let mut combat = json!({"candidate_encounter_clusters":[{"parent_group_name":"smaller","additional_source_assets":[]},{"parent_group_name":"tank_room_a_covies","squads":squads.iter().map(|n|json!({"name":n})).collect::<Vec<_>>(),"additional_source_assets":["a.character","b.weapon"]}]});
        let scripts = json!({"declarations":[{"name":"factory_a_start"}],"user_script_calls":[{"enclosing_script":"factory_a_start","name":"button_pusher01","resolution":"USER_DECLARATION"}],"scenario_symbol_uses":[],"call_sites":[{"enclosing_script":"button_pusher01","name":"vs_release_all","classification":"UNSUPPORTED","blocker_severity":"MISSION_BLOCKER"}]});
        select_factory_a(
            &mut combat,
            &scripts,
            "levels/solo/040_voi/040_voi.scenario",
        );
        assert_eq!(
            combat["selected_encounter"]["parent_group_name"],
            "tank_room_a_covies"
        );
        assert_eq!(
            combat["selected_encounter"]["script_dependencies"],
            json!(["button_pusher01", "factory_a_start"])
        );
        assert_eq!(
            combat["selected_encounter"]["script_call_sites"][0]["name"],
            "vs_release_all"
        );
        assert_eq!(
            combat["candidate_encounter_clusters"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
    }
}
