use anyhow::{Context, Result, bail};
use blam_tags::paths::group_tag_to_extension;
use blam_tags::{TagFile, TagFileHeader};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

pub fn normalized(path: &str) -> Result<String> {
    let p = path.replace('\\', "/").to_lowercase();
    if p.is_empty()
        || p.contains([':', '\0'])
        || p.starts_with('/')
        || p.split('/')
            .any(|s| s.is_empty() || s == "." || s == ".." || s.ends_with(['.', ' ']))
    {
        bail!("Unsafe relative tag path: {path}");
    }
    Ok(p)
}
pub fn identity(root: &Path, path: &str, group: &str) -> Result<String> {
    Ok(super::digest(
        format!(
            "halo3_mcc\n{}\n{}\n{group}",
            super::display(root).to_lowercase(),
            normalized(path)?
        )
        .as_bytes(),
    ))
}
pub fn destination(path: &str, mission_dir: &str, mission: &str) -> String {
    if let Some(tail) = path.strip_prefix(&format!("{mission_dir}/")) {
        format!("levels/h3/{mission}/{tail}")
    } else {
        format!("h3_port/{path}")
    }
}
pub fn is_reparse(meta: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        meta.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        meta.file_type().is_symlink()
    }
}
pub fn index(root: &Path, errors: &mut Vec<Value>) -> Result<BTreeMap<String, PathBuf>> {
    let mut pending = vec![root.to_owned()];
    let mut found = BTreeMap::new();
    while let Some(dir) = pending.pop() {
        let entries = match fs::read_dir(&dir) {
            Ok(v) => v,
            Err(e) => {
                errors.push(json!({"code":"directory_read_failed","path":super::display(&dir),"error":e.to_string()}));
                continue;
            }
        };
        for entry in entries {
            let entry = match entry {
                Ok(e) => e,
                Err(e) => {
                    errors.push(json!({"code":"directory_entry_failed","error":e.to_string()}));
                    continue;
                }
            };
            let path = entry.path();
            let meta = fs::symlink_metadata(&path)?;
            if is_reparse(&meta) {
                errors.push(json!({"code":"reparse_point_skipped","path":super::display(&path)}));
                continue;
            }
            if meta.is_dir() {
                pending.push(path);
            } else if meta.is_file() {
                let relative = normalized(&path.strip_prefix(root)?.to_string_lossy())?;
                if found.insert(relative.clone(), path).is_some() {
                    bail!("Case-insensitive source identity collision: {relative}");
                }
            }
        }
    }
    Ok(found)
}
pub fn ref_path(group: u32, name: &str) -> Result<String> {
    let extension = group_tag_to_extension(group)
        .map(str::to_owned)
        .unwrap_or_else(|| format!("group_{group:08x}"));
    normalized(&format!("{name}.{extension}"))
}
pub fn extension(path: &str) -> &str {
    path.rsplit('.').next().unwrap_or("unknown")
}

#[derive(Default)]
pub struct Scan {
    pub refs: BTreeMap<String, BTreeSet<String>>,
    pub reference_fields: Vec<Value>,
    pub metadata: Vec<Value>,
    pub sections: Vec<Value>,
    pub block_counts: BTreeMap<String, u64>,
    pub fields: u64,
    pub data_bytes: u64,
    pub resources: u64,
    pub errors: Vec<Value>,
    pub want_status: String,
    pub parsed: bool,
    pub header: Value,
    pub source_schema: Value,
}
impl Scan {
    fn add(&mut self, path: String, evidence: &str) {
        self.refs.entry(path).or_default().insert(evidence.into());
    }
    pub fn compact(&mut self) {
        // Full references/counts and schema details are retained separately.
        // Bound optional metadata so thousands of sound/AI tags cannot hold
        // millions of repeated field-map allocations in memory.
        if self.header["group"] != "scnr" && self.metadata.len() > 256 {
            self.metadata.truncate(256);
            self.errors.push(json!({"code":"metadata_summary_bounded","limit":256,"note":"Full tag references and block/permutation/resource counts remain retained"}));
        }
        for row in self
            .metadata
            .iter_mut()
            .chain(self.reference_fields.iter_mut())
        {
            if let Some(map) = row.as_object_mut() {
                map.remove("raw_name");
                map.remove("ordinal");
            }
        }
    }
    pub fn json(&self) -> Value {
        json!({"references":self.refs,"reference_fields":self.reference_fields,"metadata":self.metadata,"sections":self.sections,"block_counts":self.block_counts,"fields":self.fields,"data_bytes":self.data_bytes,"resource_headers":self.resources,"diagnostics":self.errors,"want_status":self.want_status,"parsed_fields":self.parsed,"header":self.header,"source_schema":self.source_schema})
    }
    pub fn from_json(v: &Value) -> Result<Self> {
        Ok(Self {
            refs: serde_json::from_value(v["references"].clone())?,
            reference_fields: serde_json::from_value(v["reference_fields"].clone())?,
            metadata: serde_json::from_value(v["metadata"].clone())?,
            sections: serde_json::from_value(v["sections"].clone())?,
            block_counts: serde_json::from_value(v["block_counts"].clone())?,
            fields: v["fields"].as_u64().context("fields")?,
            data_bytes: v["data_bytes"].as_u64().context("data_bytes")?,
            resources: v["resource_headers"].as_u64().context("resources")?,
            errors: serde_json::from_value(v["diagnostics"].clone())?,
            want_status: v["want_status"].as_str().context("want")?.into(),
            parsed: v["parsed_fields"].as_bool().context("parsed")?,
            header: v["header"].clone(),
            source_schema: v["source_schema"].clone(),
        })
    }
}

