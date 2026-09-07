//! Read-only scenario field inventory for the H3 Blender inspection prototype.
use anyhow::{bail, Context, Result};
use blam_tags::{TagFile, TagStruct};
#[cfg(test)] use blam_tags::TagFieldData as D;
use serde_json::json;
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Component, Path, PathBuf};

#[path = "../scenario_geometry.rs"]
mod scenario_geometry;
#[path = "../scenario_record_stream.rs"]
mod scenario_record_stream;
use scenario_record_stream::RecordStream;

const DECODER: &str = "5d0509fb75eadb96ac7774542ca0b2c10aed7b00";
const MAX_BLOB_BYTES: usize = 512 * 1024 * 1024;

#[path = "../source_values.rs"]
mod source_values;
use source_values::leaf;
#[cfg(test)] use source_values::floats;

#[path = "../source_walk.rs"]
mod source_walk;
#[path = "../port_census/mod.rs"]
mod port_census;

fn address(parent: &str, name: &str, ordinal: usize) -> String {
    let segment = format!("{name}#{ordinal}");
    if parent.is_empty() { segment } else { format!("{parent}/{segment}") }
}

struct Inventory<'a> {
    output: &'a Path,
    records: RecordStream,
    blob_count: usize,
    blob_bytes: usize,
}

impl Inventory<'_> {
    fn walk(&mut self, node: TagStruct<'_>, parent: &str, depth: usize) -> Result<()> {
        let records = &mut self.records;
        let output = self.output;
        let blob_count = &mut self.blob_count;
        let blob_bytes = &mut self.blob_bytes;
        source_walk::walk(node, parent, depth, &mut |row| {
            let address = row["address"].as_str().context("Missing source address")?;
            if !address.contains('/') && !address.contains('[') {
                let name = row["name"].as_str().unwrap_or("");
                records.begin_root(address, name)?;
                println!("Inventory section: {name}");
            }
            records.push(&row)
        }, &mut |bytes| {
            *blob_bytes = blob_bytes.checked_add(bytes.len()).context("Blob size overflow")?;
            if *blob_bytes > MAX_BLOB_BYTES { bail!("Scenario data exceeds blob budget"); }
            let relative = format!("blobs/{:06}.bin", *blob_count);
            *blob_count += 1;
            let mut file = OpenOptions::new().write(true).create_new(true).open(output.join(&relative))?;
            file.write_all(bytes)?;
            Ok(json!({"file":relative}))
        })
    }
}

fn safe_relative(path: &str) -> bool {
    let value = path.replace('\\', "/");
    !value.is_empty() && !value.contains(':') && !value.starts_with('/') &&
        Path::new(&value).components().all(|part| matches!(part, Component::Normal(_)))
}

