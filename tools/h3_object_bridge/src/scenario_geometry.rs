//! Detached BSP geometry for the read-only H3 scenario viewer.
use anyhow::{bail, Context, Result};
use blam_tags::{AssFile, AssObjectPayload, TagFieldData, TagFile};
use blam_tags::paths::group_tag_to_extension;
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::{Path, PathBuf};

pub const FORMAT: &str = "foundry.h3-scene";
const MAX_BSPS: usize = 64;

pub fn indices(text: &str) -> Result<Option<BTreeSet<usize>>> {
    if text.trim().is_empty() { return Ok(None); }
    let mut values = BTreeSet::new();
    for token in text.split(',') {
        let token = token.trim();
        if token.is_empty() || !token.bytes().all(|c| c.is_ascii_digit()) { bail!("BSP indices must be comma-separated nonnegative integers"); }
        let value: usize = token.parse()?;
        if value >= MAX_BSPS { bail!("BSP index exceeds supported limit"); }
        if !values.insert(value) { bail!("Repeated BSP index: {value}"); }
    }
    Ok(Some(values))
}

fn relative(name: &str, extension: &str) -> Result<String> {
    let name = name.replace('\\', "/");
    if name.is_empty() || name.contains([':', '\0']) || name.starts_with('/')
        || name.split('/').any(|s| s.is_empty() || s == "." || s == "..")
        || extension.is_empty() || !extension.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_') {
        bail!("Unsafe source reference");
    }
    Ok(format!("{name}.{extension}"))
}

fn source_file(root: &Path, relative: &str) -> Result<PathBuf> {
    let path = root.join(relative).canonicalize().with_context(|| format!("Missing source dependency: {relative}"))?;
    if !path.starts_with(root) || !path.is_file() { bail!("Source dependency escapes tags root"); }
    Ok(path)
}

fn reference(value: Option<TagFieldData>) -> Result<Option<String>> {
    match value {
        Some(TagFieldData::TagReference(r)) => match r.group_tag_and_name {
            Some((group, name)) if !name.is_empty() => {
                let ext = group_tag_to_extension(group).context("Unknown source reference class")?;
                Ok(Some(relative(&name, ext)?))
            }
            _ => Ok(None),
        },
        None => Ok(None),
        _ => bail!("Expected a tag reference"),
    }
}

fn write_json(path: &Path, value: &Value) -> Result<()> {
    let mut writer = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    serde_json::to_writer(&mut writer, value)?;
    writer.flush()?;
    Ok(())
}

fn point(p: blam_tags::math::RealPoint3d) -> [f32; 3] { [p.x, p.y, p.z] }
fn quaternion(q: blam_tags::math::RealQuaternion) -> [f32; 4] { [q.w, q.i, q.j, q.k] }
fn finite(values: &[f32]) -> Result<()> {
    if values.iter().any(|v| !v.is_finite()) { bail!("BSP geometry has nonfinite coordinates or attributes"); }
    Ok(())
}

