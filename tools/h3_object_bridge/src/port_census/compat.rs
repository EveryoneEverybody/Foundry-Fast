//! Schema evidence via the already-pinned reader's public comparison API.
//! This does not invoke conversion, template synthesis to disk, or tag writers.
use blam_tags::{AliasIndex, FieldVerdict, TagFile};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub fn fingerprint(tag: &TagFile) -> String {
    fn visit(
        node: blam_tags::TagStructDefinition<'_>,
        seen: &mut BTreeMap<usize, usize>,
        rows: &mut Vec<Value>,
    ) -> usize {
        if let Some(id) = seen.get(&node.index()) {
            return *id;
        }
        let id = rows.len();
        seen.insert(node.index(), id);
        rows.push(Value::Null);
        let mut fields = Vec::new();
        for f in node.fields() {
            let child = f
                .as_struct()
                .or_else(|| f.as_block().map(|b| b.struct_definition()))
                .or_else(|| f.as_array().map(|a| a.struct_definition()))
                .or_else(|| f.as_resource().map(|r| r.struct_definition()))
                .or_else(|| f.as_api_interop().map(|a| a.descriptor()));
            let child = child.map(|s| visit(s, seen, rows));
            fields.push(json!({"name":f.name(),"type":f.type_name(),"offset":f.offset(),"width":f.wire_width(),"options":f.option_names().collect::<Vec<_>>(),"data_definition":f.data_definition_name(),"array_count":f.as_array().map(|a|a.count()),"block_max":f.as_block().map(|b|b.max_count()),"resource_name":f.as_resource().map(|r|r.name()),"interop_guid":f.as_api_interop().map(|a|a.guid()),"child":child}));
        }
        rows[id] = json!({"name":node.name(),"guid":node.guid(),"size":node.size(),"version":node.version(),"fields":fields});
        id
    }
    let mut rows = Vec::new();
    visit(tag.root().definition(), &mut BTreeMap::new(), &mut rows);
    super::digest(json!({"group":tag.header.group_tag,"group_version":tag.header.group_version,"structs":rows}).to_string().as_bytes())
}

pub fn actual_catalogue(
    definitions: Option<&Path>,
    graph: &super::graph::Graph,
    index: &BTreeMap<String, PathBuf>,
) -> BTreeMap<String, Value> {
    let mut out = BTreeMap::new();
    let mut targets: BTreeMap<String, TagFile> = BTreeMap::new();
    let Some(root) = definitions else {
        return out;
    };
    for (path, row) in &graph.tags {
        let Some(hash) = row["actual_source_schema"]["fingerprint"].as_str() else {
            continue;
        };
        if out.contains_key(hash) {
            continue;
        }
        let group = super::graph::extension(path);
        let target = root.join("haloreach_mcc").join(format!("{group}.json"));
        let outcome =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<Value, String> {
                if !targets.contains_key(group) {
                    targets.insert(
                        group.into(),
                        TagFile::new(&target).map_err(|e| e.to_string())?,
                    );
                }
                let source = TagFile::read(index.get(path).ok_or("Source missing")?)
                    .map_err(|e| e.to_string())?;
                if fingerprint(&source) != hash {
                    return Err("Source layout changed during analysis".into());
                }
                let mut aliases = AliasIndex::from_schema_json(
                    &root.join("halo3_mcc").join(format!("{group}.json")),
                );
                aliases.extend(AliasIndex::from_schema_json(&target));
                let mut report = compare(&source, &targets[group], &aliases);
                report["scope"] = json!("actual_serialized_h3_layout_to_reach_definition_profile");
                report["representative_source"] = json!(path);
                report["source_layout_sha256"] = json!(hash);
                report["target_schema"] = json!(format!("haloreach_mcc/{group}.json"));
                Ok(report)
            }));
        let value = match outcome {
            Ok(Ok(v)) => v,
            Ok(Err(e)) => {
                json!({"status":"UNSUPPORTED_SCHEMA","reason":e,"representative_source":path})
            }
            Err(_) => {
                json!({"status":"UNSUPPORTED_SCHEMA","reason":"Serialized schema comparison panicked","representative_source":path})
            }
        };
        out.insert(hash.into(), value);
    }
    out
}