fn run() -> Result<()> {
    if std::env::args().nth(1).as_deref() == Some("port-census") {
        return port_census::run(std::env::args().skip(2).collect());
    }
    let mut args = std::env::args().skip(1);
    let mut options = BTreeMap::new();
    let mut include_geometry = false;
    let mut environment_semantics = false;
    let mut selection_only = false;
    while let Some(key) = args.next() {
        if key == "--version" { println!("h3-scenario-inspect schema 2; scene schema 1; environment semantics 1; decoder {DECODER}"); return Ok(()); }
        if key == "--environment-semantics" {
            if environment_semantics { bail!("Repeated environment semantics option"); }
            environment_semantics = true; continue;
        }
        if key == "--selection-json" { selection_only = true; continue; }
        if key == "--geometry" {
            if include_geometry { bail!("Repeated geometry option"); }
            include_geometry = true; continue;
        }
        if !["--input", "--tags-root", "--output", "--bsp-indices"].contains(&key.as_str()) { bail!("Unknown option: {key}"); }
        let value = args.next().context("Missing option value")?;
        if options.insert(key.clone(), value).is_some() { bail!("Repeated option: {key}"); }
    }
    let selected = scenario_geometry::indices(options.get("--bsp-indices").map(String::as_str).unwrap_or(""))?;
    if selected.is_some() && !include_geometry { bail!("BSP selection requires --geometry"); }
    if environment_semantics && !include_geometry { bail!("Environment semantics requires --geometry"); }
    let get = |key: &str| -> Result<PathBuf> {
        PathBuf::from(options.get(key).with_context(|| format!("Required: {key}"))?).canonicalize().map_err(Into::into)
    };
    let root = get("--tags-root")?;
    let input = get("--input")?;
    if selection_only {
        if !input.starts_with(&root) || !root.is_dir() || !input.is_file() { bail!("Invalid scenario source root"); }
        let tag = TagFile::read(&input)?;
        if tag.header.group_tag.to_be_bytes() != *b"scnr" { bail!("Expected a loose scenario tag"); }
        let mut skies = Vec::new();
        for field in tag.root().fields().filter(|f| f.clean_name() == "skies") {
            if let Some(block) = field.as_block() {
                for (index, entry) in block.iter().enumerate() {
                    let fields: Vec<_> = entry.fields().map(|f| json!({"name":f.clean_name(), "value":f.value().map(leaf)})).collect();
                    skies.push(json!({"index":index, "fields":fields}));
                }
            }
        }
        println!("{}", json!({"source_tag":input.strip_prefix(&root)?.to_string_lossy().replace('\\', "/"), "skies":skies}));
        return Ok(());
    }
    let output = get("--output")?;
    if !root.is_dir() || !output.is_dir() || !input.is_file() { bail!("Invalid input/output paths"); }
    if !input.starts_with(&root) || output.starts_with(&root) { bail!("Source and output directories must be separate"); }
    if fs::read_dir(&output)?.next().is_some() { bail!("Output directory must be empty"); }
    let relative = input.strip_prefix(&root)?.to_string_lossy().replace('\\', "/");
    if !safe_relative(&relative) { bail!("Unsafe source path"); }
    println!("Reading scenario {relative}");
    let inventory_started = std::time::Instant::now();
    let tag = TagFile::read(&input)?;
    if tag.header.group_tag.to_be_bytes() != *b"scnr" { bail!("Expected a loose scenario tag, not a model or cache map"); }
    fs::create_dir(output.join("blobs"))?;
    let mut inventory = Inventory { output:&output, records:RecordStream::new(&output)?, blob_count:0, blob_bytes:0 };
    inventory.walk(tag.root(), "", 0)?;
    let summary = inventory.records.summary()?;
    let mut payload = json!({"format":"foundry.h3-scenario-inspection", "version":2,
        "decoder":DECODER, "source_tag":relative, "source_group":"scnr",
        "source_group_version":tag.header.group_version,
        "coordinate_encoding":"source_world_units_unmodified", "destination_tags_written":false,
        "blob_count":inventory.blob_count, "blob_bytes":inventory.blob_bytes,
        "scope":{"named_scenario_fields":true, "opaque_data_blobs":true,
            "bsp_dependencies_loaded":false, "resource_payloads_decoded":false,
            "scripts_executed":false, "lossless_tag_roundtrip":false}});
    payload["timings"] = json!({"inventory_helper_seconds":inventory_started.elapsed().as_secs_f64()});
    println!("H3 timing scenario inventory helper: {:.3}s",inventory_started.elapsed().as_secs_f64());
    payload.as_object_mut().unwrap().extend(summary.as_object().unwrap().clone());
    let mut writer = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(output.join("scenario.h3inspect.json"))?);
    serde_json::to_writer(&mut writer, &payload)?; writer.flush()?;
    println!("Inspection complete: {} fields, {} references, {} data blobs", inventory.records.count, inventory.records.references, inventory.blob_count);
    drop(writer);
    // BSP reconstruction has a separate manifest and does not change the inventory's scope.
    scenario_geometry::extract(&tag, &root, &output, &relative, include_geometry, selected.as_ref(), environment_semantics)?;
    Ok(())
}

fn main() {
    if let Err(error) = run() { eprintln!("{error:#}"); std::process::exit(1); }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn duplicate_names_keep_ordinal_identity() {
        assert_ne!(address("hints#4[0]", "point", 3), address("hints#4[0]", "point", 4));
    }
    #[test] fn source_indices_keep_none_sentinel() {
        assert_eq!(leaf(D::ShortBlockIndex(-1)), json!(-1));
        assert_eq!(leaf(D::ShortBlockIndex(0)), json!(0));
    }
    #[test] fn flags_keep_raw_bits_and_names() {
        let value = leaf(D::LongFlags { value:1025, names:vec![(0,"giants zone".into())] });
        assert_eq!(value["value"], 1025); assert_eq!(value["set_bits"][0][1], "giants zone");
    }
    #[test] fn nonfinite_float_bits_are_retained() {
        let value = floats(&[f32::NAN, f32::INFINITY, 0.0]);
        assert!(value["values"][0].is_null()); assert_eq!(value["bits"][1], f32::INFINITY.to_bits());
    }
    #[test] fn points_are_not_rescaled() {
        let value = leaf(D::RealPoint3d(blam_tags::math::RealPoint3d {x:1.0,y:2.0,z:3.0}));
        assert_eq!(value["values"], json!([1.0,2.0,3.0]));
    }
    #[test] fn euler_components_and_bits_are_retained_in_source_order() {
        let value = leaf(D::RealEulerAngles3d(blam_tags::math::RealEulerAngles3d {yaw:0.25,pitch:-0.5,roll:1.0}));
        assert_eq!(value["values"], json!([0.25,-0.5,1.0]));
        assert_eq!(value["bits"][1], (-0.5_f32).to_bits());
        let value = leaf(D::RealEulerAngles2d(blam_tags::math::RealEulerAngles2d {yaw:0.25,pitch:-0.5}));
        assert_eq!(value["values"], json!([0.25,-0.5]));
    }
    #[test] fn unsafe_source_paths_are_rejected() {
        for path in ["../outside.scenario", "C:\\outside", "/absolute", "\\\\server\\tag", ""] { assert!(!safe_relative(path)); }
        assert!(safe_relative("levels\\solo\\040_voi\\040_voi.scenario"));
    }
}
