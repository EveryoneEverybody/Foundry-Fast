//! Read-only H3 editing-kit object extraction for Foundry. No tag writes.
use anyhow::{bail, Context, Result};
use blam_tags::{JmsFile, TagFieldData, TagFile, TagStruct};
use blam_tags::math::{RealPoint3d, RealQuaternion};
use blam_tags::paths::{group_tag_to_extension, tag_ref_path};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::path::{Component, Path, PathBuf};

const FORMAT: &str = "foundry.h3-object";
const DECODER: &str = "5d0509fb75eadb96ac7774542ca0b2c10aed7b00";
fn pos(p: RealPoint3d) -> [f32; 3] { [p.x, p.y, p.z] }
fn quat(q: RealQuaternion) -> [f32; 4] { [q.w, q.i, q.j, q.k] }

fn resolve(root: &Path, reference: &str, extension: &str) -> Result<PathBuf> {
    let normalized = reference.replace('\\', "/");
    if normalized.contains(':') || normalized.starts_with('/') {
        bail!("Absolute tag reference rejected: {reference}");
    }
    let relative = Path::new(&normalized);
    if relative.components().any(|c| !matches!(c, Component::Normal(_))) {
        bail!("Unsafe tag reference: {reference}");
    }
    // Tag references are extensionless. Literal dots in tag names are retained.
    let path = root.join(format!("{normalized}.{extension}")).canonicalize()
        .with_context(|| format!("Missing dependency: {reference}.{extension}"))?;
    if !path.starts_with(root) { bail!("Dependency escapes tags directory: {reference}"); }
    Ok(path)
}

fn reference(tag: &TagFile, names: &[&str]) -> Option<String> {
    names.iter().find_map(|name| tag_ref_path(&tag.root(), name))
}

fn block<'a>(node: TagStruct<'a>, name: &str) -> Vec<TagStruct<'a>> {
    node.field(name).and_then(|f| f.as_block()).map(|b| b.iter().collect()).unwrap_or_default()
}

fn variant_metadata(model: &TagFile) -> Vec<Value> {
    block(model.root(), "variants").iter().map(|v| json!({
        "name":v.read_string_id("name").unwrap_or_default(),
        "instance_group":v.read_int_any("instance group"),
        "regions":block(*v,"regions").iter().map(|r| json!({
            "name":r.read_string_id("region name").unwrap_or_default(),
            "parent_variant":r.read_int_any("parent variant").unwrap_or(-1),
            "runtime_region_index":r.read_int_any("runtime region index"),
            "permutations":block(*r,"permutations").iter().map(|p| json!({
                "name":p.read_string_id("permutation name").unwrap_or_default(),
                "flags":p.read_int_any("flags"), "probability":p.read_real("probability"),
                "probability_bits":p.read_real("probability").map(f32::to_bits),
                "runtime_permutation_index":p.read_int_any("runtime permutation index"),
                "states":block(*p,"states").iter().map(|s| json!({
                    "name":s.read_string_id("permutation name"),"state":s.read_int_any("state"),
                    "state_name":s.read_enum_name("state"),"property_flags":s.read_int_any("property flags"),
                    "initial_probability":s.read_real("initial probability"),
                    "looping_effect":tag_ref_path(s,"looping effect"),
                    "looping_effect_marker":s.read_string_id("looping effect marker name")
                })).collect::<Vec<_>>()
            })).collect::<Vec<_>>()
        })).collect::<Vec<_>>(),
        "children":block(*v,"objects").iter().map(|o| json!({
            "object":tag_ref_path(o,"child object"),
            "parent_marker":o.read_string_id("parent marker"),
            "child_marker":o.read_string_id("child marker"),
            "source_fields":o.fields().filter_map(|f| f.value().map(|value| json!({"name":f.name(),"decoder_value":format!("{value:?}")}))).collect::<Vec<_>>()
        })).collect::<Vec<_>>()
    })).collect()
}

fn shader_paths(tag: &TagFile) -> Vec<String> {
    let root = tag.root();
    let count = root.field("materials").and_then(|f| f.as_block()).map(|b| b.len()).unwrap_or(0);
    let mut paths = Vec::new();
    for i in 0..count {
        let path = format!("materials[{i}]/render method");
        if let Some(TagFieldData::TagReference(r)) = root.field_path(&path).and_then(|f| f.value()) {
            if let Some((group, name)) = r.group_tag_and_name {
                if !name.is_empty() {
                    if let Some(ext) = group_tag_to_extension(group) {
                        paths.push(format!("{}.{}", name.replace('\\', "/"), ext));
                    }
                }
            }
        }
    }
    paths.sort();
    paths.dedup();
    paths
}

