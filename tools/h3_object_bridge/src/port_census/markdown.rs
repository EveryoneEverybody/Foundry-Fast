use serde_json::Value;
use std::fmt::Write;
fn esc(v: &str) -> String {
    v.replace('|', "\\|").replace('\n', " ").replace('\r', "")
}
pub fn render(r: &Value) -> String {
    let mut out = String::new();
    let s = &r["summary"];
    writeln!(out,"# {} portability census\n\nRead-only engineering census. All target loader/build/runtime states are **NOT TESTED**. Strategy and minimum-set proposals are **PROVISIONAL**.\n\n| Executive metric | Count |\n|---|---:|",esc(r["source"]["scenario"].as_str().unwrap_or("H3"))).unwrap();
    for (label, key) in [
        ("Unique H3 tags", "unique_h3_tags"),
        (
            "Direct scenario dependencies",
            "direct_scenario_dependencies",
        ),
        ("Transitive dependencies", "transitive_dependencies"),
        ("Missing references", "missing_references"),
        ("Tag groups", "tag_groups"),
        ("Dependency edges", "dependency_edges"),
    ] {
        writeln!(out, "| {label} | {} |", s[key]).unwrap();
    }
    for strategy in [
        "TRANSLATE",
        "TRANSLATE_FIXUP",
        "REBUILD",
        "REPLACE",
        "STUB",
        "DROP",
        "MANUAL",
    ] {
        writeln!(
            out,
            "| {strategy} | {} |",
            s["strategies"][strategy].as_u64().unwrap_or(0)
        )
        .unwrap();
    }
    for (label, key) in [
        ("HSC discovered source files", "source_files"),
        ("HSC analyzed source files", "analyzed_source_files"),
        ("Unique H3 engine functions used", "unique_engine_functions"),
        ("Unique H3 engine globals used", "unique_engine_globals"),
    ] {
        writeln!(out, "| {label} | {} |", s["scripts"][key]).unwrap();
    }
    for status in [
        "DIRECT",
        "SIGNATURE_CHANGE",
        "RENAMED",
        "EMULATABLE",
        "STUB_CANDIDATE",
        "UNSUPPORTED",
        "UNKNOWN",
    ] {
        writeln!(
            out,
            "| HSC {status} | {} |",
            s["scripts"]["function_classifications"][status]
                .as_u64()
                .unwrap_or(0)
        )
        .unwrap();
    }
    for status in [
        "BOOT_BLOCKER",
        "MISSION_BLOCKER",
        "COMBAT_BLOCKER",
        "FIDELITY_BLOCKER",
        "OPTIONAL",
        "UNKNOWN",
    ] {
        writeln!(
            out,
            "| {status} | {} |",
            s["blockers"][status].as_u64().unwrap_or(0)
        )
        .unwrap();
    }
    writeln!(out,"\n## Environment\n\n- H3 tags: `{}`\n- Reach tags: `{}`\n- Foundry commit: `{}`\n- Decoder: `{}`\n- Report schema: `{}` version {}\n\nThe JSON is the complete machine-readable report. Timing/cache metrics are in a separate timing JSON so repeated reports remain deterministic.\n",esc(r["source"]["h3_tags_root"].as_str().unwrap_or("")),esc(r["source"]["reach_tags_root"].as_str().unwrap_or("")),r["source"]["foundry_fast_revision"].as_str().unwrap_or("unknown"),r["source"]["decoder_revision"].as_str().unwrap_or(""),super::FORMAT,super::VERSION).unwrap();
    writeln!(out,"## Tag groups\n\n| Group | Unique | Direct | Transitive | Missing | Schema profile |\n|---|---:|---:|---:|---:|---|").unwrap();
    for g in r["tag_groups"].as_array().unwrap() {
        writeln!(
            out,
            "| {} | {} | {} | {} | {} | {} |",
            g["group"].as_str().unwrap(),
            g["total_unique_tags"],
            g["direct_scenario_dependencies"],
            g["transitive_dependencies"],
            g["missing_dependencies"],
            g["structural_compatibility"].as_str().unwrap_or("UNKNOWN")
        )
        .unwrap();
    }
    writeln!(out,"\nSchema comparisons describe potential field loss in definition profiles, not used-value loss, native layout acceptance or runtime compatibility. Complete interned field comparisons are in `schema_compatibility_profiles`.\n\n## Scenario\n\n| Authored category | Count | Reach correspondence |\n|---|---:|---|").unwrap();
    for c in r["scenarios"]["categories"].as_array().unwrap() {
        writeln!(
            out,
            "| {} | {} | {} |",
            c["category"].as_str().unwrap(),
            c["count"]
                .as_u64()
                .map(|n| n.to_string())
                .unwrap_or_else(|| "not observed".into()),
            c["reach_correspondence"].as_str().unwrap()
        )
        .unwrap();
    }
    for (heading, groups, note) in [
        (
            "Objects",
            vec![
                "scenery",
                "crate",
                "device_machine",
                "device_control",
                "biped",
                "vehicle",
                "giant",
            ],
            "Object metadata/placements exist; remap palettes, attachments, variants and gameplay references. Parent-relative placements remain unresolved.",
        ),
        (
            "Models",
            vec!["model", "render_model", "collision_model", "physics_model"],
            "Rebuild resource-bearing content through Foundry/Reach Tool. A source preview is not proof of export readiness.",
        ),
        (
            "Animations",
            vec!["model_animation_graph"],
            "Stored poses remain unsupported. Preserve source streams, event/network metadata and explicit fallback status; do not infer a quaternion codec.",
        ),
        (
            "Lighting",
            vec![
                "light",
                "scenario_lightmap",
                "scenario_lightmap_bsp_data",
                "scenario_structure_lighting_info",
            ],
            "Preserve authored lights/emissive/sky metadata and regenerate Reach-native lightmaps with Faux. H3 baked data is not the primary target solution.",
        ),
        (
            "Sky",
            vec!["sky"],
            "Use actual H3 sky geometry/materials; scenario skies may reference scenery/model groups, so consult scenario content as well as this group total.",
        ),
    ] {
        let count = r["tags"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|t| groups.contains(&t["source_group"].as_str().unwrap()))
            .count();
        writeln!(
            out,
            "\n## {heading}\n\n{count} tags in the listed groups. {note}"
        )
        .unwrap();
    }
    writeln!(out,"\n## Materials\n\n{} shader tags. Preview, eligibility for Reach node staging, and final Reach-tag-buildability are separate fields. Ordinary `.shader` snapshots are the current native-node entry point; terrain has specialized source previews. No nodes, bitmaps or shader tags were created. Full descriptions and runtime/unresolved parameters are in JSON.\n",r["materials"].as_array().unwrap().len()).unwrap();
    for (heading, key, note) in [
        (
            "Audio",
            "audio",
            "Categories use source paths and ownership evidence. Preserve mission-critical audio through a future Reach import pipeline; review generic Reach replacements. No FSB extraction or rebuild.",
        ),
        (
            "Effects",
            "effects",
            "Generic gameplay effects are replacement candidates; mission-specific effects require event review. No substitutions performed.",
        ),
        (
            "AI",
            "ai",
            "Actor dependencies and palette evidence support an MVP using H3 visuals with reviewed Reach-native character/style behavior.",
        ),
    ] {
        writeln!(
            out,
            "\n## {heading}\n\n{} records. {note}",
            r[key].as_array().unwrap().len()
        )
        .unwrap();
    }
    haloscript(&mut out, &r["scripts"]);
    writeln!(out, "\n## Unsupported systems and blockers\n").unwrap();
    for b in r["blockers"].as_array().unwrap() {
        writeln!(
            out,
            "- **{}** — {} ({})",
            b["severity"].as_str().unwrap(),
            b["message"].as_str().unwrap(),
            b["evidence_level"].as_str().unwrap_or("UNKNOWN")
        )
        .unwrap();
    }
    writeln!(out,"\n## Path conflicts\n\n{} collision records. Source assets map deterministically under `levels/h3/<mission>/` or `h3_port/`. Existing Reach paths are only replacement candidates; stock provenance and semantic equivalence are unverified. No destination tags are created.\n\n## Minimum boot set\n\n{} proposed source assets for the first authored BSP candidate, plus explicit Reach player/spawn/lighting requirements. Other BSP candidates are retained. This is an environment-filtered dependency closure, not a validated loader minimum.\n\n## Minimum combat set\n\n{} candidate authored squad-group clusters. The selected encounter, when present, retains its authored activation script, squads, static script dependencies and additional assets. All other candidates retain actor palette joins. Selection does not prove runtime reachability.\n\n## Recommended implementation order\n\n1. Resolve incomplete source/reference/schema evidence and select a boot BSP and spawn.\n2. Rebuild environment/collision/pathfinding, sky, materials and Reach lighting.\n3. Generate and independently validate a minimal Reach scenario.\n4. Select an authored combat cluster and review Reach-native behavior replacements.\n5. Plan the HSC call-site changes needed for progression.\n6. Rebuild mission-critical audio/effects and improve fidelity.\n\nThis checkpoint stops at the census; none of these future port steps is performed.\n\n## Limitations\n",r["path_collisions"].as_array().unwrap().len(),r["minimum_boot_set"]["source_assets"].as_array().unwrap().len(),r["minimum_combat_set"]["candidate_encounter_clusters"].as_array().unwrap().len()).unwrap();
    if let Some(name) = r["minimum_combat_set"]["selected_encounter"]["name"].as_str() {
        writeln!(
            out,
            "\nSelected combat candidate: **{}**, rooted at `{}`; {} additional source assets.\n",
            esc(name),
            esc(r["minimum_combat_set"]["selected_encounter"]["root_script"]
                .as_str()
                .unwrap_or("")),
            r["minimum_combat_set"]["selected_encounter"]["additional_source_assets"]
                .as_array()
                .unwrap()
                .len()
        )
        .unwrap();
    }
    for note in r["limitations"].as_array().unwrap() {
        writeln!(out, "- {}", note.as_str().unwrap()).unwrap();
    }
    out
}

