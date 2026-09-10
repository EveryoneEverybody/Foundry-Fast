//! Read-only local texel deltas for native PC ABGRFP32 lightmap arrays.
//! Plane/channel statistics are not reconstructed illumination or world ROIs.
use anyhow::{Context, Result, ensure};
use blam_tags::{TagFile, TagFieldData as D};
use serde_json::json;
use sha2::{Digest, Sha256};

fn pixels(path: &std::ffi::OsStr) -> Result<(Vec<u8>, Vec<i32>)> {
    let tag = TagFile::read(path)?;
    let root = tag.root();
    let bitmaps = root.field("bitmaps").and_then(|f| f.as_block()).context("Missing bitmap layout")?;
    ensure!(bitmaps.len() == 1, "Expected exactly one bitmap image");
    let row = bitmaps.iter().next().unwrap();
    let layout = ["width", "height", "depth", "type", "format", "mipmap count"].iter()
        .map(|n| row.field(n).and_then(|f| f.value()).and_then(|v| match v {
            D::ShortInteger(v) | D::ShortEnum { value: v, .. } => Some(v as i32),
            D::CharInteger(v) | D::CharEnum { value: v, .. } => Some(v as i32),
            D::LongInteger(v) => Some(v), _ => None,
        }).with_context(|| format!("Missing {n}")))
        .collect::<Result<Vec<_>>>()?;
    ensure!(layout[0] > 0 && layout[1] > 0 && layout[2] > 0 && layout[3] == 3 && layout[4] == 24 && layout[5] == 0,
        "Only native PC ABGRFP32 arrays without mipmaps are supported: {layout:?}");
    let data = root.field("processed pixel data").and_then(|f| f.as_data()).context("Missing pixels")?.to_vec();
    ensure!(data.len() == layout[0] as usize * layout[1] as usize * layout[2] as usize * 16, "Pixel layout length mismatch");
    Ok((data, layout))
}

fn main() -> Result<()> {
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    ensure!(args.len() == 2, "Expected baseline and diagnostic bitmap paths");
    let (a, layout) = pixels(&args[0])?;
    let (b, other) = pixels(&args[1])?;
    ensure!(layout == other, "Layout changed; do not compare unrelated texels");
    let (w, h, d) = (layout[0] as usize, layout[1] as usize, layout[2] as usize);
    let mut planes = Vec::new();
    for z in 0..d {
        let mut changed = 0usize;
        let mut bounds = [w, h, 0, 0];
        let mut sums = [0f64; 4];
        let mut maxima = [0f64; 4];
        let mut finite_pairs = [0usize; 4];
        let mut nonfinite_pairs = [0usize; 4];
        let mut changed_nonfinite_pairs = [0usize; 4];
        let mut tiles = std::collections::BTreeMap::<(usize, usize), usize>::new();
        for y in 0..h { for x in 0..w {
            let start = ((z * h + y) * w + x) * 16;
            if a[start..start+16] != b[start..start+16] {
                changed += 1;
                bounds[0] = bounds[0].min(x); bounds[1] = bounds[1].min(y);
                bounds[2] = bounds[2].max(x); bounds[3] = bounds[3].max(y);
                *tiles.entry((x / 32, y / 32)).or_default() += 1;
            }
            for c in 0..4 {
                let i = start + c * 4;
                let av = f32::from_le_bytes(a[i..i+4].try_into()?);
                let bv = f32::from_le_bytes(b[i..i+4].try_into()?);
                // The captured native payload contains nonfinite values.
                // Preserve their bitwise difference accounting; never turn
                // them into zero or include them in photometric statistics.
                if !av.is_finite() || !bv.is_finite() {
                    nonfinite_pairs[c] += 1;
                    changed_nonfinite_pairs[c] += usize::from(a[i..i+4] != b[i..i+4]);
                    continue;
                }
                finite_pairs[c] += 1;
                let delta = (bv as f64 - av as f64).abs();
                sums[c] += delta; maxima[c] = maxima[c].max(delta);
            }
        }}
        planes.push(json!({"plane": z, "changed_texels": changed,
            "changed_bounds_inclusive": if changed > 0 { Some(bounds) } else { None },
            "mean_absolute_finite_delta_per_stored_channel": (0..4).map(|c| if finite_pairs[c] > 0 { Some(sums[c] / finite_pairs[c] as f64) } else { None }).collect::<Vec<_>>(),
            "max_absolute_delta_per_stored_channel": maxima,
            "finite_pairs_per_channel": finite_pairs, "nonfinite_pairs_per_channel": nonfinite_pairs,
            "changed_nonfinite_pairs_per_channel": changed_nonfinite_pairs,
            "changed_tiles_32x32": tiles.into_iter().map(|((x,y),n)| json!({"tile_xy":[x,y],"changed_texels":n})).collect::<Vec<_>>() }));
    }
    serde_json::to_writer_pretty(std::io::stdout(), &json!({
        "format": "foundry.lightmap-texel-delta", "version": 1, "layout": layout,
        "baseline": args[0].to_string_lossy(), "diagnostic": args[1].to_string_lossy(),
        "baseline_pixel_sha256": format!("{:x}", Sha256::digest(&a)),
        "diagnostic_pixel_sha256": format!("{:x}", Sha256::digest(&b)), "planes": planes,
        "limitations": "Stored linear float channels only; no coefficient-to-radiance reconstruction, world position mapping, or runtime brightness claim."
    }))?;
    Ok(())
}
