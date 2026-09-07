//! Interpret the same source rows consumed by the existing scenario viewer.
use super::graph::Scan;
use serde_json::{Value, json};
use std::collections::BTreeMap;

pub fn parent(address: &str) -> &str {
    address.rsplit_once('/').map(|x| x.0).unwrap_or("")
}
pub fn section(address: &str) -> &str {
    address
        .split('/')
        .next()
        .unwrap_or("")
        .split('#')
        .next()
        .unwrap_or("")
}
pub fn entities(scan: &Scan, name: &str) -> Vec<Value> {
    let mut entities: BTreeMap<String, Value> = BTreeMap::new();
    for row in &scan.metadata {
        let address = row["address"].as_str().unwrap_or("");
        // Identify the requested block segment and its source element index.
        let mut parts = Vec::new();
        let mut entity_address = None;
        for part in address.split('/') {
            parts.push(part);
            if part.split('#').next() == Some(name) && part.contains('[') {
                entity_address = Some(parts.join("/"));
                break;
            }
        }
        if let Some(key) = entity_address {
            let entity = entities
                .entry(key.clone())
                .or_insert_with(|| json!({"address":key,"fields":{},"records":[]}));
            let value = row["value"].clone();
            if row["kind"] == "value" {
                entity["fields"][row["address"]
                    .as_str()
                    .unwrap()
                    .strip_prefix(&format!("{key}/"))
                    .unwrap_or(address)] = value.clone();
            }
            if row["name"] == "name" && parent(address) == key {
                entity["name"] = value;
            }
            entity["records"].as_array_mut().unwrap().push(row.clone());
        }
    }
    entities.into_values().collect()
}
pub fn field<'a>(entity: &'a Value, name: &str) -> Option<&'a Value> {
    let prefix = format!("{name}#");
    entity["fields"]
        .as_object()?
        .iter()
        .find(|(k, _)| k.starts_with(&prefix) && !k.contains('/'))
        .map(|(_, v)| v)
}
pub fn symbols(scan: &Scan) -> BTreeMap<String, Vec<Value>> {
    let categories = [
        "object names",
        "squads",
        "squad groups",
        "trigger volumes",
        "cutscene flags",
        "cutscene camera points",
        "point sets",
        "zones",
        "areas",
        "ai objectives",
        "tasks",
        "designer zones",
        "zone sets",
        "starting locations",
        "points",
    ];
    let mut table: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for category in categories {
        for entity in entities(scan, category) {
            if let Some(name) = entity["name"].as_str().filter(|s| !s.is_empty()) {
                table
                    .entry(name.to_lowercase())
                    .or_default()
                    .push(json!({"category":category,"address":entity["address"],"name":name}));
            }
        }
    }
    // Qualified AI and point references keep their authored parent name.
    let entries: Vec<_> = table.values().flatten().cloned().collect();
    for child in &entries {
        let address = child["address"].as_str().unwrap();
        let owner = entries
            .iter()
            .filter(|p| {
                p["address"]
                    .as_str()
                    .is_some_and(|a| address.starts_with(&format!("{a}/")))
            })
            .max_by_key(|p| p["address"].as_str().unwrap().len());
        if let Some(owner) = owner {
            let name = format!(
                "{}/{}",
                owner["name"].as_str().unwrap(),
                child["name"].as_str().unwrap()
            )
            .to_lowercase();
            table.entry(name).or_default().push(child.clone());
        }
    }
    table
}
pub fn report(scan: &Scan) -> Value {
    let categories = [
        "structure bsps",
        "zone sets",
        "skies",
        "object names",
        "scenery",
        "machines",
        "controls",
        "crates",
        "vehicles",
        "weapons",
        "equipment",
        "bipeds",
        "giants",
        "effect scenery",
        "sound scenery",
        "light volumes",
        "terminals",
        "trigger volumes",
        "player starting locations",
        "cutscene flags",
        "cutscene camera points",
        "squads",
        "squad groups",
        "fire-teams",
        "zones",
        "areas",
        "firing positions",
        "ai objectives",
        "tasks",
        "designer zones",
        "point sets",
        "points",
        "giant sector hints",
        "giant rail hints",
        "reference frames",
        "node orientations",
        "decals",
        "decorators",
        "source files",
        "cinematics",
        "cortana effects",
        "flocks",
    ];
    let mut rows = Vec::new();
    for category in categories {
        let count = scan
            .sections
            .iter()
            .find(|r| r["name"] == category && r["kind"] == "block")
            .and_then(|r| r["count"].as_u64())
            .or_else(|| scan.block_counts.get(category).copied());
        rows.push(json!({"category":category,"count":count,"status":if count.is_some(){"SOURCE_DECODE_ONLY"}else{"NOT_OBSERVED_BY_NAME"},"reach_correspondence":if matches!(category,"node orientations"|"giant sector hints"|"giant rail hints"){"MANUAL"}else{"PROVISIONAL"},"note":if category=="node orientations"{"Stored-pose codec remains unsupported; zero poses applied"}else if category=="structure bsps"{"Rebuild render/collision/pathfinding/resources through Reach tooling"}else{"Name-level corresponding system is a planning hypothesis, not loader acceptance"}}));
    }
    let mut content = BTreeMap::new();
    for category in categories {
        if !["firing positions", "points"].contains(&category) {
            let mut values = entities(scan, category);
            // Values remain keyed by exact source address in fields. Retain
            // only container/resource records here, avoiding a second copy of
            // every scalar; complete field type comparisons live in the schema.
            for entity in &mut values {
                entity["records"]
                    .as_array_mut()
                    .unwrap()
                    .retain(|r| r["kind"] != "value");
            }
            if !values.is_empty() {
                content.insert(category, values);
            }
        }
    }
    let placements: [&str; 14] = [
        "scenery",
        "machines",
        "controls",
        "crates",
        "vehicles",
        "weapons",
        "equipment",
        "bipeds",
        "giants",
        "effect scenery",
        "sound scenery",
        "light volumes",
        "terminals",
        "decals",
    ];
    let parent_relative: Vec<_> = scan
        .metadata
        .iter()
        .filter(|r| r["name"] == "parent object" && r["value"].as_i64().is_some_and(|v| v >= 0))
        .cloned()
        .collect();
    let mut unresolved = Vec::new();
    for category in placements {
        for entity in entities(scan, category) {
            if field(&entity, "type")
                .and_then(Value::as_i64)
                .is_some_and(|n| n < 0)
            {
                unresolved
                    .push(json!({"address":entity["address"],"reason":"Negative palette index"}));
            }
        }
    }
    json!({"basis":"Existing H3 source field walker and source-value encoding; no second scenario binary parser","categories":rows,"root_sections":scan.sections,"block_counts":scan.block_counts,"content":content,"parent_relative_placements":parent_relative,"unresolved_placements":unresolved,"stored_poses":{"count":scan.block_counts.get("node orientations"),"applied":0,"status":"BLOCKED","reason":"Packed H3 node orientations have no verified codec"},"proven_target_status":"NOT_TESTED","limitations":["Counts are source block totals, not runtime active entities","Parent attachments and reference frames retain source addresses; no guessed transforms","Detailed firing-position coordinates are omitted from this census; existing scenario inspection retains them"]})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn symbols_keep_source_addresses() {
        let mut scan = Scan::default();
        scan.metadata = vec![
            json!({"kind":"value","address":"trigger volumes#7[0]/name#0","name":"name","value":"tv_start"}),
        ];
        let s = symbols(&scan);
        assert_eq!(s["tv_start"][0]["address"], "trigger volumes#7[0]");
        assert_eq!(s["tv_start"][0]["category"], "trigger volumes");
    }
}
