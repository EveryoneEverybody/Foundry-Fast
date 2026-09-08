//! Read-only collision-tree evidence for light membership audits. No tag writes.
use anyhow::{Context, Result, ensure};
use blam_tags::TagFile;
use serde_json::json;
use sha2::{Digest, Sha256};

fn main() -> Result<()> {
    let path = std::env::args_os().nth(1).context("Expected source BSP tag path")?;
    let bytes = std::fs::read(&path)?;
    let tag = TagFile::read(&path)?;
    let root = tag.root();
    let bsps = root.field_path("resource interface/raw_resources[0]/raw_items/collision bsp")
        .and_then(|f| f.as_block()).context("Missing collision BSP")?;
    ensure!(bsps.len() == 1, "Ambiguous collision BSP");
    let bsp = bsps.element(0).unwrap();
    let nodes = bsp.field("bsp3d nodes").and_then(|f| f.as_block()).context("Missing nodes")?;
    let planes = bsp.field("planes").and_then(|f| f.as_block()).context("Missing planes")?;
    let leaves = root.field("leaves").and_then(|f| f.as_block()).context("Missing cluster leaves")?;
    let collision_leaves = bsp.field("leaves").and_then(|f| f.as_block()).context("Missing collision leaves")?;
    ensure!(leaves.len() == collision_leaves.len(), "Cluster and collision leaf counts differ");
    let packed = nodes.iter().map(|n| Ok(n.read_int_any("node data designator")
        .context("Missing packed node")? as u64)).collect::<Result<Vec<_>>>()?;
    let planes = planes.iter().map(|p| {
        ensure!(matches!(p.field("plane").and_then(|f| f.value()),
            Some(blam_tags::TagFieldData::RealPlane3d(_))), "Missing plane");
        let p = p.read_plane3d("plane");
        Ok([p.i, p.j, p.k, p.d])
    }).collect::<Result<Vec<_>>>()?;
    let clusters = leaves.iter().map(|l| Ok(l.read_int_any("cluster")
        .context("Missing leaf cluster")? as i32)).collect::<Result<Vec<_>>>()?;
    serde_json::to_writer_pretty(std::io::stdout(), &json!({
        "format": "foundry.h3-lighting-spatial-evidence", "version": 1,
        "source_path": path, "source_sha256": format!("{:x}", Sha256::digest(bytes)),
        "decoder": "blam-tags@5d0509fb75eadb96ac7774542ca0b2c10aed7b00",
        "units": "world_units", "nodes_u64": packed, "planes": planes, "leaf_clusters": clusters,
        "node_layout": "plane bits 0..15; back 16..39; front 40..63; leaf bit 23; solid 0xffffff"
    }))?;
    Ok(())
}
