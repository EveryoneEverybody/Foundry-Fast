//! Read H3 animation tags into temporary source files. Never write tags.
use anyhow::{bail, Context, Result};
use blam_tags::animation::{NodeTransform, Pose, SizeLayout, Skeleton, SkeletonNode};
use blam_tags::extract::animation::{build_defaults, jma_kind_for};
use blam_tags::{Animation, TagFile, TagStruct};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Component, Path, PathBuf};

const DECODER: &str = "23f5252a60d6ceb1ee22bd152679de93c66bc3b9";
const FORMAT: &str = "foundry.h3-animation";

fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes { write!(s, "{b:02x}").unwrap(); }
    s
}

fn safe_relative(reference: &str) -> Result<String> {
    let s = reference.replace('\\', "/");
    if s.is_empty() || s.contains(':') || s.starts_with('/') || s.split('/').any(|c| c.is_empty() || c == "." || c == "..") {
        bail!("Unsafe source reference: {reference}");
    }
    if Path::new(&s).components().any(|c| !matches!(c, Component::Normal(_))) {
        bail!("Unsafe source reference: {reference}");
    }
    Ok(s)
}

fn dependency(root: &Path, reference: &str, extension: &str) -> Result<PathBuf> {
    let s = safe_relative(reference)?;
    let p = root.join(format!("{s}.{extension}")).canonicalize()
        .with_context(|| format!("Missing source dependency: {s}.{extension}"))?;
    if !p.starts_with(root) { bail!("Source dependency escapes tags directory"); }
    Ok(p)
}

fn read_group(path: &Path, group: &[u8; 4]) -> Result<TagFile> {
    let tag = TagFile::read(path).with_context(|| format!("Read {}", path.display()))?;
    if &tag.header.group_tag.to_be_bytes() != group { bail!("Unexpected tag class: {}", path.display()); }
    Ok(tag)
}

// Keep authored field values and bytes independent of playback support.
fn snapshot(s: TagStruct<'_>, depth: usize) -> Value {
    if depth > 16 { return json!({"raw_hex":hex(s.raw()), "status":"depth_limit"}); }
    let fields: Vec<Value> = s.fields().map(|f| {
        let name = f.name();
        let value = if let Some(child) = f.as_struct() {
            snapshot(child, depth + 1)
        } else if let Some(block) = f.as_block() {
            json!((0..block.len()).filter_map(|i| block.element(i)).map(|e| snapshot(e, depth + 1)).collect::<Vec<_>>())
        } else if let Some(bytes) = f.as_data() {
            json!({"data_hex":hex(bytes)})
        } else if let Some(v) = s.read_int_any(name) {
            json!({"integer":v.to_string(), "decoded":format!("{:?}", f.value())})
        } else if let Some(v) = s.read_real(name) {
            json!({"real":v, "bits":v.to_bits()})
        } else if let Some(v) = s.read_string_id(name) {
            json!(v)
        } else if let Some(v) = s.read_tag_ref_path(name) {
            json!({"source_tag":v})
        } else {
            json!({"decoded":format!("{:?}", f.value())})
        };
        json!({"name":name, "value":value})
    }).collect();
    json!({"struct":s.name(), "raw_hex":hex(s.raw()), "fields":fields})
}

fn supported(animation_type: Option<&str>, movement: Option<&str>, world: bool) -> bool {
    !world && animation_type == Some("base") && matches!(movement, Some("none" | "dx,dy" | "dx,dy,dyaw" | "dx,dy,dz,dyaw"))
}

fn validate_skeleton(s: &Skeleton) -> Result<()> {
    if s.nodes.is_empty() || s.nodes.len() > 255 { bail!("Invalid source skeleton size"); }
    let mut names = BTreeSet::new();
    for (i, n) in s.nodes.iter().enumerate() {
        if n.name.is_empty() || n.name.contains(['\n', '\r']) || !names.insert(&n.name) { bail!("Invalid or duplicate source node name"); }
        if (i == 0 && n.parent != -1) || (i > 0 && (n.parent < 0 || n.parent as usize >= i)) {
            bail!("Expected one root and parent-before-child source node order");
        }
    }
    Ok(())
}

