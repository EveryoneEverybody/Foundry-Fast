//! Read-only scenario field inventory for the H3 Blender inspection prototype.
use anyhow::{bail, Context, Result};
use blam_tags::{TagFieldData as D, TagFile, TagStruct};
use blam_tags::paths::group_tag_to_extension;
use serde_json::{json, Value};
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
const MAX_DEPTH: usize = 96;
const MAX_BLOB_BYTES: usize = 512 * 1024 * 1024;

fn floats(values: &[f32]) -> Value {
    json!({"values": values.iter().map(|v| if v.is_finite() { Some(*v) } else { None }).collect::<Vec<_>>(),
           "bits": values.iter().map(|v| v.to_bits()).collect::<Vec<_>>()})
}

fn leaf(value: D) -> Value {
    match value {
        D::String(v) | D::LongString(v) => json!(v),
        D::StringId(v) | D::OldStringId(v) => json!(v.string),
        D::CharInteger(v) | D::CharBlockIndex(v) | D::CustomCharBlockIndex(v) => json!(v),
        D::ShortInteger(v) | D::ShortBlockIndex(v) | D::CustomShortBlockIndex(v) => json!(v),
        D::LongInteger(v) | D::LongBlockIndex(v) | D::CustomLongBlockIndex(v) | D::LongBlockFlags(v) => json!(v),
        D::Int64Integer(v) => json!(v),
        D::ByteInteger(v) | D::ByteBlockFlags(v) => json!(v),
        D::WordInteger(v) | D::WordBlockFlags(v) => json!(v),
        D::DwordInteger(v) | D::Tag(v) => json!(v),
        D::QwordInteger(v) => json!(v),
        D::CharEnum {value, name} => json!({"value":value, "name":name}),
        D::ShortEnum {value, name} => json!({"value":value, "name":name}),
        D::LongEnum {value, name} => json!({"value":value, "name":name}),
        D::ByteFlags {value, names} => json!({"value":value, "set_bits":names}),
        D::WordFlags {value, names} => json!({"value":value, "set_bits":names}),
        D::LongFlags {value, names} => json!({"value":value, "set_bits":names}),
        D::Angle(v) | D::Real(v) | D::RealSlider(v) | D::RealFraction(v) => floats(&[v]),
        D::RealPoint2d(v) => floats(&[v.x, v.y]),
        D::RealPoint3d(v) => floats(&[v.x, v.y, v.z]),
        D::RealVector2d(v) => floats(&[v.i, v.j]),
        D::RealVector3d(v) => floats(&[v.i, v.j, v.k]),
        D::RealQuaternion(v) => json!({"order":"wxyz", "components":floats(&[v.w, v.i, v.j, v.k])}),
        D::TagReference(v) => match v.group_tag_and_name {
            Some((group, name)) => json!({"group":group, "group_name":String::from_utf8_lossy(&group.to_be_bytes()),
                "path":name, "extension":group_tag_to_extension(group)}),
            None => Value::Null,
        },
        other => json!({"representation":"decoder_debug", "value":format!("{other:?}")}),
    }
}

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
        if depth > MAX_DEPTH { bail!("Scenario tree exceeds depth limit at {parent}"); }
        for field in node.fields() {
            let clean_name = field.clean_name();
            let path = address(parent, &clean_name, field.ordinal());
            if depth == 0 {
                self.records.begin_root(&path, &clean_name)?;
                println!("Inventory section: {clean_name}");
            }
            let mut row = json!({"address":path, "name":clean_name, "raw_name":field.name(),
                "ordinal":field.ordinal(), "type":field.type_name()});
            if let Some(nested) = field.as_struct() {
                row["kind"] = json!("struct");
                self.records.push(&row)?;
                self.walk(nested, &path, depth + 1)?;
            } else if let Some(block) = field.as_block() {
                row["kind"] = json!("block"); row["count"] = json!(block.len());
                self.records.push(&row)?;
                for (i, element) in block.iter().enumerate() {
                    self.walk(element, &format!("{path}[{i}]"), depth + 1)?;
                }
            } else if let Some(array) = field.as_array() {
                row["kind"] = json!("array");
                row["count"] = json!(array.iter().count()); self.records.push(&row)?;
                for (i, element) in array.iter().enumerate() {
                    self.walk(element, &format!("{path}[{i}]"), depth + 1)?;
                }
            } else if let Some(resource) = field.as_resource() {
                row["kind"] = json!("resource_header_only"); self.records.push(&row)?;
                if let Some(header) = resource.as_struct() { self.walk(header, &path, depth + 1)?; }
            } else if let Some(bytes) = field.as_data() {
                self.blob_bytes = self.blob_bytes.checked_add(bytes.len()).context("Blob size overflow")?;
                if self.blob_bytes > MAX_BLOB_BYTES { bail!("Scenario data exceeds blob budget"); }
                let relative = format!("blobs/{:06}.bin", self.blob_count);
                self.blob_count += 1;
                let mut file = OpenOptions::new().write(true).create_new(true).open(self.output.join(&relative))?;
                file.write_all(bytes)?;
                row["kind"] = json!("data"); row["file"] = json!(relative); row["bytes"] = json!(bytes.len());
                row["definition"] = json!(field.data_definition_name());
                self.records.push(&row)?;
            } else {
                row["kind"] = json!("value");
                row["value"] = field.value().map(leaf).unwrap_or(Value::Null);
                self.records.push(&row)?;
            }
        }
        Ok(())
    }
}

fn safe_relative(path: &str) -> bool {
    let value = path.replace('\\', "/");
    !value.is_empty() && !value.contains(':') && !value.starts_with('/') &&
        Path::new(&value).components().all(|part| matches!(part, Component::Normal(_)))
}

fn run() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let mut options = BTreeMap::new();
    let mut include_geometry = false;
    while let Some(key) = args.next() {
        if key == "--version" { println!("h3-scenario-inspect schema 2; scene schema 1; decoder {DECODER}"); return Ok(()); }
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
    let get = |key: &str| -> Result<PathBuf> {
        PathBuf::from(options.get(key).with_context(|| format!("Required: {key}"))?).canonicalize().map_err(Into::into)
    };
    let root = get("--tags-root")?;
    let input = get("--input")?;
    let output = get("--output")?;
    if !root.is_dir() || !output.is_dir() || !input.is_file() { bail!("Invalid input/output paths"); }
    if !input.starts_with(&root) || output.starts_with(&root) { bail!("Source and output directories must be separate"); }
    if fs::read_dir(&output)?.next().is_some() { bail!("Output directory must be empty"); }
    let relative = input.strip_prefix(&root)?.to_string_lossy().replace('\\', "/");
    if !safe_relative(&relative) { bail!("Unsafe source path"); }
    println!("Reading scenario {relative}");
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
    payload.as_object_mut().unwrap().extend(summary.as_object().unwrap().clone());
    let mut writer = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(output.join("scenario.h3inspect.json"))?);
    serde_json::to_writer(&mut writer, &payload)?; writer.flush()?;
    println!("Inspection complete: {} fields, {} references, {} data blobs", inventory.records.count, inventory.records.references, inventory.blob_count);
    drop(writer);
    // BSP reconstruction has a separate manifest and does not change the inventory's scope.
    scenario_geometry::extract(&tag, &root, &output, &relative, include_geometry, selected.as_ref())?;
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
    #[test] fn unsafe_source_paths_are_rejected() {
        for path in ["../outside.scenario", "C:\\outside", "/absolute", "\\\\server\\tag", ""] { assert!(!safe_relative(path)); }
        assert!(safe_relative("levels\\solo\\040_voi\\040_voi.scenario"));
    }
}
