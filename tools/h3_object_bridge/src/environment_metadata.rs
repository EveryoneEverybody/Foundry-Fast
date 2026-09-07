//! Opt-in, read-only environment contracts. No compiled resource bytes are exported.
use anyhow::{Context, Result, bail};
use blam_tags::{TagFile, TagStruct, TagFieldData};
use serde_json::{Value, json, Map};
use crate::source_values::leaf;
use std::collections::BTreeSet;

fn collision_mesh(node: TagStruct<'_>) -> Result<Value> {
    let surfaces = node.field("surfaces").and_then(|f|f.as_block()).context("Missing instance collision surfaces")?;
    let edges = node.field("edges").and_then(|f|f.as_block()).context("Missing instance collision edges")?;
    let points = node.field("vertices").and_then(|f|f.as_block()).context("Missing instance collision vertices")?;
    let mut vertices = vec![];
    let mut triangles = vec![];
    let mut source_surfaces = vec![];
    for (si, surface) in surfaces.iter().enumerate() {
        let first = surface.read_int_any("first edge").context("Missing instance first edge")?;
        let mut edge_index = first;
        let start = vertices.len();
        let mut ring_edges = vec![];
        let mut ring_points = vec![];
        let mut seen = BTreeSet::new();
        loop {
            if edge_index < 0 || !seen.insert(edge_index) { bail!("Malformed instance collision surface {si}"); }
            let edge = edges.element(edge_index as usize).context("Invalid instance collision edge")?;
            ring_edges.push(edge_index as i64);
            let (vertex, next) = if edge.read_int_any("left surface") == Some(si as i128) {
                (edge.read_int_any("start vertex"),edge.read_int_any("forward edge"))
            } else if edge.read_int_any("right surface") == Some(si as i128) {
                (edge.read_int_any("end vertex"),edge.read_int_any("reverse edge"))
            } else { bail!("Instance collision edge does not own surface {si}"); };
            let vertex = vertex.context("Missing instance collision vertex")?;
            if vertex < 0 { bail!("Negative instance collision vertex"); }
            ring_points.push(vertex as i64);
            let p = points.element(vertex as usize).context("Invalid instance collision point")?.read_point3d("point");
            if [p.x,p.y,p.z].iter().any(|v|!v.is_finite()) { bail!("Nonfinite instance collision point"); }
            vertices.push(json!({"position":[p.x*100.0,p.y*100.0,p.z*100.0],"normal":[0,0,1],"uvs":[],"weights":[]}));
            edge_index = next.context("Missing instance collision next edge")?;
            if edge_index == first { break; }
        }
        let count = vertices.len()-start;
        if count < 3 { bail!("Degenerate instance collision ring {si}"); }
        let material = surface.read_int_any("material").context("Missing instance collision material")?;
        let mut metadata = scalar_fields(surface)?;
        metadata["triangle_start"] = json!(triangles.len());
        metadata["triangle_count"] = json!(count-2);
        metadata["source_surface"] = json!(si);
        metadata["ring"] = json!({"source_edges":ring_edges,"source_vertices":ring_points,
            "decoded_vertices":(start..vertices.len()).collect::<Vec<_>>()});
        source_surfaces.push(metadata);
        for i in 1..count-1 {
            triangles.push(json!({"material":material,"vertices":[start,start+i,start+i+1],"source_surface":si}));
        }
    }
    Ok(json!({"kind":"mesh","vertices":vertices,"triangles":triangles,"source_surfaces":source_surfaces}))
}