pub fn scan(path: &Path, scenario: bool, all_fields: bool) -> Scan {
    let mut result = Scan::default();
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<()> {
        let (header, endian) = TagFileHeader::peek(path)?;
        result.header = json!({"group":String::from_utf8_lossy(&header.group_tag.to_be_bytes()),"group_tag":header.group_tag,"group_version":header.group_version,"file_version":header.version,"build_version":header.build_version,"build_number":header.build_number,"endian":format!("{endian:?}")});
        match TagFile::read_dependency_references(path) {
            Ok(Some(refs)) => {
                result.want_status = "present".into();
                for (group, name) in refs {
                    if !name.is_empty() {
                        match ref_path(group,&name) {Ok(p)=>result.add(p,"declared_want"),Err(e)=>result.errors.push(json!({"code":"unsafe_want_reference","group":group,"name":name,"error":e.to_string()}))}
                    }
                }
            }
            Ok(None) => result.want_status = "absent".into(),
            Err(e) => {
                result.want_status = "error".into();
                result
                    .errors
                    .push(json!({"code":"want_read_failed","error":e.to_string()}));
            }
        }
        let bytes = fs::metadata(path)?.len();
        // Large resource assets use want when available. Explicitly mark their
        // field source unobserved; an empty want stream never proves no refs.
        if bytes > 4 * 1024 * 1024 && result.want_status == "present" && !scenario && !all_fields {
            result.errors.push(json!({"code":"large_tag_fields_not_walked","reason":"Lightweight dependency stream used; --all-fields audits the main fields"}));
            return Ok(());
        }
        if bytes > 512 * 1024 * 1024 {
            bail!("Tag exceeds 512 MiB per-file read budget");
        }
        let tag = TagFile::read(path)?;
        let group = String::from_utf8_lossy(&header.group_tag.to_be_bytes()).into_owned();
        result.source_schema = json!({"root_guid":tag.root().definition().guid(),"fingerprint":super::compat::fingerprint(&tag),"basis":"all_nested_serialized_field_definitions","actual_layout_compared":false});
        let retain = matches!(
            group.as_str(),
            "snd!"
                | "lsnd"
                | "snde"
                | "effe"
                | "char"
                | "styl"
                | "bipd"
                | "vehi"
                | "gint"
                | "jmad"
                | "ligh"
        );
        crate::source_walk::walk(
            tag.root(),
            "",
            0,
            &mut |row| {
                result.fields += 1;
                if result.fields > 10_000_000 {
                    bail!("Tag field traversal exceeds ten million fields");
                }
                let address = row["address"].as_str().unwrap();
                let root = address.split('/').next().unwrap_or("");
                let root_name = root.split('#').next().unwrap_or("");
                let name = row["name"].as_str().unwrap_or("");
                if !address.contains('/') && !address.contains('[') {
                    result.sections.push(row.clone());
                }
                if row["kind"] == "block" || row["kind"] == "array" {
                    *result.block_counts.entry(name.into()).or_default() +=
                        row["count"].as_u64().unwrap_or(0);
                }
                if row["kind"] == "data" {
                    result.data_bytes += row["bytes"].as_u64().unwrap_or(0);
                }
                if row["kind"] == "resource_header_only" {
                    result.resources += 1;
                }
                if let (Some(group), Some(name)) = (
                    row["value"]["group"].as_u64(),
                    row["value"]["path"].as_str(),
                ) {
                    if !name.is_empty() {
                        match ref_path(group as u32,name) {Ok(p)=>{result.add(p,"parsed_field");result.reference_fields.push(row.clone());},Err(e)=>result.errors.push(json!({"code":"unsafe_field_reference","address":address,"error":e.to_string()}))}
                    }
                }
                let meaningful = if scenario {
                    matches!(
                        root_name,
                        "structure bsps"
                            | "zone sets"
                            | "skies"
                            | "object names"
                            | "squads"
                            | "squad groups"
                            | "zones"
                            | "ai objectives"
                            | "designer zones"
                            | "scripting data"
                            | "trigger volumes"
                            | "player starting locations"
                            | "cutscene flags"
                            | "cutscene camera points"
                            | "reference frames"
                            | "scenery"
                            | "machines"
                            | "controls"
                            | "crates"
                            | "vehicles"
                            | "weapons"
                            | "equipment"
                            | "bipeds"
                            | "giants"
                            | "effect scenery"
                            | "sound scenery"
                            | "light volumes"
                            | "terminals"
                            | "source files"
                            | "ai user hint data"
                            | "device groups"
                            | "decals"
                            | "decorators"
                            | "style pallette"
                            | "cinematics"
                            | "cortana effects"
                            | "flocks"
                    ) || root_name.ends_with(" palette")
                } else {
                    retain
                        && (row["kind"] == "block"
                            || row["kind"] == "resource_header_only"
                            || row["kind"] == "data"
                            || row["value"].is_string()
                            || [
                                "codec",
                                "sample count",
                                "sample rate",
                                "encoding",
                                "compression",
                                "permutation index",
                                "resource index",
                                "bank",
                            ]
                            .contains(&name))
                };
                // Large navigation coordinate arrays remain counted. Preserve
                // authored names, joins, transforms and pose streams, not every
                // runtime pathfinding scalar in the summary.
                let noisy = address.contains("/firing positions#")
                    || address.contains("/points#")
                    || address.contains("/vertices#");
                let padding = row["value"]["representation"] == "decoder_debug"
                    || (row["kind"] == "block" && row["count"] == 0);
                // Decorator instance buffers must not crowd out later systems.
                // Keep references, shallow structure and resource summaries;
                // full nested block counts are collected independently above.
                let decorator_payload = root_name == "decorators"
                    && address.contains('/')
                    && name != "name"
                    && row["value"]["path"].is_null()
                    && !(row["kind"] == "block" && address.matches('/').count() <= 2)
                    && row["kind"] != "data"
                    && row["kind"] != "resource_header_only";
                if meaningful
                    && !padding
                    && !decorator_payload
                    && (!noisy || name == "name")
                    && result.metadata.len() < if scenario { 600_000 } else { 1000 }
                {
                    result.metadata.push(row);
                }
                Ok(())
            },
            &mut |_| Ok(json!({})),
        )?;
        result.parsed = true;
        let declared: BTreeSet<_> = result
            .refs
            .iter()
            .filter(|(_, v)| v.contains("declared_want"))
            .map(|(p, _)| p.clone())
            .collect();
        let parsed: BTreeSet<_> = result
            .refs
            .iter()
            .filter(|(_, v)| v.contains("parsed_field"))
            .map(|(p, _)| p.clone())
            .collect();
        if result.want_status == "present" && declared != parsed {
            result.errors.push(json!({"code":"dependency_sources_disagree","want_only":declared.difference(&parsed).collect::<Vec<_>>(),"fields_only":parsed.difference(&declared).collect::<Vec<_>>(),"note":"want can include build-time or transitive dependencies; neither source is assumed complete"}));
        }
        if result.metadata.len() == if scenario { 600_000 } else { 1000 } {
            result.errors.push(json!({"code":"metadata_budget_reached","limit":if scenario{600000}else{1000},"note":"Reference traversal and block counts are unaffected; detailed nonessential metadata is bounded"}));
        }
        Ok(())
    }));
    match outcome {Ok(Ok(()))=>{},Ok(Err(e))=>result.errors.push(json!({"code":"tag_read_failed","error":format!("{e:#}")})),Err(_)=>result.errors.push(json!({"code":"reader_panicked","error":"Pinned reader panicked while analyzing this tag"}))};
    result
}