fn mesh_json(j: &JmsFile) -> Value {
    json!({
        "nodes": j.nodes.iter().map(|n| json!({"name": n.name, "parent": n.parent,
            "position": pos(n.translation), "rotation": quat(n.rotation)})).collect::<Vec<_>>(),
        "materials": j.materials.iter().map(|m| json!({"name": m.name, "label": m.material_name})).collect::<Vec<_>>(),
        "markers": j.markers.iter().map(|m| json!({"name": m.name, "node": m.node_index,
            "position": pos(m.translation), "rotation": quat(m.rotation), "radius": m.radius})).collect::<Vec<_>>(),
        "vertices": j.vertices.iter().map(|v| json!({"position": pos(v.position),
            "normal": [v.normal.i, v.normal.j, v.normal.k], "weights": v.node_sets,
            "uvs": v.uvs.iter().map(|uv| [uv.x, uv.y]).collect::<Vec<_>>(),
            "color": v.color.map(pos)})).collect::<Vec<_>>(),
        "triangles": j.triangles.iter().map(|t| json!({"material": t.material, "vertices": t.v})).collect::<Vec<_>>()
    })
}

fn physics_json(j: &JmsFile) -> Value {
    let mut shapes = Vec::new();
    for s in &j.spheres {
        shapes.push(json!({"kind":"sphere", "name":s.name, "node":s.parent, "material":s.material,
            "position":pos(s.translation), "rotation":quat(s.rotation), "radius":s.radius}));
    }
    for s in &j.boxes {
        shapes.push(json!({"kind":"box", "name":s.name, "node":s.parent, "material":s.material,
            "position":pos(s.translation), "rotation":quat(s.rotation), "size":[s.width,s.length,s.height]}));
    }
    for s in &j.convex_shapes {
        shapes.push(json!({"kind":"convex", "name":s.name, "node":s.parent, "material":s.material,
            "position":pos(s.translation), "rotation":quat(s.rotation),
            "vertices":s.vertices.iter().map(|p| pos(*p)).collect::<Vec<_>>()}));
    }
    json!({"shape_space":"node_local",
        "nodes": j.nodes.iter().map(|n| json!({"name": n.name, "parent": n.parent,
            "position": pos(n.translation), "rotation": quat(n.rotation)})).collect::<Vec<_>>(),
        "shapes":shapes, "capsules_in_source":j.capsules.len(),
        "ragdolls_in_source":j.ragdolls.len(), "hinges_in_source":j.hinges.len()})
}

fn write_source(dir: &Path, name: &str, j: &JmsFile) -> Result<()> {
    let file = OpenOptions::new().write(true).create_new(true).open(dir.join(name))?;
    let mut writer = BufWriter::new(file);
    j.write(&mut writer, 8213)?;
    writer.flush()?;
    Ok(())
}

