//! Source-only descriptions for non-render tags. All files are opened read-only.
use anyhow::{bail, Result};
use blam_tags::{TagFile, TagStruct};
use serde_json::{json, Value};
use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::path::Path;
use crate::source_values::leaf;

fn walk(node: TagStruct<'_>, parent: &str, rows: &mut Vec<Value>, depth: usize) -> Result<()> {
    if depth > 96 || rows.len() > 100_000 { bail!("Semantic source inventory exceeds its budget"); }
    for field in node.fields() {
        let address = format!("{parent}/{}#{}", field.clean_name(), field.ordinal());
        let mut row = json!({"address":address, "name":field.clean_name(), "raw_name":field.name(), "type":field.type_name()});
        if let Some(nested) = field.as_struct() {
            row["kind"] = json!("struct"); rows.push(row); walk(nested, &address, rows, depth+1)?;
        } else if let Some(block) = field.as_block() {
            row["kind"] = json!("block"); row["count"] = json!(block.len()); rows.push(row);
            for (i, child) in block.iter().enumerate() { walk(child, &format!("{address}[{i}]"), rows, depth+1)?; }
        } else if let Some(array) = field.as_array() {
            row["kind"] = json!("array"); rows.push(row);
            for (i, child) in array.iter().enumerate() { walk(child, &format!("{address}[{i}]"), rows, depth+1)?; }
        } else if let Some(bytes) = field.as_data() {
            if bytes.len() > 1024*1024 { bail!("Semantic data exceeds its byte budget"); }
            row["kind"] = json!("data"); row["bytes"] = json!(bytes); rows.push(row);
        } else if let Some(resource) = field.as_resource() {
            row["kind"] = json!("resource_header_only"); rows.push(row);
            if let Some(header) = resource.as_struct() { walk(header, &address, rows, depth+1)?; }
        } else {
            row["kind"] = json!("value"); row["value"] = field.value().map(leaf).unwrap_or(Value::Null); rows.push(row);
        }
    }
    Ok(())
}

pub fn write(tag: &TagFile, source: &str, output: &Path, reason: &str) -> Result<()> {
    let mut rows = Vec::new(); walk(tag.root(), "", &mut rows, 0)?;
    let data = json!({"format":"foundry.h3-semantic", "version":1, "game":"halo3_mcc", "source_tag":source,
        "group":String::from_utf8_lossy(&tag.header.group_tag.to_be_bytes()), "reason":reason,
        "records":rows, "destination_tags_written":false});
    let mut file = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(output.join("source.h3semantic.json"))?);
    serde_json::to_writer(&mut file, &data)?; file.flush()?;
    println!("Semantic source retained: {source}: {reason}");
    Ok(())
}
