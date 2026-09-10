//! Compare the actual captured shader files, without resolving through a kit.
use anyhow::{Result, ensure};
use blam_tags::{TagFile, TagStruct};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

fn walk(row: TagStruct<'_>, path: &str, out: &mut BTreeMap<String, Value>, depth: usize) -> Result<()> {
    ensure!(depth < 32 && out.len() < 20000, "Shader diagnostic size limit");
    for (ordinal, field) in row.fields().enumerate() {
        let key = format!("{path}/{ordinal}:{}", field.name());
        if let Some(s) = field.as_struct() { walk(s, &key, out, depth+1)?; }
        else if let Some(b) = field.as_block() {
            out.insert(format!("{key}/count"), json!(b.len()));
            for (i,s) in b.iter().enumerate() { walk(s, &format!("{key}[{i}]"), out, depth+1)?; }
        } else if let Some(a) = field.as_array() {
            for (i,s) in a.iter().enumerate() { walk(s, &format!("{key}[{i}]"), out, depth+1)?; }
        } else if let Some(bytes) = field.as_data() {
            out.insert(key, json!({"bytes": bytes.len(), "sha256": format!("{:x}", Sha256::digest(bytes)),
                "constant": field.as_function().and_then(|f| f.as_constant())}));
        } else if !matches!(field.type_name(), "pad" | "skip" | "explanation" | "pageable resource" | "api interop") {
            if let Some(v) = field.value() { out.insert(key, json!(format!("{v:?}"))); }
        }
    }
    Ok(())
}

fn main() -> Result<()> {
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    ensure!(args.len()==2 && args.iter().all(|a| a.to_string_lossy().ends_with(".shader")), "Expected two captured .shader files");
    let mut tables = Vec::new();
    for path in &args {
        let tag = TagFile::read(path)?;
        let mut table = BTreeMap::new(); walk(tag.root(), "", &mut table, 0)?; tables.push(table);
    }
    let keys = tables[0].keys().chain(tables[1].keys()).collect::<std::collections::BTreeSet<_>>();
    let changes = keys.into_iter().filter(|k| tables[0].get(*k) != tables[1].get(*k)).map(|k|
        json!({"field": k, "before": tables[0].get(k), "after": tables[1].get(k)})).collect::<Vec<_>>();
    serde_json::to_writer_pretty(std::io::stdout(), &json!({
        "before_sha256": format!("{:x}", Sha256::digest(std::fs::read(&args[0])?)),
        "after_sha256": format!("{:x}", Sha256::digest(std::fs::read(&args[1])?)), "changes": changes,
        "interpretation": "Read-only leaf field changes in captured files; function blobs retained by hash."
    }))?;
    Ok(())
}