fn geometry(ass: &AssFile, shaders: &[Option<String>], source: &str, index: usize) -> Result<Value> {
    if ass.materials.len() < shaders.len() { bail!("Decoded material slots do not cover the source material table"); }
    let mut objects = Vec::with_capacity(ass.objects.len());
    for (id, object) in ass.objects.iter().enumerate() {
        let mut row = json!({"id":id, "xref_path":object.xref_filepath, "xref_object":object.xref_objectname});
        match &object.payload {
            AssObjectPayload::Mesh { vertices, triangles } => {
                for v in vertices {
                    finite(&point(v.position))?; finite(&[v.normal.i, v.normal.j, v.normal.k])?;
                    finite(&[v.color.red, v.color.green, v.color.blue])?;
                    for uv in &v.uvs { finite(&point(*uv))?; }
                    for (_, weight) in &v.node_set { finite(&[*weight])?; }
                }
                for triangle in triangles {
                    if triangle.material < -1 || triangle.material >= ass.materials.len() as i32
                        || triangle.v.iter().any(|i| *i as usize >= vertices.len()) {
                        bail!("Decoded BSP triangle has an invalid vertex or material index");
                    }
                }
                row["kind"] = json!("mesh");
                row["vertices"] = json!(vertices.iter().map(|v| json!({
                    "position":point(v.position), "normal":[v.normal.i,v.normal.j,v.normal.k],
                    "color":[v.color.red,v.color.green,v.color.blue], "weights":v.node_set,
                    "uvs":v.uvs.iter().map(|uv|point(*uv)).collect::<Vec<_>>()
                })).collect::<Vec<_>>());
                row["triangles"] = json!(triangles.iter().map(|t|json!({"material":t.material,"vertices":t.v})).collect::<Vec<_>>());
            }
            AssObjectPayload::Sphere { material, radius } => {
                finite(&[*radius])?;
                row["kind"]=json!("sphere_marker"); row["radius"]=json!(radius); row["material"]=json!(material);
            }
            other => {
                row["kind"]=json!("unsupported"); row["source_description"]=json!(format!("{other:?}"));
            }
        }
        objects.push(row);
    }
    let mut placements = Vec::with_capacity(ass.instances.len());
    for inst in &ass.instances {
        finite(&point(inst.local_translation))?; finite(&quaternion(inst.local_rotation))?;
        finite(&point(inst.pivot_translation))?; finite(&quaternion(inst.pivot_rotation))?;
        finite(&[inst.local_scale, inst.pivot_scale])?;
        placements.push(json!({"id":inst.unique_id,"object":inst.object_index,"name":inst.name,
            "parent":inst.parent_id,"inheritance_flag":inst.inheritance_flag,
            "position":point(inst.local_translation),"rotation":quaternion(inst.local_rotation),"scale":inst.local_scale,
            "pivot_position":point(inst.pivot_translation),"pivot_rotation":quaternion(inst.pivot_rotation),
            "pivot_scale":inst.pivot_scale,"bone_groups":inst.bone_groups}));
    }
    Ok(json!({"format":"foundry.h3-bsp", "version":1, "units":"ass_100_per_world_unit",
        "source_tag":source, "bsp_index":index,
        "materials":ass.materials.iter().enumerate().map(|(i,m)|json!({"slot":i,"name":m.name,
            "lightmap_variant":m.lightmap_variant,"ass_metadata":m.bm_strings,
            "source_shader":shaders.get(i).cloned().flatten(),"destination_shader":Value::Null})).collect::<Vec<_>>(),
        "objects":objects,"instances":placements,
        "limitations":["Reconstructed BSP geometry, not original authoring topology or a lossless tag conversion.",
            "The decoder may omit unavailable render sections; decoded counts are not proof of complete source coverage.",
            "ASS object identities can combine identical source definitions. Instance placements remain separate.",
            "Lighting tags, lightmaps, environment-object xrefs and generated pathfinding resources are not loaded."]}))
}