fn run() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let mut values = BTreeMap::new();
    let (mut collision, mut physics) = (false, false);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--collision" => collision = true,
            "--physics" => physics = true,
            "--tags-root" | "--input" | "--output" => {
                let value = args.next().context("Missing option value")?;
                values.insert(arg, value);
            }
            "--version" => { println!("h3-object-bridge 0.1.0; schema 1; decoder {DECODER}"); return Ok(()); }
            _ => bail!("Unknown option: {arg}"),
        }
    }
    let get = |key: &str| -> Result<PathBuf> {
        Ok(PathBuf::from(values.get(key).with_context(|| format!("Required: {key}"))?))
    };
    let root = get("--tags-root")?.canonicalize().context("Invalid tags directory")?;
    let input = get("--input")?.canonicalize().context("Invalid source tag")?;
    let output = get("--output")?.canonicalize().context("Output directory must already exist")?;
    if !root.is_dir() || !output.is_dir() { bail!("Tags root and output must be directories"); }
    if !input.starts_with(&root) { bail!("Source tag is outside the tags directory"); }
    if output.starts_with(&root) { bail!("Output must be outside the source tags directory"); }
    if output.join("asset.h3asset.json").exists() { bail!("Output already contains an extraction"); }
    println!("Reading {}", input.display());
    let object = TagFile::read(&input).context("Read source tag")?;
    let group = object.header.group_tag.to_be_bytes();
    let model_path = if &group == b"hlmt" || &group == b"mode" {
        input.clone()
    } else {
        if ![b"bipd", b"bloc", b"scen", b"vehi", b"weap", b"mach", b"ctrl", b"eqip", b"gint", b"efsc", b"ssce", b"term"].contains(&&group) {
            bail!("Unsupported object group: {}", String::from_utf8_lossy(&group));
        }
        let model_ref = reference(&object, &["object/model", "unit/object/model", "item/object/model",
            "device/object/model", "model"]).context("Object has no supported model reference")?;
        resolve(&root, &model_ref, "model")?
    };
    let model = TagFile::read(&model_path).context("Read model")?;
    let direct_render = model.header.group_tag.to_be_bytes() == *b"mode";
    if !direct_render && model.header.group_tag.to_be_bytes() != *b"hlmt" { bail!("Expected model tag"); }
    let render_path = if direct_render { model_path.clone() } else {
        resolve(&root, &reference(&model, &["render model"]).context("No render model reference")?, "render_model")?
    };
    println!("Decoding render model");
    let render_tag = TagFile::read(&render_path)?;
    if render_tag.header.group_tag.to_be_bytes() != *b"mode" { bail!("Expected render_model dependency"); }
    let render = JmsFile::from_render_model(&render_tag).context("Decode render geometry")?;
    if render.vertices.is_empty() || render.triangles.is_empty() { bail!("Render model has no decoded triangles"); }
    let mut warnings = vec![
        "Experimental reconstruction, not a lossless object-tag conversion.".to_string(),
        "All decoded permutations are retained in the source payload. Scenario previews may select explicit variant permutations; child attachments are not applied.".to_string(),
        "Animations, gameplay fields, shader conversion, UVW W coordinates and marker permutation filters are not imported in this pass.".to_string(),
        "Render topology is reconstructed by the JMS decoder. Original authoring topology is not guaranteed.".to_string(),
    ];
    let mut dependencies = BTreeMap::new();
    let relative = |path: &Path| path.strip_prefix(&root).unwrap().to_string_lossy().replace('\\', "/");
    dependencies.insert("model", relative(&model_path));
    dependencies.insert("render_model", relative(&render_path));
    let mut collision_data = Value::Null;
    let mut physics_data = Value::Null;
    write_source(&output, "render.jms", &render)?;
    for (enabled, field_names, ext) in [
        (collision, vec!["collision model"], "collision_model"),
        (physics, vec!["physics_model", "physics model"], "physics_model"),
    ] {
        if !enabled || direct_render { continue; }
        if let Some(reference) = reference(&model, &field_names) {
            let path = resolve(&root, &reference, ext)?;
            dependencies.insert(ext, relative(&path));
            println!("Decoding {ext}");
            let tag = TagFile::read(&path)?;
            if ext == "collision_model" {
                if tag.header.group_tag.to_be_bytes() != *b"coll" { bail!("Expected collision_model dependency"); }
                let jms = JmsFile::from_collision_model_with_skeleton(&tag, &render.nodes)?;
                write_source(&output, "collision.jms", &jms)?;
                collision_data = mesh_json(&jms);
                warnings.push("Collision geometry is reconstructed; special surface flags and damage behavior require comparison with the source tag.".into());
            } else {
                if tag.header.group_tag.to_be_bytes() != *b"phmo" { bail!("Expected physics_model dependency"); }
                let jms = JmsFile::from_physics_model_with_skeleton(&tag, &render.nodes)?;
                write_source(&output, "physics.jms", &jms)?;
                physics_data = physics_json(&jms);
                warnings.push(format!("Physics reference shapes only. Mass, inertia, body regions and simulation constraints are not mapped. Capsules: {}; ragdolls: {}; hinges: {} retained in physics.jms, not instantiated in Blender.", jms.capsules.len(), jms.ragdolls.len(), jms.hinges.len()));
            }
        } else {
            warnings.push(format!("No {ext} reference on source model"));
        }
    }
    let payload = json!({"format": FORMAT, "version":1, "game":"halo3_mcc", "units":"jms_x100",
        "decoder":DECODER, "name":input.file_stem().unwrap().to_string_lossy(),
        "source_tag":relative(&input), "dependencies":dependencies,
        "variants":variant_metadata(&model),
        "default_variant":["object", "unit/object", "item/object", "device/object"].iter()
            .find_map(|p| object.root().descend(p).and_then(|s| s.read_string_id("default model variant"))).unwrap_or_default(),
        "shader_paths":shader_paths(&render_tag), "render":mesh_json(&render),
        "collision":collision_data, "physics":physics_data, "warnings":warnings});
    let file = OpenOptions::new().write(true).create_new(true).open(output.join("asset.h3asset.json"))?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer(&mut writer, &payload)?;
    writer.flush()?;
    println!("Extraction complete: {} vertices, {} triangles, {} nodes", render.vertices.len(), render.triangles.len(), render.nodes.len());
    Ok(())
}

fn main() {
    if let Err(error) = run() { eprintln!("{error:#}"); std::process::exit(1); }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unsafe_references() {
        for path in ["../outside", "a/../../outside", "C:\\outside", "/outside", "\\\\host\\share"] {
            assert!(resolve(Path::new("."), path, "model").is_err());
        }
    }
    #[test]
    fn empty_mesh_has_stable_schema() {
        let value = mesh_json(&JmsFile::default());
        assert!(value["nodes"].as_array().unwrap().is_empty());
        assert!(value["vertices"].as_array().unwrap().is_empty());
        assert!(value["triangles"].as_array().unwrap().is_empty());
    }
    #[test]
    fn physics_space_and_node_names_are_explicit() {
        let mut jms = JmsFile::default();
        jms.nodes.push(blam_tags::jms::JmsNode {
            name:"b_panel".into(), parent:-1,
            rotation:RealQuaternion { w:1.0, i:0.0, j:0.0, k:0.0 },
            translation:RealPoint3d { x:150.0, y:200.0, z:0.0 },
        });
        let value = physics_json(&jms);
        assert_eq!(value["shape_space"], "node_local");
        assert_eq!(value["nodes"][0]["name"], "b_panel");
    }
    #[test]
    fn quaternion_order_is_explicit() {
        assert_eq!(quat(RealQuaternion { w:4.0, i:1.0, j:2.0, k:3.0 }), [4.0,1.0,2.0,3.0]);
    }
}
