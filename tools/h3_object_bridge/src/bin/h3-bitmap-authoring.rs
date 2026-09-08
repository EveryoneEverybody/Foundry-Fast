//! Recover six original cubemap faces as TIFF authoring, never copy runtime tags.
use anyhow::{Context, Result, ensure};
use blam_tags::{Bitmap, TagFile};
use serde_json::json;
use sha2::{Digest,Sha256};
use std::{fs::{self,OpenOptions},io::Write,path::PathBuf};

fn main()->Result<()> {
    let args=std::env::args_os().skip(1).map(PathBuf::from).collect::<Vec<_>>();
    ensure!(args.len()==3,"Usage: h3-bitmap-authoring <tags-root> <bitmap-tag> <new-empty-output-dir>");
    let root=args[0].canonicalize()?;let input=args[1].canonicalize()?;
    let output=args[2].canonicalize()?;
    ensure!(input.starts_with(&root) && input.is_file(),"Source must belong to tags root");
    ensure!(!output.starts_with(&root) && output.is_dir() && fs::read_dir(&output)?.next().is_none(),"Output must be empty and outside source tags");
    let tag=TagFile::read(&input)?;let bitmap=Bitmap::new(&tag)?;
    ensure!(bitmap.len()==1,"Only one indexed source image is supported");
    let image=bitmap.image(0).context("Missing image")?;
    let format=image.format_name().unwrap_or_default().to_lowercase();
    ensure!(image.is_cube() && image.depth()==1 && image.width()==image.height()
        && image.width()>0 && image.width()<=4096
        && ["dxt1","dxt5","x8r8g8b8","a8r8g8b8"].contains(&format.as_str()),"Unsupported bounded cubemap shape/format");
    let mut pixels=Vec::new();image.write_tiff(&mut pixels)?;
    OpenOptions::new().write(true).create_new(true).open(output.join("source_cube.tif"))?.write_all(&pixels)?;
    let layout=json!({"tiff":"source_cube.tif","layout":"directx_cross_4x3",
        "face_order":["+X","-X","+Y","-Y","+Z","-Z"],
        "cells":[[0,1],[2,1],[1,0],[1,2],[1,1],[3,1]],
        "face_rotations_quarter_turns":[0,0,0,0,0,0],"width":image.width()*4,"height":image.height()*3,
        "decoded_faces":6,"pixel_format":"RGBA8","mip_policy":"TIFF contains six base faces; original DDS retains source mips",
        "source_sequence_count":bitmap.sequences().len()});
    let result=json!({"source_tag":input.strip_prefix(&root)?.to_string_lossy().replace('\\',"/"),
        "source_sha256":format!("{:x}",Sha256::digest(fs::read(&input)?)),"format":format,
        "cube_source":layout,"status":"cube_source_pixels","runtime_status":"NOT_GENERATED"});
    serde_json::to_writer(OpenOptions::new().write(true).create_new(true).open(output.join("bitmap-authoring.json"))?,&result)?;
    println!("Decoded six source cube faces");Ok(())
}