pub fn extract(scenario: &TagFile, root: &Path, output: &Path, source: &str,
               include_geometry: bool, selected: Option<&BTreeSet<usize>>) -> Result<()> {
    let mut entries = Vec::new();
    let mut shader_paths = BTreeSet::new();
    let block = scenario.root().field("structure bsps").and_then(|f| f.as_block());
    let count = block.as_ref().map(|b|b.len()).unwrap_or(0);
    if count > MAX_BSPS { bail!("Scenario exceeds supported BSP count"); }
    if selected.is_some_and(|s| s.iter().any(|i| *i >= count)) { bail!("Requested BSP index is outside the scenario table"); }
    if include_geometry { fs::create_dir(output.join("geometry"))?; }
    if let Some(block) = block {
        for (index, entry) in block.iter().enumerate() {
            let requested = include_geometry && selected.is_none_or(|s|s.contains(&index));
            let mut row = json!({"index":index,"source_tag":Value::Null,"status":if requested {"error"} else {"not_requested"},
                "diagnostics":[]});
            let outcome = catch_unwind(AssertUnwindSafe(|| -> Result<()> {
                let rel = reference(entry.field("structure bsp").and_then(|f|f.value()))?.context("Missing structure BSP reference")?;
                if !rel.ends_with(".scenario_structure_bsp") { bail!("Wrong structure BSP reference class"); }
                row["source_tag"] = json!(rel);
                if !requested { return Ok(()); }
                println!("Decoding BSP {index}: {rel}");
                let tag = TagFile::read(source_file(root,&rel)?)?;
                if tag.header.group_tag.to_be_bytes() != *b"sbsp" { bail!("Expected a structure BSP dependency"); }
                let materials = tag.root().field("materials").and_then(|f|f.as_block()).context("Missing source material table")?;
                let mut shaders = Vec::new();
                for material in materials.iter() {
                    shaders.push(reference(material.field("render method").and_then(|f|f.value()))?);
                }
                let ass = AssFile::from_scenario_structure_bsp(&tag)?;
                let payload = geometry(&ass,&shaders,&rel,index)?;
                let path = format!("geometry/bsp_{index:04}.json");
                write_json(&output.join(&path),&payload)?;
                for shader in shaders.into_iter().flatten() { shader_paths.insert(shader); }
                row["status"]=json!("extracted"); row["geometry"]=json!(path);
                row["decoded_objects"]=json!(ass.objects.len()); row["decoded_instances"]=json!(ass.instances.len());
                row["source_clusters"]=json!(tag.root().field("clusters").and_then(|f|f.as_block()).map(|b|b.len()));
                row["source_instances"]=json!(tag.root().field("instanced geometry instances").and_then(|f|f.as_block()).map(|b|b.len()));
                println!("BSP {index}: {} decoded definitions, {} placements",ass.objects.len(),ass.instances.len());
                Ok(())
            }));
            let error = match outcome { Ok(Ok(()))=>None, Ok(Err(e))=>Some(format!("{e:#}")), Err(_)=>Some("BSP decoder panicked".into()) };
            if let Some(error) = error {
                println!("BSP {index} extraction failed: {error}");
                row["status"]=json!("error");row["diagnostics"]=json!([error]);
            }
            entries.push(row);
        }
    }
    write_json(&output.join("scene.h3scene.json"),&json!({
        "format":FORMAT,"version":1,"game":"halo3_mcc","source_tag":source,
        "units":"ass_100_per_world_unit","inventory":"scenario.h3inspect.json",
        "destination_tags_written":false,"geometry_requested":include_geometry,
        "bsp_entries":entries,"shader_paths":shader_paths,
        "limitations":["Read-only Blender reference. Reach BSP and scenario tags are not generated.",
            "Scenario object placements, lighting dependencies and external scenario resources are inventoried, not imported.",
            "Generated navigation resources are not decoded. Authored hints do not simulate Halo AI."]
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn selection_is_explicit() {
        assert_eq!(indices("2,0").unwrap().unwrap(),BTreeSet::from([0,2]));
        assert!(indices("").unwrap().is_none());
        for text in ["-1","0,","0,0","64","1.0"] { assert!(indices(text).is_err()); }
    }
    #[test] fn typed_paths_keep_literal_dots() {
        assert_eq!(relative("levels\\a.v1","scenario_structure_bsp").unwrap(),"levels/a.v1.scenario_structure_bsp");
        for name in ["../a","a//b","/a","C:\\a", "a\0b"] { assert!(relative(name,"shader").is_err()); }
    }
    #[test] fn material_slots_do_not_gain_reach_paths() {
        let mut ass=AssFile::default();
        ass.materials.push(blam_tags::ass::AssMaterial{name:"same".into(),lightmap_variant:String::new(),bm_strings:vec![]});
        let value=geometry(&ass,&[Some("one/same.shader".into())],"a.scenario_structure_bsp",0).unwrap();
        assert_eq!(value["materials"][0]["source_shader"],"one/same.shader");
        assert!(value["materials"][0]["destination_shader"].is_null());
    }
    #[test] fn material_table_mismatch_is_rejected() {
        assert!(geometry(&AssFile::default(),&[None],"a.scenario_structure_bsp",0).is_err());
    }
    #[test] fn nonfinite_geometry_is_rejected() { assert!(finite(&[f32::NAN]).is_err()); }
    #[test] fn instance_identity_and_signed_scale_are_retained() {
        let mut ass=AssFile::default();
        ass.instances.push(blam_tags::ass::AssInstance{unique_id:7,parent_id:-1,object_index:-1,local_scale:-2.0,..Default::default()});
        let value=geometry(&ass,&[],"a.scenario_structure_bsp",3).unwrap();
        assert_eq!(value["instances"][0]["id"],7);
        assert_eq!(value["instances"][0]["scale"],-2.0);
        assert_eq!(value["bsp_index"],3);
        assert_eq!(value["units"],"ass_100_per_world_unit");
    }
}