fn haloscript(out: &mut String, scripts: &Value) {
    let s = &scripts["summary"];
    writeln!(out,"\n## HaloScript Portability\n\n{} unique H3 engine functions; {} engine call sites. {} unresolved source call sites are separate from the engine inventory. Each unique function contributes to one conservative summary bucket. DIRECT is signature compatibility, not proof of identical runtime semantics.\n\n| Compatibility | Raw unique | Reviewed unique | Reviewed call sites |\n|---|---:|---:|---:|",s["unique_engine_functions"],s["engine_call_sites"],s["unresolved_call_sites"]).unwrap();
    for class in super::hsc_compat::CLASSES {
        writeln!(
            out,
            "| {class} | {} | {} | {} |",
            s["raw_function_classifications"][class],
            s["function_classifications"][class],
            s["call_site_classifications"][class]
        )
        .unwrap();
    }
    writeln!(out,"\n- Script mission-blocker call sites: {}\n- Script fidelity-review call sites: {}\n- Script optional-review call sites: {}\n- Scenario symbol references: {}\n- Unresolved typed scenario symbols: {}\n- Parser/declaration diagnostics: {}\n\nCounts of review requirements include unimplemented signature/wrapper proposals. Source locations, exact expressions, overload candidates, transformations, API confidence and independent context evidence remain in JSON. `transpiler_mappings` is analysis metadata; no HSC is emitted.\n\n### Remaining genuinely unsupported unique functions\n\nUnsupported means no reviewed Reach replacement in this catalogue; it does not prove emulation is impossible.\n\n| Function | Unsupported calls | Context roles | Blocker severities |\n|---|---:|---|---|",s["script_blocker_call_sites"]["MISSION_BLOCKER"].as_u64().unwrap_or(0),s["script_blocker_call_sites"]["FIDELITY_BLOCKER"].as_u64().unwrap_or(0),s["script_blocker_call_sites"]["OPTIONAL"].as_u64().unwrap_or(0),scripts["scenario_symbol_uses"].as_array().unwrap().len(),scripts["unresolved_symbols"].as_array().unwrap().len(),scripts["diagnostics"].as_array().unwrap().len()).unwrap();
    for function in scripts["engine_functions"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|f| {
            f["classifications"]
                .as_array()
                .unwrap()
                .iter()
                .any(|v| v == "UNSUPPORTED")
        })
    {
        let calls: Vec<_> = scripts["call_sites"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|c| c["name"] == function["name"] && c["classification"] == "UNSUPPORTED")
            .collect();
        let roles: std::collections::BTreeSet<_> = calls
            .iter()
            .filter_map(|c| c["call_site_role"].as_str())
            .collect();
        let severities: std::collections::BTreeSet<_> = calls
            .iter()
            .filter_map(|c| c["blocker_severity"].as_str())
            .collect();
        writeln!(
            out,
            "| {} | {} | {} | {} |",
            esc(function["name"].as_str().unwrap()),
            calls.len(),
            roles.into_iter().collect::<Vec<_>>().join(", "),
            severities.into_iter().collect::<Vec<_>>().join(", ")
        )
        .unwrap();
    }
    writeln!(out,"\n### Remaining script mission blockers\n\n| Source | Enclosing script | Function | Compatibility |\n|---|---|---|---|").unwrap();
    for call in scripts["call_sites"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["requires_review"] == true && c["blocker_severity"] == "MISSION_BLOCKER")
    {
        writeln!(
            out,
            "| {}:{}:{} | {} | {} | {} |",
            esc(call["location"]["file"].as_str().unwrap()),
            call["location"]["line"],
            call["location"]["column"],
            esc(call["enclosing_script"].as_str().unwrap()),
            esc(call["name"].as_str().unwrap()),
            esc(call["classification"].as_str().unwrap())
        )
        .unwrap();
    }
    writeln!(out,"\n### Other reviewed mappings and uncertainties\n\n| Function | Reviewed category | Calls |\n|---|---|---:|").unwrap();
    for f in scripts["engine_functions"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|f| f["classification"] != "DIRECT" && f["classification"] != "UNSUPPORTED")
    {
        writeln!(
            out,
            "| {} | {} | {} |",
            esc(f["name"].as_str().unwrap()),
            esc(f["classification"].as_str().unwrap()),
            f["call_count"]
        )
        .unwrap();
    }
}
