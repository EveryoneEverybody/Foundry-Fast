//! Read-only lighting input tables; excludes compiled mesh/resource payloads.
use anyhow::{Context, Result, ensure};
use blam_tags::{TagFile, TagStruct, TagFieldData as D};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

fn leaves(row: TagStruct<'_>) -> Value {
    let fields = row.fields().filter(|f| !matches!(f.type_name(),
        "data" | "custom" | "api interop" | "pageable resource" | "block" | "struct" | "array" | "pad" | "skip" | "explanation" | "terminator"))
        .filter_map(|f| f.value().map(|v| {
            let value = match &v {
                D::Real(v) | D::Angle(v) | D::RealFraction(v) | D::RealSlider(v) => json!(v),
                D::ShortInteger(v) => json!(v), D::LongInteger(v) => json!(v), D::CharInteger(v) => json!(v),
                D::ShortEnum { value, name } => json!({"value": value, "name": name}),
                D::CharEnum { value, name } => json!({"value": value, "name": name}),
                D::WordFlags { value, names } => json!({"value": value, "names": names}),
                D::LongFlags { value, names } => json!({"value": value, "names": names}),
                D::TagReference(r) => json!(r.group_tag_and_name),
                D::String(s) | D::LongString(s) => json!(s),
                _ => json!(format!("{v:?}")),
            };
            (f.name().to_owned(), json!({"type": f.type_name(), "value": value}))
        })).collect::<serde_json::Map<_,_>>();
    Value::Object(fields)
}

fn block(row: TagStruct<'_>, name: &str) -> Result<Value> {
    let b = row.field(name).and_then(|f| f.as_block()).with_context(|| format!("Missing {name}"))?;
    ensure!(b.len() <= 8192, "Oversized diagnostic table");
    Ok(Value::Array(b.iter().map(leaves).collect()))
}

fn main() -> Result<()> {
    let path = std::env::args_os().nth(1).context("Expected tag path")?;
    let tag = TagFile::read(&path)?;
    let root = tag.root();
    let mut rows = json!({"root": leaves(root)});
    let text = path.to_string_lossy();
    let blocks: &[&str] = if text.ends_with(".scenario_structure_lighting_info") {
        &["generic light definitions", "generic light instances", "material info"]
    } else if text.ends_with(".scenario") { &["structure bsps", "skies"]
    } else if text.ends_with(".scenario_structure_bsp") { &["materials"]
    } else if text.ends_with(".bitmap") { &["bitmaps"]
    } else if text.ends_with(".scenario_lightmap_bsp_data") { &["clusters", "instances"]
    } else if text.ends_with(".scenario_faux_data") {
        let bsps = root.field("global BSP data").and_then(|f| f.as_block()).context("Missing Faux BSP data")?;
        let data = bsps.iter().map(|b| Ok(json!({"fields": leaves(b), "materials": block(b, "materials")?})))
            .collect::<Result<Vec<_>>>()?;
        rows["global BSP data"] = json!(data);
        &[]
    } else { anyhow::bail!("Unsupported lighting evidence tag type"); };
    for name in blocks { rows[*name] = block(root, name)?; }
    serde_json::to_writer_pretty(std::io::stdout(), &json!({
        "format": "foundry.lighting-input-rows", "version": 1, "path": text,
        "sha256": format!("{:x}", Sha256::digest(std::fs::read(&path)?)),
        "decoder": "blam-tags@5d0509fb75eadb96ac7774542ca0b2c10aed7b00", "rows": rows,
        "limitations": "Read-only schema fields; no inference of bake participation or native BSP point membership"
    }))?;
    Ok(())
}
