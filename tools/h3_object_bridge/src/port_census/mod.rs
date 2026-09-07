//! Headless, read-only H3 -> Reach portability census. No tag writer API is used.
mod assets;
mod compat;
mod graph;
mod hsc;
#[cfg(test)]
#[path = "tests.rs"]
mod integration_tests;
mod markdown;
mod policy;
mod scenario;
use anyhow::{Context, Result, bail};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Component, Path, PathBuf};
use std::time::Instant;

pub const FORMAT: &str = "foundry.h3-reach-portability-census";
pub const VERSION: u32 = 1;
const CACHE_VERSION: &str = "port-census-scan-3";
pub fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
pub fn display(path: &Path) -> String {
    path.to_string_lossy()
        .trim_start_matches("\\\\?\\")
        .replace('\\', "/")
}
pub fn write_json_new(path: &Path, value: &Value) -> Result<()> {
    let mut file = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    serde_json::to_writer(&mut file, value)?;
    file.write_all(b"\n")?;
    file.flush()?;
    Ok(())
}
fn write_new(path: &Path, text: &str) -> Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(text.as_bytes())?;
    Ok(())
}

fn resolved_future(path: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_owned()
    } else {
        std::env::current_dir()?.join(path)
    };
    if absolute
        .components()
        .any(|c| matches!(c, Component::ParentDir))
    {
        bail!("Output paths must not contain '..'");
    }
    let mut ancestor = absolute.as_path();
    let mut tail = Vec::new();
    while !ancestor.exists() {
        tail.push(
            ancestor
                .file_name()
                .context("No existing path ancestor")?
                .to_owned(),
        );
        ancestor = ancestor.parent().context("No existing path ancestor")?;
    }
    let mut result = ancestor.canonicalize()?;
    for part in tail.into_iter().rev() {
        result.push(part);
    }
    Ok(result)
}
fn overlap(a: &Path, b: &Path) -> bool {
    let a = display(a).trim_end_matches('/').to_lowercase();
    let b = display(b).trim_end_matches('/').to_lowercase();
    a == b || a.starts_with(&format!("{b}/")) || b.starts_with(&format!("{a}/"))
}
fn output_guard(output: &Path, protected: &[PathBuf]) -> Result<PathBuf> {
    let resolved = resolved_future(output)?;
    for source in protected {
        if overlap(&resolved, source) {
            bail!("Output overlaps protected input/kit: {}", display(source));
        }
    }
    // Resolve existing ancestors before creating anything, preventing a junction
    // into either kit from bypassing lexical path checks.
    Ok(resolved)
}
fn revision(path: &Path) -> Option<String> {
    let out = std::process::Command::new("git")
        .arg("-c")
        .arg(format!("safe.directory={}", display(path)))
        .arg("-C")
        .arg(path)
        .args(["rev-parse", "HEAD"])
        .output()
        .ok()?;
    out.status
        .success()
        .then(|| String::from_utf8_lossy(&out.stdout).trim().to_owned())
}
fn definitions_digest(root: Option<&Path>) -> Result<Value> {
    let Some(root) = root else {
        return Ok(Value::Null);
    };
    let mut files = BTreeMap::new();
    for profile in ["halo3_mcc", "haloreach_mcc"] {
        let dir = root.join(profile);
        if !dir.is_dir() {
            continue;
        }
        for entry in fs::read_dir(&dir)? {
            let p = entry?.path();
            if p.extension().is_some_and(|e| e == "json") {
                files.insert(
                    format!("{profile}/{}", p.file_name().unwrap().to_string_lossy()),
                    digest(&fs::read(p)?),
                );
            }
        }
    }
    Ok(
        json!({"revision":revision(root),"content_sha256":digest(serde_json::to_string(&files)?.as_bytes()),"files":files}),
    )
}