fn writer(path: &Path) -> Result<BufWriter<std::fs::File>> {
    Ok(BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?))
}

fn transform_json(t: &NodeTransform) -> Value {
    json!({"position":[t.translation.x, t.translation.y, t.translation.z],
        "rotation":[t.rotation.w, t.rotation.i, t.rotation.j, t.rotation.k], "scale":t.scale})
}

fn run() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let mut values = BTreeMap::new();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--version" => { println!("h3-animation-bridge 0.1.0; schema 1; decoder {DECODER}"); return Ok(()); }
            "--tags-root" | "--input" | "--output" | "--animation" => {
                if values.contains_key(&arg) { bail!("Duplicate option: {arg}"); }
                values.insert(arg, args.next().context("Missing option value")?);
            }
            _ => bail!("Unknown option: {arg}"),
        }
    }
    let get = |key: &str| -> Result<PathBuf> { Ok(PathBuf::from(values.get(key).with_context(|| format!("Required: {key}"))?).canonicalize()?) };
    let root = get("--tags-root")?;
    let input = get("--input")?;
    let output = get("--output")?;
    if !root.is_dir() || !output.is_dir() || !input.is_file() { bail!("Invalid source or output path"); }
    if !input.starts_with(&root) || output.starts_with(&root) { bail!("Source must be inside tags; output must be outside tags"); }
    // Refuse an existing extraction before creating any files.
    if fs::read_dir(&output)?.next().is_some() { bail!("Output directory must be empty"); }
    let relative = |p: &Path| p.strip_prefix(&root).unwrap().to_string_lossy().replace('\\', "/");
    let source = TagFile::read(&input)?;
    let group = source.header.group_tag.to_be_bytes();
    let model_path = match &group {
        b"hlmt" => Some(input.clone()),
        b"jmad" => None,
        b"bipd" | b"bloc" | b"scen" | b"vehi" | b"weap" | b"mach" | b"ctrl" | b"eqip" | b"gint" => {
            let r = ["unit/object/model", "object/model", "item/object/model", "device/object/model"]
                .into_iter().find_map(|p| blam_tags::paths::tag_ref_path(&source.root(), p))
                .context("No source model reference")?;
            Some(dependency(&root, &r, "model")?)
        }
        _ => bail!("Expected H3 model, object, giant, or model_animation_graph"),
    };
    let model = model_path.as_ref().map(|p| read_group(p, b"hlmt")).transpose()?;
    let graph_path = if let Some(m) = &model {
        dependency(&root, &m.root().read_tag_ref_path("animation").context("Model has no animation graph")?, "model_animation_graph")?
    } else { input.clone() };
    let render_path = model.as_ref().and_then(|m| m.root().read_tag_ref_path("render model"))
        .map(|r| dependency(&root, &r, "render_model")).transpose()?;
    let render = render_path.as_ref().map(|p| read_group(p, b"mode")).transpose()?;
    let tag = read_group(&graph_path, b"jmad")?;
    let animations = Animation::new(&tag)?;
    let skeleton = Skeleton::from_tag(&tag);
    validate_skeleton(&skeleton)?;
    if animations.iter().any(|a| a.data_sizes.as_ref().is_some_and(|d| d.layout() != SizeLayout::H3)) {
        bail!("This bridge accepts H3/ODST-layout animation resources only");
    }
    // Require a real default transform for every node, not the decoder's identity fallback.
    for node in &skeleton.nodes {
        let has = |s: TagStruct<'_>, block_name: &str, field: &str| -> bool {
            s.field(block_name).and_then(|f| f.as_block()).is_some_and(|b|
                (0..b.len()).filter_map(|i| b.element(i)).any(|e|
                    e.read_string_id(field).as_deref() == Some(&node.name)
                    && e.field("default translation").is_some() && e.field("default rotation").is_some()))
        };
        if !render.as_ref().is_some_and(|r| has(r.root(), "nodes", "name"))
            && !has(tag.root(), "additional node data", "node name") {
            bail!("No source rest transform for {}. Select the owning .model", node.name);
        }
    }
    let defaults = build_defaults(&skeleton, &tag, render.as_ref(), false);
    let filter = values.get("--animation").filter(|s| !s.is_empty());
    if filter.is_some_and(|s| !animations.iter().any(|a| a.name.as_ref() == Some(s))) {
        bail!("Animation name not found: {}", filter.unwrap());
    }
    let mut results = Vec::new();
    for a in animations.iter() {
        let mut record = json!({"index":a.index, "name":a.name, "animation_type":a.animation_type,
            "frame_info_type":a.frame_info_type, "world_relative":a.world_relative,
            "source_frame_count":a.frame_count, "source_node_count":a.node_count as u8,
            "node_list_checksum":a.node_list_checksum, "resource_group":a.resource_group,
            "resource_group_member":a.resource_group_member, "codec_byte":a.codec_byte,
            "resource_bytes":a.blob.len(), "status":"not_selected"});
        if let Some(e) = tag.root().descend(&format!("definitions/animations[{}]", a.index)) {
            record["source_fields"] = snapshot(e, 0);
        }
        if filter.is_some_and(|f| a.name.as_ref() != Some(f)) { results.push(record); continue; }
        if !supported(a.animation_type.as_deref(), a.frame_info_type.as_deref(), a.world_relative) {
            record["status"] = json!("unsupported");
            record["message"] = json!("First pass imports base clips only; overlays, replacements and world-space clips retain metadata");
            results.push(record); continue;
        }
        let export = || -> Result<Value> {
            if a.node_count as u8 as usize != skeleton.len() { bail!("Animation node count differs from skeleton"); }
            if a.movement_type_mismatch() { bail!("Header/resource movement types disagree"); }
            println!("Decoding {}", a.name.as_deref().unwrap_or("<unnamed>"));
            let clip = a.decode()?;
            let pose = clip.pose(&skeleton, Some(&defaults));
            if pose.frames.is_empty() || pose.frames.len() != a.frame_count as usize { bail!("Decoded/header frame count mismatch"); }
            let kind = jma_kind_for(a);
            if kind.folds_movement() && clip.movement.frames.len() != pose.frames.len() { bail!("Movement sample count differs from pose frame count"); }
            let name = format!("clip_{:04}.{}", a.index, kind.extension().to_ascii_lowercase());
            let mut out = writer(&output.join(&name))?;
            pose.write_jma(&mut out, &skeleton, &defaults, a.node_list_checksum, kind, "actor", Some(&clip.movement))?;
            out.flush()?;
            let motion_name = if kind.folds_movement() {
                let motion_skeleton = Skeleton { nodes: vec![SkeletonNode {
                    name:"movement".into(), parent:-1, first_child:-1, next_sibling:-1,
                }] };
                let motion_pose = Pose { frames: vec![vec![NodeTransform::IDENTITY]; pose.frames.len()] };
                let name = format!("motion_{:04}.{}", a.index, kind.extension().to_ascii_lowercase());
                let mut w = writer(&output.join(&name))?;
                motion_pose.write_jma(&mut w, &motion_skeleton, &[NodeTransform::IDENTITY], 0, kind, "actor", Some(&clip.movement))?;
                w.flush()?;
                Some(name)
            } else { None };
            Ok(json!({"jma_file":name, "motion_file":motion_name, "kind":kind.extension(),
                "decoded_frame_count":pose.frames.len(), "file_frame_count":pose.frames.len()+1,
                "frame_layout":"codec_frames_then_held_terminal", "fps":30,
                "movement_samples":clip.movement.frames.iter().map(|m| json!({
                    "translation":[m.dx,m.dy,m.dz],
                    "rotation":[m.rotation.w,m.rotation.i,m.rotation.j,m.rotation.k]})).collect::<Vec<_>>() }))
        };
        match export() {
            Ok(data) => { record["status"] = json!("decoded"); record["decoded"] = data; }
            Err(e) => { eprintln!("Animation {:?}: {e:#}", a.name); record["status"] = json!("error"); record["message"] = json!(format!("{e:#}")); }
        }
        results.push(record);
    }
    let count = results.iter().filter(|r| r["status"] == "decoded").count();
    let metadata: BTreeMap<_,_> = ["definitions", "contents"] .into_iter()
        .filter_map(|name| tag.root().field(name).and_then(|f| f.as_struct()).map(|s| (name, snapshot(s,0)))).collect();
    let payload = json!({"format":FORMAT, "version":1, "game":"halo3_mcc", "decoder":DECODER,
        "source_tag":relative(&input), "source_graph":relative(&graph_path),
        "source_render_model":render_path.as_ref().map(|p|relative(p)),
        "units":"halo_world", "jma_units":"halo_world_x100", "quaternion_order":"wxyz",
        "rest_space":"parent_local", "rest_source":if render.is_some() {"render_model_with_graph_fallback"} else {"graph_additional_node_data"},
        "nodes":skeleton.nodes.iter().zip(&defaults).map(|(n,t)| json!({"name":n.name,"parent":n.parent,"rest":transform_json(t)})).collect::<Vec<_>>(),
        "animations":results, "source_metadata":metadata,
        "warnings":["Events and graph routing are retained as source metadata, not converted to Reach events.",
            "Base clips only. Decoding does not establish Reach Tool or in-game compatibility."]});
    let mut out = writer(&output.join("animations.h3anim.json"))?;
    serde_json::to_writer(&mut out, &payload)?;
    out.flush()?;
    println!("Animation extraction complete: {count} clips decoded");
    Ok(())
}

