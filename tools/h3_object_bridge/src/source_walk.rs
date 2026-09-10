//! Shared read-only field traversal for inspection and portability analysis.
use crate::source_values::leaf;
use anyhow::{Result, bail};
use blam_tags::TagStruct;
use serde_json::{Value, json};

pub fn walk(
    node: TagStruct<'_>,
    parent: &str,
    depth: usize,
    row: &mut impl FnMut(Value) -> Result<()>,
    data: &mut impl FnMut(&[u8]) -> Result<Value>,
) -> Result<()> {
    if depth > 96 {
        bail!("Source tree exceeds depth limit at {parent}");
    }
    for field in node.fields() {
        let name = field.clean_name();
        let path = crate::address(parent, &name, field.ordinal());
        let mut value = json!({"address":path,"name":name,"raw_name":field.name(),
            "ordinal":field.ordinal(),"type":field.type_name()});
        if let Some(child) = field.as_struct() {
            value["kind"] = json!("struct");
            row(value)?;
            walk(child, &path, depth + 1, row, data)?;
        } else if let Some(block) = field.as_block() {
            value["kind"] = json!("block");
            value["count"] = json!(block.len());
            row(value)?;
            for (i, child) in block.iter().enumerate() {
                walk(child, &format!("{path}[{i}]"), depth + 1, row, data)?;
            }
        } else if let Some(array) = field.as_array() {
            value["kind"] = json!("array");
            value["count"] = json!(array.iter().count());
            row(value)?;
            for (i, child) in array.iter().enumerate() {
                walk(child, &format!("{path}[{i}]"), depth + 1, row, data)?;
            }
        } else if let Some(resource) = field.as_resource() {
            value["kind"] = json!("resource_header_only");
            row(value)?;
            if let Some(child) = resource.as_struct() {
                walk(child, &path, depth + 1, row, data)?;
            }
        } else if let Some(bytes) = field.as_data() {
            value["kind"] = json!("data");
            value["bytes"] = json!(bytes.len());
            value["definition"] = json!(field.data_definition_name());
            value
                .as_object_mut()
                .unwrap()
                .extend(data(bytes)?.as_object().unwrap().clone());
            row(value)?;
        } else {
            value["kind"] = json!("value");
            value["value"] = field.value().map(leaf).unwrap_or(Value::Null);
            row(value)?;
        }
    }
    Ok(())
}
