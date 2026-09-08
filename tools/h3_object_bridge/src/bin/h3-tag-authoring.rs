//! Bounded, read-only object/dependency authoring metadata. No resource copying.
use anyhow::{Context, Result, bail, ensure};
use blam_tags::{TagFile, TagStruct, TagFieldData};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::BufWriter;
use std::path::PathBuf;

#[path = "../source_values.rs"]
mod source_values;

fn fields(node: TagStruct<'_>, count: &mut usize, depth: usize) -> Result<Vec<Value>> {
    ensure!(depth < 48, "Object authoring nesting limit");
    let mut result = Vec::new();
    for field in node.fields() {
        if matches!(field.type_name(), "pad"|"skip"|"explanation"|"custom"|"terminator"|"api interop") { continue; }
        *count += 1;
        ensure!(*count <= 500_000, "Object authoring field budget");
        let mut row = json!({"name":field.clean_name(), "raw_name":field.name(),
            "ordinal":field.ordinal(), "type":field.type_name()});
        if let Some(child) = field.as_struct() {
            row["fields"] = json!(fields(child,count,depth+1)?);
        } else if let Some(block) = field.as_block() {
            row["count"] = json!(block.len());
            row["elements"] = json!(block.iter().enumerate().map(|(i,child)|
                Ok(json!({"source_index":i,"fields":fields(child,count,depth+1)?})))
                .collect::<Result<Vec<Value>>>()?);
        } else if let Some(array) = field.as_array() {
            row["elements"] = json!(array.iter().enumerate().map(|(i,child)|
                Ok(json!({"source_index":i,"fields":fields(child,count,depth+1)?})))
                .collect::<Result<Vec<Value>>>()?);
        } else if field.as_resource().is_some() {
            row["disposition"] = json!("COMPILED_RESOURCE_NOT_COPIED");
        } else if let Some(bytes) = field.as_data() {
            row["bytes"] = json!(bytes.len());
            row["sha256"] = json!(format!("{:x}",Sha256::digest(bytes)));
            row["constant"] = json!(field.as_function().and_then(|f|f.as_constant()));
            row["disposition"] = json!("SOURCE_DATA_HASH_ONLY_NOT_COPIED");
        } else {
            row["value"] = field.value().map(|v| match v {
                TagFieldData::RealBounds(b) => source_values::floats(&[b.lower,b.upper]),
                TagFieldData::RealPlane3d(p) => source_values::floats(&[p.i,p.j,p.k,p.d]),
                other => source_values::leaf(other),
            }).unwrap_or(Value::Null);
        }
        result.push(row);
    }
    Ok(result)
}

fn main() -> Result<()> {
    let args = std::env::args_os().skip(1).map(PathBuf::from).collect::<Vec<_>>();
    ensure!(args.len()==3, "Usage: h3-tag-authoring <tags-root> <source-tag-file> <new-output-json>");
    let root=args[0].canonicalize()?;
    let input=args[1].canonicalize()?;
    let output_parent=args[2].parent().context("Output needs a parent directory")?.canonicalize()?;
    ensure!(root.is_dir() && input.is_file() && input.starts_with(&root), "Source must be inside tags root");
    ensure!(!output_parent.starts_with(&root) && !args[2].exists(), "Output must be new and outside source tags");
    let tag=TagFile::read(&input)?;
    let group=tag.header.group_tag.to_be_bytes();
    if ![b"scen",b"bloc",b"mach",b"ctrl",b"hlmt",b"mode",b"coll",b"phmo",b"jmad",b"ssce",b"efsc",b"ligh"].contains(&&group) {
        bail!("Unsupported bounded object dependency group");
    }
    let mut count=0;
    let metadata=fields(tag.root(),&mut count,0)?;
    let result=json!({"format":"foundry.h3-object-authoring","version":1,
        "source_tag":input.strip_prefix(&root)?.to_string_lossy().replace('\\',"/"),
        "source_group":String::from_utf8_lossy(&group),
        "source_sha256":format!("{:x}",Sha256::digest(fs::read(&input)?)),
        "decoder":"5d0509fb75eadb96ac7774542ca0b2c10aed7b00",
        "field_count":count,"fields":metadata,
        "policy":"Source authoring fields and data hashes only; native resources require Reach authoring and Tool"});
    let writer=BufWriter::new(OpenOptions::new().write(true).create_new(true).open(&args[2])?);
    serde_json::to_writer(writer,&result)?;
    println!("Read {count} object authoring fields");
    Ok(())
}