fn main() { if let Err(e) = run() { eprintln!("{e:#}"); std::process::exit(1); } }

#[cfg(test)]
mod tests {
    use super::*;
    use blam_tags::animation::JmaKind;
    #[test] fn source_path_guard() {
        for p in ["", "../a", "a/../b", "/a", "C:\\a", "\\\\server\\a", "a//b", "a/./b"] { assert!(safe_relative(p).is_err()); }
        assert_eq!(safe_relative("objects\\scarab.v2\\scarab").unwrap(), "objects/scarab.v2/scarab");
    }
    #[test] fn supported_types_are_explicit() {
        for m in ["none","dx,dy","dx,dy,dyaw","dx,dy,dz,dyaw"] { assert!(supported(Some("base"),Some(m),false)); }
        for t in [None,Some("overlay"),Some("replacement"),Some("unknown")] { assert!(!supported(t,Some("none"),false)); }
        assert!(!supported(Some("base"),Some("dx,dy,dz,dangle_axis"),false));
        assert!(!supported(Some("base"),Some("none"),true));
    }
    #[test] fn quaternion_order_is_wxyz() { assert_eq!(transform_json(&NodeTransform::IDENTITY)["rotation"],json!([1.0,0.0,0.0,0.0])); }
    #[test] fn bytes_are_not_length_only() { assert_eq!(hex(&[0,127,255]), "007fff"); }
    #[test] fn zero_frame_pose_writes_zero_frames() {
        let s=Skeleton {nodes: vec![SkeletonNode{name:"hull".into(),parent:-1,first_child:-1,next_sibling:-1}]};
        validate_skeleton(&s).unwrap();
        let p=Pose {frames:vec![]}; let mut v=Vec::new();
        p.write_jma(&mut v,&s,&[NodeTransform::IDENTITY],0,JmaKind::Jmm,"actor",None).unwrap();
        assert!(String::from_utf8(v).unwrap().starts_with("16392\n0\n30\n"));
    }
}
