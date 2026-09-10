//! Decode source device-machine/control animations to normal JMA authoring.
use anyhow::{Context, Result, ensure};
use blam_tags::{TagFile, Animation};
use blam_tags::extract::{TagResolver, ExtractError, animation::animations_to_dir};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::path::{PathBuf, Component};

struct Source {
    root: PathBuf,
    hashes: RefCell<BTreeMap<String,String>>,
}
impl TagResolver for Source {
    fn resolve(&self, reference:&str, extension:&str, _group:u32) -> Result<TagFile,ExtractError> {
        let normalized=reference.replace('\\',"/");
        let rel=PathBuf::from(format!("{normalized}.{extension}"));
        if normalized.contains(':') || rel.components().any(|c|!matches!(c,Component::Normal(_))) {
            return Err(ExtractError::msg("Unsafe device dependency path"));
        }
        let path=self.root.join(rel).canonicalize().map_err(|e|ExtractError::msg(e.to_string()))?;
        if !path.starts_with(&self.root) {return Err(ExtractError::msg("Device dependency escapes source tags"));}
        let bytes=fs::read(&path).map_err(|e|ExtractError::msg(e.to_string()))?;
        self.hashes.borrow_mut().insert(path.to_string_lossy().into_owned(),format!("{:x}",Sha256::digest(bytes)));
        TagFile::read(path).map_err(|e|ExtractError::msg(e.to_string()))
    }
}

fn main()->Result<()> {
    let args=std::env::args_os().skip(1).map(PathBuf::from).collect::<Vec<_>>();
    ensure!(args.len()==3,"Usage: h3-device-animations <tags-root> <device-tag> <new-output-directory>");
    let root=args[0].canonicalize()?;let input=args[1].canonicalize()?;
    let output=args[2].canonicalize()?;
    ensure!(input.starts_with(&root)&&!output.starts_with(&root),"Invalid source/output roots");
    ensure!(fs::read_dir(&output)?.next().is_none(),"Animation output directory must be empty");
    let tag=TagFile::read(&input)?;
    ensure!([b"mach",b"ctrl"].contains(&&tag.header.group_tag.to_be_bytes()),"Only device machines and controls are supported");
    let source=Source{root,hashes:RefCell::new(BTreeMap::new())};
    source.hashes.borrow_mut().insert(input.to_string_lossy().into_owned(),format!("{:x}",Sha256::digest(fs::read(&input)?)));
    let resolved=blam_tags::extract::animation::resolve_animation_inputs(&tag,&source)?;
    let graph=resolved.jmad.as_ref().context("Device has no local animation graph")?;
    let animations=Animation::new(graph)?;
    ensure!(animations.len()<=128,"Device animation budget exceeded; classify complex machine separately");
    let name=input.file_stem().context("Device name absent")?.to_string_lossy();
    let summary=animations_to_dir(&tag,&source,&output,&name)?;
    let report=json!({"format":"foundry.h3-device-animations","version":1,"source_tag":input,
        "source_hashes":source.hashes.borrow().clone(),"written":summary.written,"skipped":summary.skipped,
        "warnings":summary.warnings,"source_animation_count":animations.len(),
        "policy":"Decoded device motion into JMA authoring; no H3 runtime animation resources copied", "native_status":"NOT_GENERATED"});
    serde_json::to_writer_pretty(OpenOptions::new().write(true).create_new(true).open(output.join("animation-decode-report.json"))?,&report)?;
    println!("Decoded {} device animations; {} skipped",summary.written,summary.skipped);
    Ok(())
}