fn scalar_fields(node: TagStruct<'_>) -> Result<Value> {
    let mut out = Map::new();
    for field in node.fields() {
        let name = field.clean_name();
        if name.is_empty() { continue; }
        let value = if let Some(block) = field.as_block() {
            json!({"source_block_count":block.len()})
        } else if let Some(child) = field.as_struct() {
            scalar_fields(child)?
        } else if field.as_data().is_some() || field.as_resource().is_some() {
            json!({"compiled_payload":"not_exported"})
        } else { field.value().map(|v| match v {
            TagFieldData::RealBounds(b) => crate::source_values::floats(&[b.lower,b.upper]),
            TagFieldData::RealPlane3d(p) => crate::source_values::floats(&[p.i,p.j,p.k,p.d]),
            other => leaf(other),
        }).unwrap_or(Value::Null) };
        if out.insert(name.to_string(), value).is_some() { bail!("Duplicate source environment field {name}"); }
    }
    Ok(Value::Object(out))
}

fn rows(node: &TagStruct<'_>, name: &str) -> Result<Vec<Value>> {
    let Some(block) = node.field_path(name).and_then(|f|f.as_block()) else { return Ok(vec![]); };
    block.iter().enumerate().map(|(i, element)| {
        let mut value = scalar_fields(element)?;
        value["source_index"] = json!(i);
        Ok(value)
    }).collect()
}

pub fn extract(tag: &TagFile) -> Result<Value> {
    let root = tag.root();
    let mut result = json!({"version":1});
    for (key, path) in [
        ("clusters", "clusters"), ("portals", "cluster portals"),
        ("instances", "instanced geometry instances"), ("materials", "materials"),
        ("collision_materials", "collision materials"), ("seams", "seam identifiers"),
        ("environment_objects", "environment objects"), ("weather", "weather polyhedra"),
        ("definitions", "resource interface/raw_resources[0]/raw_items/instanced geometries definitions"),
        ("render_meshes", "render geometry/meshes"),
    ] { result[key] = json!(rows(&root, path)?); }
    // Part flags and material lighting indices are distinct from shader identity.
    let meshes = root.field_path("render geometry/meshes").and_then(|f|f.as_block())
        .context("Missing environment render mesh table")?;
    for (i, mesh) in meshes.iter().enumerate() {
        result["render_meshes"][i]["parts"] = json!(rows(&mesh, "parts")?);
        result["render_meshes"][i]["subparts"] = json!(rows(&mesh, "subparts")?);
    }
    if let Some(defs) = root.field_path("resource interface/raw_resources[0]/raw_items/instanced geometries definitions").and_then(|f|f.as_block()) {
        for (i, def) in defs.iter().enumerate() {
            let collision = def.field("collision info").and_then(|f|f.as_struct()).context("Missing instance collision definition")?;
            result["definitions"][i]["collision_mesh"] = collision_mesh(collision)?;
            // These are correspondence evidence, not copied target runtime data.
            // Keep the source topology needed to distinguish an unassigned solid
            // instance surface from the separate structure-sky encoding.
            for name in ["surfaces", "surface to triangle mapping", "breakable surface sets"] {
                result["definitions"][i][name] = json!(rows(&def, name)?);
            }
            for name in ["planes", "edges", "vertices"] {
                result["definitions"][i]["collision_mesh"][name.to_string()+"_source"] = json!(rows(&collision, name)?);
            }
        }
    }
    for (key, path, nested) in [
        ("portals", "cluster portals", "vertices"),
        ("clusters", "clusters", "portals"),
        ("materials", "materials", "properties"),
        ("seams", "seam identifiers", "edge mapping"),
        ("seams", "seam identifiers", "cluster mapping"),
    ] {
        if let Some(block) = root.field(path).and_then(|f|f.as_block()) {
            for (i, row) in block.iter().enumerate() {
                result[key][i][nested] = json!(rows(&row, nested)?);
            }
        }
    }
    let bounds = ["world bounds x", "world bounds y", "world bounds z"].map(|n|
        root.field(n).and_then(|f|f.value()).map(|v| match v {
            TagFieldData::RealBounds(b) => crate::source_values::floats(&[b.lower,b.upper]),
            other => leaf(other),
        }).unwrap_or(Value::Null));
    result["world_bounds"] = json!(bounds);
    result["policy"] = json!("Source authoring fields and compiled-field inventories only; target Tool must rebuild all runtime resources");
    Ok(result)
}