pub struct Graph {
    pub tags: BTreeMap<String, Value>,
    pub scans: BTreeMap<String, Scan>,
    pub edges: Vec<Value>,
    pub cache_hits: usize,
}
pub fn build(
    root: &Path,
    scenario: &str,
    index: &BTreeMap<String, PathBuf>,
    cache: &Path,
    cache_scope: &str,
    all_fields: bool,
) -> Result<Graph> {
    build_using(
        root,
        scenario,
        index,
        cache,
        cache_scope,
        all_fields,
        &mut scan,
    )
}
fn build_using(
    root: &Path,
    scenario: &str,
    index: &BTreeMap<String, PathBuf>,
    cache: &Path,
    cache_scope: &str,
    all_fields: bool,
    scan: &mut impl FnMut(&Path, bool, bool) -> Scan,
) -> Result<Graph> {
    let mut graph = Graph {
        tags: BTreeMap::new(),
        scans: BTreeMap::new(),
        edges: vec![],
        cache_hits: 0,
    };
    let mut queue = VecDeque::from([(scenario.to_owned(), 0usize, Vec::<String>::new())]);
    let mut queued = BTreeSet::from([scenario.to_owned()]);
    while let Some((path, depth, mut first_path)) = queue.pop_front() {
        if graph.tags.len() >= 100_000 {
            bail!(
                "Dependency census exceeds 100000 tag budget; refusing a silently truncated graph"
            );
        }
        first_path.push(path.clone());
        let group = extension(&path);
        let mut scan_result = Scan::default();
        let mut size = None;
        let mut mtime = None;
        if let Some(file) = index.get(&path) {
            let meta = fs::metadata(file)?;
            size = Some(meta.len());
            mtime = meta
                .modified()
                .ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_nanos().to_string());
            let mut key_input = format!("{cache_scope}\n{path}\n{size:?}\n{mtime:?}\n{all_fields}");
            if path == scenario {
                key_input.push_str("\nscenario-metadata-4");
            }
            let key = super::digest(key_input.as_bytes());
            let cached = cache.join(format!("{key}.json"));
            let reused = fs::read(&cached)
                .ok()
                .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
                .filter(|v| v["cache_key"] == key)
                .and_then(|v| Scan::from_json(&v["scan"]).ok());
            if let Some(scan) = reused {
                scan_result = scan;
                graph.cache_hits += 1;
            } else {
                scan_result = scan(file, path == scenario, all_fields);
                if !cached.exists() {
                    super::write_json_new(
                        &cached,
                        &json!({"cache_key":key,"scan":scan_result.json()}),
                    )?;
                } else {
                    eprintln!(
                        "Ignoring invalid analysis cache entry: {}",
                        cached.display()
                    );
                }
            }
            scan_result.compact();
        }
        let mut field_addresses: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for field in &scan_result.reference_fields {
            if let (Some(group), Some(name), Some(address)) = (
                field["value"]["group"].as_u64(),
                field["value"]["path"].as_str(),
                field["address"].as_str(),
            ) {
                if let Ok(target) = ref_path(group as u32, name) {
                    field_addresses
                        .entry(target)
                        .or_default()
                        .push(address.into());
                }
            }
        }
        for (target, evidence) in &scan_result.refs {
            let mut evidence = evidence.clone();
            if path == scenario && evidence.contains("parsed_field") {
                evidence.insert("scenario_source_inventory".into());
            }
            let addresses = field_addresses.get(target).cloned().unwrap_or_default();
            if path == scenario && addresses.iter().any(|a| a.starts_with("source files#")) {
                evidence.insert("scenario_script_external_reference".into());
            }
            graph.edges.push(json!({"source":path,"target":target,"evidence":evidence,"source_field_addresses":addresses,"relationship":"declared_or_field_reference","runtime_required":"UNKNOWN"}));
            if queued.insert(target.clone()) {
                queue.push_back((target.clone(), depth + 1, first_path.clone()));
            }
        }
        graph.tags.insert(path.clone(),json!({"source_path":path,"source_group":group,"source_identity":{"source_game":"halo3_mcc","canonical_source_root":super::display(root),"normalized_tag_path":path,"tag_group":group,"id":identity(root,&path,group)?},"exists":index.contains_key(&path),"source_size":size,"source_mtime_unix_ns":mtime,"direct_dependency":depth==1,"only_transitive":depth>1,"dependency_depth":depth,"first_reached_by":first_path,"references":scan_result.refs.keys().collect::<Vec<_>>(),"referenced_by":[],"header":scan_result.header,"actual_source_schema":scan_result.source_schema,"dependency_scan":{"want":scan_result.want_status,"parsed_fields":scan_result.parsed,"field_count":scan_result.fields,"resource_headers":scan_result.resources},"diagnostics":scan_result.errors}));
        if path != scenario {
            scan_result.reference_fields.clear();
            scan_result.sections.clear();
            scan_result.errors.clear();
            scan_result.header = Value::Null;
            scan_result.source_schema = Value::Null;
        }
        graph.scans.insert(path, scan_result);
        if graph.tags.len() % 250 == 0 {
            println!(
                "Port census: {} unique tags; {} pending",
                graph.tags.len(),
                queue.len()
            );
        }
    }
    let mut reverse: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for edge in &graph.edges {
        reverse
            .entry(edge["target"].as_str().unwrap().into())
            .or_default()
            .insert(edge["source"].as_str().unwrap().into());
    }
    for (path, row) in &mut graph.tags {
        row["referenced_by"] = json!(reverse.get(path).cloned().unwrap_or_default());
        row["direct_dependency"] =
            json!(reverse.get(path).is_some_and(|v| v.contains(scenario)) && path != scenario);
        row["only_transitive"] = json!(path != scenario && row["direct_dependency"] == false);
    }
    graph.edges.sort_by(|a, b| {
        (a["source"].as_str(), a["target"].as_str())
            .cmp(&(b["source"].as_str(), b["target"].as_str()))
    });
    Ok(graph)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn identities_are_source_scoped() {
        let a = Path::new("/a/tags");
        assert_eq!(
            identity(a, "Objects\\BRUTE.biped", "biped").unwrap(),
            identity(a, "objects/brute.biped", "biped").unwrap()
        );
        assert_ne!(
            identity(a, "x.model", "model").unwrap(),
            identity(Path::new("/b/tags"), "x.model", "model").unwrap()
        );
    }
    #[test]
    fn safe_paths_and_mapping() {
        for p in ["../tag", "c:/x", "/x", "a//b", "a/./b", "a./b"] {
            assert!(normalized(p).is_err());
        }
        assert_eq!(
            destination(
                "levels/solo/040_voi/a.bitmap",
                "levels/solo/040_voi",
                "040_voi"
            ),
            "levels/h3/040_voi/a.bitmap"
        );
        assert_eq!(
            destination("a/b.bitmap", "levels/solo/040_voi", "040_voi"),
            "h3_port/a/b.bitmap"
        );
    }
    #[test]
    fn unknown_groups_retain_identity() {
        assert_eq!(ref_path(0x01020304, "test").unwrap(), "test.group_01020304");
    }
    #[test]
    fn graph_deduplicates_cycles_missing_refs_and_is_deterministic() {
        let root =
            std::env::temp_dir().join(format!("port_census_graph_test_{}", std::process::id()));
        fs::create_dir_all(root.join("cache")).unwrap();
        let root = root.canonicalize().unwrap();
        let mut files = BTreeMap::new();
        for name in ["root.scenario", "a.model", "b.model"] {
            let p = root.join(name);
            fs::write(&p, b"fixture").unwrap();
            files.insert(name.into(), p);
        }
        let mut reader = |path: &Path, _: bool, _: bool| {
            let mut s = Scan::default();
            let name = path.file_name().unwrap().to_str().unwrap();
            let refs = match name {
                "root.scenario" => vec!["a.model", "b.model"],
                "a.model" => vec!["b.model", "missing.bitmap"],
                _ => vec!["a.model", "root.scenario"],
            };
            for p in refs {
                s.add(p.into(), "parsed_field");
            }
            // A real 040_voi coordinate exposed one-ULP drift in serde_json's
            // default cache parser. Preserve the source decimal and raw bits.
            s.metadata.push(json!({"kind":"value","name":"point","address":"point#0","value":{"values":[f32::from_bits(3216466039) as f64],"bits":[3216466039u32]}}));
            s
        };
        let first = build_using(
            &root,
            "root.scenario",
            &files,
            &root.join("cache"),
            "test",
            false,
            &mut reader,
        )
        .unwrap();
        let second = build_using(
            &root,
            "root.scenario",
            &files,
            &root.join("cache"),
            "test",
            false,
            &mut |_, _, _| panic!("cache miss"),
        )
        .unwrap();
        assert_eq!(first.tags.len(), 4);
        assert_eq!(first.tags, second.tags);
        assert_eq!(first.edges, second.edges);
        assert_eq!(
            first.scans["root.scenario"].metadata,
            second.scans["root.scenario"].metadata
        );
        assert_eq!(first.tags["a.model"]["dependency_depth"], 1);
        assert_eq!(first.tags["missing.bitmap"]["dependency_depth"], 2);
        assert_eq!(first.tags["missing.bitmap"]["exists"], false);
        assert_eq!(
            first.tags["a.model"]["referenced_by"],
            json!(["b.model", "root.scenario"])
        );
        assert_eq!(second.cache_hits, 3);
        assert!(
            build_using(
                &root,
                "root.scenario",
                &files,
                &root.join("cache"),
                "changed-schema",
                false,
                &mut |p, s, a| reader(p, s, a)
            )
            .unwrap()
            .cache_hits
                == 0
        );
        fs::remove_dir_all(root).unwrap();
    }
}