fn facts(f: &blam_tags::FieldFacts) -> Value {
    json!({"name":f.name,"clean_name":f.clean_name,"alias":f.alias,"type":f.type_name,"offset":f.offset,"width":f.width})
}
pub fn compare(source: &TagFile, target: &TagFile, aliases: &AliasIndex) -> Value {
    let compared = blam_tags::compare_group_layouts(
        source.root().definition(),
        target.root().definition(),
        aliases,
    );
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut structs = Vec::new();
    for s in &compared.structs {
        let mut fields = Vec::new();
        for f in &s.fields {
            let (status, detail) = match &f.verdict {
                FieldVerdict::Identical => ("identical", Value::Null),
                FieldVerdict::ContainerDrift => ("container_drift", Value::Null),
                FieldVerdict::StructuralOnly => ("structural_only", Value::Null),
                FieldVerdict::Renamed { alias } => ("renamed_provable", json!({"alias":alias})),
                FieldVerdict::TypeEquivalent { reason } => (
                    "type_conversion",
                    json!({"reason":format!("{reason:?}"),"semantic_equivalence":"NOT_PROVEN"}),
                ),
                FieldVerdict::Requantized {
                    source_width,
                    target_width,
                } => (
                    "type_conversion",
                    json!({"source_width":source_width,"target_width":target_width,"may_narrow":source_width>target_width}),
                ),
                FieldVerdict::OptionsRemapped { remap } => ("option_remap", json!({"remap":remap})),
                FieldVerdict::OptionsLost { lost, remap } => {
                    *counts.entry("lost_options".into()).or_default() += lost.len();
                    ("option_loss", json!({"lost":lost,"remap":remap}))
                }
                FieldVerdict::SourceOnly => ("source_only_dropped", Value::Null),
                FieldVerdict::TargetOnly => ("target_only_defaulted", Value::Null),
                FieldVerdict::Blocked(reason) => {
                    ("hard_blocked", json!({"reason":format!("{reason:?}")}))
                }
            };
            *counts.entry(status.into()).or_default() += 1;
            if f.source.is_some() && f.target.is_some() {
                *counts.entry("matched_fields".into()).or_default() += 1;
            }
            let opaque = f.source.as_ref().is_some_and(|x| {
                [
                    "data",
                    "pageable resource",
                    "api interop",
                    "vertex buffer",
                    "custom",
                ]
                .iter()
                .any(|t| x.type_name.contains(t))
            });
            if opaque {
                *counts
                    .entry("opaque_engine_bound_fields".into())
                    .or_default() += 1;
            }
            fields.push(json!({"source":f.source.as_ref().map(facts),"target":f.target.as_ref().map(facts),"verdict":status,"detail":detail,"child_struct_pair":f.child.map(|x|x.0),"opaque_engine_bound":opaque}));
        }
        structs.push(json!({"source_name":s.source_name,"target_name":s.target_name,"source_guid":s.source_guid,"target_guid":s.target_guid,"source_size":s.source_size,"target_size":s.target_size,"fields":fields}));
    }
    json!({"status":format!("{:?}",compared.severity).to_uppercase(),"evidence_level":"VERIFIED","basis":"schema_field_matching","field_counts":counts,"struct_pairs":structs,
        "loss_scope":"Potential schema losses, counted once per interned struct pair; not counts of nondefault authored values",
        "native_target_layout":"NOT_VALIDATED","proven_target_status":"NOT_TESTED","semantic_compatibility":"UNKNOWN","reviewed_conversion_policy":"NOT_APPLIED"})
}

pub fn catalogue(definitions: Option<&Path>, groups: &[String]) -> BTreeMap<String, Value> {
    let mut out = BTreeMap::new();
    for group in groups {
        let Some(root) = definitions else {
            out.insert(group.clone(),json!({"status":"UNSUPPORTED_SCHEMA","reason":"No definitions root supplied","reach_group_available":null}));
            continue;
        };
        let source = root.join("halo3_mcc").join(format!("{group}.json"));
        let target = root.join("haloreach_mcc").join(format!("{group}.json"));
        if !target.is_file() {
            out.insert(group.clone(),json!({"status":"NO_TARGET_GROUP","reason":"Group absent from supplied Reach definitions, not proof of engine removal","reach_group_available":false}));
            continue;
        }
        let result = std::panic::catch_unwind(|| -> Result<Value, String> {
            let a = TagFile::new(&source).map_err(|e| e.to_string())?;
            let b = TagFile::new(&target).map_err(|e| e.to_string())?;
            let mut aliases = AliasIndex::from_schema_json(&source);
            aliases.extend(AliasIndex::from_schema_json(&target));
            let mut r = compare(&a, &b, &aliases);
            r["reach_group_available"] = json!(true);
            r["source_schema"] = json!(format!("halo3_mcc/{group}.json"));
            r["target_schema"] = json!(format!("haloreach_mcc/{group}.json"));
            r["source_schema_sha256"] = json!(super::digest(
                &std::fs::read(&source).map_err(|e| e.to_string())?
            ));
            r["target_schema_sha256"] = json!(super::digest(
                &std::fs::read(&target).map_err(|e| e.to_string())?
            ));
            r["scope"] =
                json!("definition_profile_only; actual serialized tag may use a different layout");
            Ok(r)
        });
        let value = match result {
            Ok(Ok(v)) => v,
            Ok(Err(e)) => {
                json!({"status":"UNSUPPORTED_SCHEMA","reason":e,"reach_group_available":true})
            }
            Err(_) => {
                json!({"status":"UNSUPPORTED_SCHEMA","reason":"Schema reader panicked","reach_group_available":true})
            }
        };
        out.insert(group.clone(), value);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn absent_definitions_stay_unknown() {
        let c = catalogue(None, &["scenario".into()]);
        assert_eq!(c["scenario"]["status"], "UNSUPPORTED_SCHEMA");
        assert!(c["scenario"]["reach_group_available"].is_null());
    }
}