fn options(args: Vec<String>) -> Result<(BTreeMap<String, String>, bool)> {
    let mut options = BTreeMap::new();
    let mut all = false;
    let mut args = args.into_iter();
    while let Some(key) = args.next() {
        if key == "--all-fields" {
            if all {
                bail!("Repeated --all-fields");
            }
            all = true;
            continue;
        }
        if !key.starts_with('-') && !options.contains_key("--input") {
            options.insert("--input".into(), key);
            continue;
        }
        if ![
            "--input",
            "--h3-tags",
            "--reach-tags",
            "--h3-data",
            "--scripts",
            "--definitions",
            "--output",
            "--cache",
            "--hsc-catalogue",
            "--baboon-reference",
            "--troop-reference",
        ]
        .contains(&key.as_str())
        {
            bail!("Unknown port-census option: {key}");
        }
        let value = args
            .next()
            .with_context(|| format!("Missing value for {key}"))?;
        if value.starts_with("--") {
            bail!("Missing value for {key}");
        }
        if options.insert(key.clone(), value).is_some() {
            bail!("Repeated {key}");
        }
    }
    Ok((options, all))
}

pub fn run(args: Vec<String>) -> Result<()> {
    if args.iter().any(|s| s == "--help" || s == "-h") {
        println!(
            "h3-scenario-inspect port-census <scenario> --h3-tags <tags> --reach-tags <tags> --output <outside-kits-directory> [--h3-data <data>] [--scripts <directory>] [--definitions <profiles-root>] [--cache <outside-kits-directory>] [--hsc-catalogue <json>] [--all-fields] [--baboon-reference <repo>] [--troop-reference <repo>]\nReports: <mission>_portability_report.json/.md; deterministic schema {VERSION}; variable phase timings in a separate file. All game content is read-only. Existing reports are never overwritten."
        );
        return Ok(());
    }
    let (options, all_fields) = options(args)?;
    let required = |key: &str| -> Result<PathBuf> {
        Ok(PathBuf::from(
            options
                .get(key)
                .with_context(|| format!("Required: {key}"))?,
        ))
    };
    let h3 = required("--h3-tags")?.canonicalize()?;
    let reach = required("--reach-tags")?.canonicalize()?;
    if !h3.is_dir() || !reach.is_dir() || overlap(&h3, &reach) {
        bail!("H3 and Reach tag roots must be separate existing directories");
    }
    let input_arg = required("--input")?;
    let input = if input_arg.is_absolute() {
        input_arg.canonicalize()?
    } else {
        h3.join(input_arg).canonicalize()?
    };
    if !input.starts_with(&h3) || !input.is_file() {
        bail!("Scenario must be a real file inside --h3-tags");
    }
    let source_path = graph::normalized(&input.strip_prefix(&h3)?.to_string_lossy())?;
    if graph::extension(&source_path) != "scenario" {
        bail!("Expected a .scenario source tag");
    }
    let (header, _) = blam_tags::TagFileHeader::peek(&input)?;
    if header.group_tag != u32::from_be_bytes(*b"scnr") {
        bail!("Source header is not a scenario");
    }
    let mission = input
        .file_stem()
        .context("Scenario stem")?
        .to_string_lossy()
        .to_lowercase();
    let mission_dir = source_path.rsplit_once('/').map(|p| p.0).unwrap_or("");
    let optional = |key: &str| -> Result<Option<PathBuf>> {
        options
            .get(key)
            .map(|p| PathBuf::from(p).canonicalize().map_err(Into::into))
            .transpose()
    };
    let data = optional("--h3-data")?;
    let explicit_scripts = optional("--scripts")?;
    let definitions = optional("--definitions")?;
    let catalogue_path = optional("--hsc-catalogue")?;
    let baboon = optional("--baboon-reference")?;
    let troop = optional("--troop-reference")?;
    let mut protected = vec![h3.clone(), reach.clone()];
    // With normal tags roots, protect the entire kit, including data, prefs,
    // project.xml and Omaha settings. Custom roots remain protected themselves.
    for root in [&h3, &reach] {
        if root
            .file_name()
            .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("tags"))
        {
            protected.push(root.parent().context("Kit parent")?.to_owned());
        }
    }
    for root in [&data, &explicit_scripts, &definitions, &baboon, &troop] {
        if let Some(root) = root {
            protected.push(root.clone());
        }
    }
    let output = output_guard(&required("--output")?, &protected)?;
    let cache = output_guard(
        &options
            .get("--cache")
            .map(PathBuf::from)
            .unwrap_or_else(|| output.join("cache")),
        &protected,
    )?;
    for suffix in [
        "portability_report.json",
        "portability_report.md",
        "dependency_graph.json",
        "timings.json",
    ] {
        if output.join(format!("{mission}_{suffix}")).exists() {
            bail!(
                "Report already exists; choose a new output directory: {}",
                display(&output)
            );
        }
    }
    fs::create_dir_all(&output)?;
    fs::create_dir_all(&cache)?;
    let mut timings = BTreeMap::new();
    let started = Instant::now();
    let mut diagnostics = Vec::new();
    println!("Port census: indexing source and Reach paths (read-only)");
    let h3_index = graph::index(&h3, &mut diagnostics)?;
    let reach_index = graph::index(&reach, &mut diagnostics)?;
    let def_identity = definitions_digest(definitions.as_deref())?;
    timings.insert("source_discovery_seconds", started.elapsed().as_secs_f64());
    let started = Instant::now();
    let scope = format!(
        "{CACHE_VERSION}\n{}\n{}\n{}",
        display(&h3),
        crate::DECODER,
        def_identity
    );
    println!("Port census: source dependency graph");
    let mut graph = graph::build(&h3, &source_path, &h3_index, &cache, &scope, all_fields)?;
    timings.insert("dependency_graph_seconds", started.elapsed().as_secs_f64());
    let started = Instant::now();
    let groups: Vec<_> = graph
        .tags
        .keys()
        .map(|p| graph::extension(p).to_owned())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    println!("Port census: {} group profiles", groups.len());
    let compatibility = compat::catalogue(definitions.as_deref(), &groups);
    let actual_compatibility = compat::actual_catalogue(definitions.as_deref(), &graph, &h3_index);
    timings.insert(
        "compatibility_analysis_seconds",
        started.elapsed().as_secs_f64(),
    );
    let started = Instant::now();
    let mut scripts = hsc::Sources::default();
    let mut script_roots = Vec::new();
    if let Some(root) = &explicit_scripts {
        script_roots.push((root.clone(), "explicit_mission_source"));
    } else if let Some(root) = &data {
        let folder = root.join(mission_dir);
        if folder.is_dir() {
            script_roots.push((folder, "mission_directory_source"));
        }
    }
    if let Some(root) = &data {
        if root.join("globals").is_dir() {
            script_roots.push((root.join("globals"), "shared_global_source"));
        }
    }
    let selected_sources: BTreeSet<String> =
        scenario::entities(&graph.scans[&source_path], "source files")
            .iter()
            .filter_map(|e| e["name"].as_str().map(|s| s.to_lowercase()))
            .collect();
    let mut seen = BTreeSet::new();
    for (root, scope) in &script_roots {
        for (_, file) in graph::index(root, &mut diagnostics)? {
            if !file
                .extension()
                .is_some_and(|e| e.to_string_lossy().eq_ignore_ascii_case("hsc"))
                || !seen.insert(file.clone())
            {
                continue;
            }
            let name = if let Some(data) = &data {
                file.strip_prefix(data)
                    .map(display)
                    .unwrap_or_else(|_| display(&file))
            } else {
                display(&file)
            };
            let scope = if explicit_scripts.is_none()
                && !selected_sources.is_empty()
                && !selected_sources
                    .contains(&file.file_stem().unwrap().to_string_lossy().to_lowercase())
            {
                "discovered_not_in_scenario_source_table"
            } else {
                scope
            };
            match fs::read(&file) {
                Ok(bytes) => {
                    let text = if bytes.starts_with(&[0xff, 0xfe]) {
                        let units: Vec<_> = bytes[2..]
                            .chunks_exact(2)
                            .map(|b| u16::from_le_bytes([b[0], b[1]]))
                            .collect();
                        String::from_utf16_lossy(&units)
                    } else {
                        String::from_utf8_lossy(&bytes).into_owned()
                    };
                    scripts.add(&name, &text, scope);
                }
                Err(e) => diagnostics
                    .push(json!({"code":"script_read_failed","path":name,"error":e.to_string()})),
            }
        }
    }
    if scripts.files.is_empty() {
        diagnostics.push(json!({"code":"hsc_sources_unavailable","message":"Supply --h3-data or --scripts; compiled scenario bytecode is not decompiled"}));
    }
    let catalogue = if let Some(path) = &catalogue_path {
        let value: hsc::Catalogue = serde_json::from_slice(&fs::read(path)?)?;
        if value.format != "foundry.hsc-signatures" || value.version != 1 {
            bail!("Unsupported HSC catalogue schema");
        }
        value
    } else {
        hsc::Catalogue::bundled()
    };
    timings.insert("script_parse_seconds", started.elapsed().as_secs_f64());
    let started = Instant::now();
    let source_symbols = scenario::symbols(&graph.scans[&source_path]);
    let mut script_report = scripts.analyze(&catalogue, &source_symbols);
    script_report["scenario_source_table"] = json!(scenario::entities(&graph.scans[&source_path], "source files").iter().map(|e| {
        let name=e["name"].as_str().unwrap_or("");
        let found=scripts.files.iter().any(|f|Path::new(f["path"].as_str().unwrap_or("")).file_stem().is_some_and(|s|s.to_string_lossy().eq_ignore_ascii_case(name)));
        let generated=scenario::field(e,"flags").and_then(|v|v["value"].as_u64()).is_some_and(|v|v&1!=0);
        json!({"name":name,"address":e["address"],"source_found":found,"generated_flag":generated,"status":if found{"PHYSICAL_SOURCE_FOUND"}else if generated{"GENERATED_SOURCE_NOT_PARSED"}else{"SOURCE_NOT_FOUND"}})
    }).collect::<Vec<_>>());
    for entry in script_report["scenario_source_table"].as_array().unwrap() {
        if entry["source_found"] == false {
            diagnostics.push(json!({"code":"scenario_script_source_unavailable","source":entry,"note":"Engine-generated or missing physical source is not reconstructed from compiled bytecode"}));
        }
    }
    let mut collisions = Vec::new();
    let mut path_map = Vec::new();
    let mut destinations: BTreeMap<String, String> = BTreeMap::new();
    let mut group_rows: BTreeMap<String, Value> = BTreeMap::new();
    let mut strategies: BTreeMap<String, u64> = BTreeMap::new();
    let mut reach_stems: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for p in reach_index.keys() {
        if let Some((stem, _)) = p.rsplit_once('.') {
            reach_stems.entry(stem.into()).or_default().push(p.clone());
        }
    }
    for (path, row) in &mut graph.tags {
        let group = graph::extension(path);
        let local = path.starts_with(&format!("{mission_dir}/"));
        let (mut strategy, status, mut note) = policy::strategy(group, local);
        if strategy == "MANUAL" && row["exists"] == true {
            if let Some(actual) = row["actual_source_schema"]["fingerprint"]
                .as_str()
                .and_then(|h| actual_compatibility.get(h))
            {
                if actual["status"] == "IDENTICAL"
                    && actual["field_counts"]["opaque_engine_bound_fields"]
                        .as_u64()
                        .unwrap_or(0)
                        == 0
                {
                    strategy = "TRANSLATE";
                    note = "Observed ordinary serialized fields match the Reach profile with no detected opaque slots; generic translation is a provisional proposal requiring semantic and target validation";
                }
            }
        }
        let same_path = reach_index.contains_key(path);
        let proposed = graph::destination(path, mission_dir, &mission);
        let same_stem = path
            .rsplit_once('.')
            .and_then(|(s, _)| reach_stems.get(s))
            .cloned()
            .unwrap_or_default();
        let candidates:Vec<_>=same_stem.iter().map(|p|{
            let header=reach_index.get(p).and_then(|file|blam_tags::TagFileHeader::peek(file).ok()).map(|(h,_)|json!({"group_tag":h.group_tag,"group_version":h.group_version,"build_version":h.build_version,"build_number":h.build_number}));
            json!({"path":p,"evidence":if p==path{"exact_same_path_existing_reach_file"}else{"same_path_stem_different_group"},"header":header,"native_layout_accepted":"NOT_TESTED","semantic_equivalence":"UNVERIFIED","stock_provenance":"UNVERIFIED kit may contain custom assets","group_matches":graph::extension(p)==group})
        }).collect();
        let existing_destination = reach_index.contains_key(&proposed);
        if same_path || existing_destination || !same_stem.is_empty() {
            collisions.push(json!({"source_path":path,"exact_same_path":same_path,"same_logical_stem_candidates":same_stem,"proposed_destination":proposed,"destination_exists":existing_destination,"overwrite_performed":false}));
        }
        if let Some(previous) = destinations.insert(proposed.clone(), path.clone()) {
            bail!("Proposed destination collision: {previous}, {path} -> {proposed}");
        }
        let mapping = json!({"source":path,"proposed_destination":proposed,"strategy":strategy,"replacement_candidates":candidates,"selected_stock_replacement":null,"status":"PROVISIONAL","note":"Candidate replacements stay at their existing Reach paths if reviewed/selected; the namespaced path is reserved for a future rebuilt H3 asset"});
        path_map.push(mapping);
        row["local_shared"] = json!(if local { "mission_local" } else { "shared" });
        row["mission_relevance"] = json!(if row["direct_dependency"] == true {
            "direct_source_reference"
        } else {
            "transitive_or_declared_build_dependency"
        });
        row["proposed_strategy"] = json!(strategy);
        row["confidence"] = json!("provisional");
        row["policy_evidence_level"] = json!("PROVISIONAL");
        row["foundry_rebuild_status"] = json!(status);
        row["notes"] = json!([note]);
        row["structural_compatibility"] = json!({"profile":group,"status":compatibility[group]["status"],"scope":"definition_profile_only","actual_serialized_layout_compared":false});
        row["conversion_losses"] = compatibility[group]["field_counts"].clone();
        row["reach_group_available"] = compatibility[group]["reach_group_available"].clone();
        if let Some(hash) = row["actual_source_schema"]["fingerprint"]
            .as_str()
            .map(str::to_owned)
        {
            if let Some(actual) = actual_compatibility.get(&hash) {
                row["structural_compatibility"] = json!({"profile":group,"serialized_layout_comparison":hash,"status":actual["status"],"scope":"actual_serialized_layout_to_reach_definition","actual_serialized_layout_compared":actual["struct_pairs"].is_array()});
                row["conversion_losses"] = actual["field_counts"].clone();
            }
        }
        row["proven_target_status"] = json!({"official_loader":"NOT_TESTED","live_runtime":"NOT_TESTED","reach_tool_build":"NOT_TESTED"});
        row["proposed_destination"] = json!(proposed);
        row["destination_collision"] = json!(existing_destination);
        row["reach_same_path_collision"] = json!(same_path);
        row["replacement_candidates"] = json!(candidates);
        *strategies.entry(strategy.into()).or_default() += 1;
        let census=group_rows.entry(group.into()).or_insert_with(||json!({"group":group,"total_unique_tags":0,"direct_scenario_dependencies":0,"transitive_dependencies":0,"missing_dependencies":0,"strategies":{},"structural_compatibility":compatibility[group]["status"],"notes":"Structural profile evidence and planning policy are separate; target runtime untested"}));
        for key in [
            "total_unique_tags",
            if row["direct_dependency"] == true {
                "direct_scenario_dependencies"
            } else if path != &source_path {
                "transitive_dependencies"
            } else {
                "scenario_roots"
            },
        ] {
            census[key] = json!(census[key].as_u64().unwrap_or(0) + 1);
        }
        if row["exists"] == false {
            census["missing_dependencies"] =
                json!(census["missing_dependencies"].as_u64().unwrap_or(0) + 1);
        }
        census["strategies"][strategy] =
            json!(census["strategies"][strategy].as_u64().unwrap_or(0) + 1);
    }
    let scenario_report = scenario::report(&graph.scans[&source_path]);
    let (boot, combat) = policy::minimum_sets(&graph, &source_path);
    let blockers = policy::blockers(&graph, &script_report, &boot, &source_path);
    let (audio, effects, ai) = assets::inventories(&graph, mission_dir);
    // Everything that needs source scan rows has finished. Material provenance
    // uses tag identities and its own existing decoder, so release rows now.
    graph.scans.clear();
    timings.insert("cross_reference_seconds", started.elapsed().as_secs_f64());
    let started = Instant::now();
    println!("Port census: material provenance (no pixels or tags written)");
    let materials = assets::materials(&graph, &h3_index);
    timings.insert("material_analysis_seconds", started.elapsed().as_secs_f64());
    let mut severity_counts: BTreeMap<String, usize> = BTreeMap::new();
    for b in &blockers {
        *severity_counts
            .entry(b["severity"].as_str().unwrap().into())
            .or_default() += 1;
    }
    let summary = json!({"unique_h3_tags":graph.tags.len(),"direct_scenario_dependencies":graph.tags.values().filter(|t|t["direct_dependency"]==true).count(),"transitive_dependencies":graph.tags.values().filter(|t|t["only_transitive"]==true).count(),"missing_references":graph.tags.values().filter(|t|t["exists"]==false).count(),"tag_groups":groups.len(),"dependency_edges":graph.edges.len(),"strategies":strategies,"scripts":script_report["summary"],"blockers":severity_counts,"path_collisions":collisions.len(),"field_walked_tags":graph.tags.values().filter(|r|r["dependency_scan"]["parsed_fields"]==true).count()});
    let evidence = json!({"levels":{"VERIFIED":"Direct source/schema/tool observation","INFERRED":"Derived mapping, not runtime validation","PROVISIONAL":"Planning hypothesis","UNKNOWN":"Insufficient evidence"},"boundaries":["serialized tag truth","semantic interpretation","official loader acceptance","live Reach runtime"],"foundry_capabilities":policy::capabilities(),"licensing":{"direct_source_copied_from_baboon_or_blam_tags":false,"existing_dependency":"Foundry's pre-existing pinned blam-tags dependency retained; public read/compare APIs used","reference_source_license":"No top-level grant found at inspected Baboon/blam-tags revisions; do not infer permission for source transplantation","conceptual_reuse":["source-scoped canonical identities","dependency source disagreement","schema facts separate from reviewed policy","native versus generated layouts","official acceptance separate from runtime behavior"]}});
    let report = json!({"format":FORMAT,"version":VERSION,"source":{"scenario":source_path,"h3_tags_root":display(&h3),"reach_tags_root":display(&reach),"h3_data_root":data.as_deref().map(display),"definitions_root":definitions.as_deref().map(display),"definitions_revision":def_identity,"foundry_fast_revision":env!("FOUNDRY_FAST_REVISION"),"decoder_revision":crate::DECODER,"baboon_reference_revision":baboon.as_deref().and_then(revision).unwrap_or_else(||"f4df490579f83697aa7d56ade53abf8071ff5449".into()),"troop_reference_revision":troop.as_deref().and_then(revision).unwrap_or_else(||"69c574d238315c05e0f49140509d9548e20fcc0e".into()),"reference_revision_basis":"explicit checkout when supplied; otherwise implementation-study pin","scenario_sha256":digest(&fs::read(&input)?)},"safety":{"game_content_written":false,"tag_writer_invoked":false,"official_tools_invoked":false,"blender_required":false},"summary":summary,"tag_groups":group_rows.values().collect::<Vec<_>>(),"schema_compatibility_profiles":compatibility,"serialized_layout_comparisons":actual_compatibility,"tags":graph.tags.values().collect::<Vec<_>>(),"dependencies":graph.edges,"scenarios":scenario_report,"materials":materials,"audio":audio,"effects":effects,"ai":ai,"scripts":script_report,"scenario_symbol_table":source_symbols,"path_collisions":collisions,"proposed_path_map":path_map,"minimum_boot_set":boot,"minimum_combat_set":combat,"blockers":blockers,"diagnostics":diagnostics,"evidence":evidence,"limitations":["This is a source census and proposed build plan, not a porter","Generic dependency graph is a union of observed main fields and declared want; dynamic script references and runtime implicit dependencies can remain unknown","Large resource tags with want are not field-walked by default; use --all-fields for a slower audit","Serialized-layout comparisons are attached when available; definition-only fallbacks remain explicit. All losses are potential schema losses, not per-value loss","No Reach loader, Tool, shader, sound, scenario or runtime acceptance is claimed","Cached reads use source root, definitions digest, decoder, file size and mtime; unchanged metadata after content edits can invalidate that assumption"]});
    let started = Instant::now();
    write_json_new(
        &output.join(format!("{mission}_portability_report.json")),
        &report,
    )?;
    write_new(
        &output.join(format!("{mission}_portability_report.md")),
        &markdown::render(&report),
    )?;
    write_json_new(
        &output.join(format!("{mission}_dependency_graph.json")),
        &json!({"format":"foundry.h3-dependency-graph","version":1,"scenario":source_path,"nodes":graph.tags.keys().collect::<Vec<_>>(),"edges":report["dependencies"]}),
    )?;
    timings.insert("report_generation_seconds", started.elapsed().as_secs_f64());
    write_json_new(
        &output.join(format!("{mission}_timings.json")),
        &json!({"phase_seconds":timings,"cache_hits":graph.cache_hits,"note":"Variable timing/cache metrics are separate to keep the engineering reports deterministic"}),
    )?;
    println!(
        "Port census complete: {} tags, {} groups, {} missing references\n{}",
        summary["unique_h3_tags"],
        summary["tag_groups"],
        summary["missing_references"],
        display(&output)
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn protected_paths_include_kit_ancestors() {
        assert!(overlap(Path::new("C:/kit/tags"), Path::new("c:/KIT")));
        assert!(!overlap(Path::new("C:/kit-output"), Path::new("C:/kit")));
    }
    #[test]
    fn required_options_and_duplicates() {
        assert!(options(vec!["--wrong".into()]).is_err());
        assert!(
            options(vec![
                "--output".into(),
                "a".into(),
                "--output".into(),
                "b".into()
            ])
            .is_err()
        );
    }
    #[test]
    fn version_is_stable() {
        assert_eq!(FORMAT, "foundry.h3-reach-portability-census");
        assert_eq!(VERSION, 1);
        let schema: Value =
            serde_json::from_str(include_str!("../../data/port_census.schema.json")).unwrap();
        assert_eq!(schema["properties"]["format"]["const"], FORMAT);
        assert_eq!(schema["properties"]["version"]["const"], VERSION);
        assert!(schema["$defs"]["tag"].is_object());
    }
}
