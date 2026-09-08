//! Read-only comparison of native lightmap pixels, distinct from tag headers.
use anyhow::{Context, Result, ensure};
use blam_tags::TagFile;
use serde_json::json;
use sha2::{Digest, Sha256};

fn main() -> Result<()> {
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    ensure!(args.len() == 2, "Expected baseline and diagnostic bitmap paths");
    let a = TagFile::read(&args[0])?;
    let b = TagFile::read(&args[1])?;
    let pixels = |tag: &TagFile| -> Result<Vec<u8>> {
        let data = tag.root().field("processed pixel data").and_then(|f| f.as_data())
            .context("Missing processed pixel data")?;
        ensure!(!data.is_empty(), "Empty pixel payload");
        Ok(data.to_vec())
    };
    let pa = pixels(&a)?;
    let pb = pixels(&b)?;
    ensure!(pa.len() == pb.len(), "Payload size differs; layout must be reconciled first");
    let changed = pa.iter().zip(&pb).filter(|(x,y)| x != y).count();
    serde_json::to_writer_pretty(std::io::stdout(), &json!({
        "baseline": args[0].to_string_lossy(), "diagnostic": args[1].to_string_lossy(), "bytes": pa.len(),
        "baseline_pixel_sha256": format!("{:x}", Sha256::digest(&pa)),
        "diagnostic_pixel_sha256": format!("{:x}", Sha256::digest(&pb)),
        "changed_pixel_bytes": changed, "changed_byte_fraction": changed as f64 / pa.len() as f64,
        "interpretation": "Encoded pixel change only, not a photometric or runtime brightness measurement"
    }))?;
    Ok(())
}
