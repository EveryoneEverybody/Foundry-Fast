//! Symbol resolution and call-site analysis over the retained HSC AST.
use super::{
    hsc::{Catalogue, Declaration, Form, Sources, declaration},
    hsc_compat as compat,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

fn declared_type(value: &Value) -> Option<String> {
    value
        .as_str()
        .or_else(|| value["label"].as_str())
        .or_else(|| value["name"].as_str())
        .map(str::to_owned)
}
fn stock_player_slot(d: &Declaration) -> Option<usize> {
    if d.kind != "static" || d.result != "unit" || !d.params.is_empty() || d.body.len() != 1 {
        return None;
    }
    let unit = &d.body[0];
    if unit.head() != "unit" || unit.list().len() != 2 {
        return None;
    }
    let list = &unit.list()[1];
    if list.head() != "list_get" || list.list().len() != 3 {
        return None;
    }
    let players = &list.list()[1];
    if players.head() != "players" || players.list().len() != 1 {
        return None;
    }
    list.list()[2]
        .text()
        .parse::<usize>()
        .ok()
        .filter(|i| *i < 4)
}
struct Walk<'a> {
    sources: &'a Sources,
    cat: &'a Catalogue,
    review: &'a Value,
    symbols: &'a BTreeMap<String, Vec<Value>>,
    lookup: BTreeMap<String, Vec<&'a Declaration>>,
    calls: Vec<Value>,
    uses: Vec<Value>,
    globals: Vec<Value>,
    script_calls: Vec<Value>,
    unknown: Vec<Value>,
    diagnostics: Vec<Value>,
    unresolved_calls: Vec<Value>,
}
impl Walk<'_> {
    fn original(&self, f: &Form) -> &str {
        self.sources
            .texts
            .get(&f.location.file)
            .and_then(|s| s.get(f.location.byte..f.end_byte))
            .unwrap_or("")
    }
    fn infer(&self, f: &Form, d: &Declaration, depth: usize) -> Vec<String> {
        if depth > 64 {
            return vec![];
        }
        let name = if f.atom.is_some() { f.text() } else { f.head() }.to_lowercase();
        if f.atom.is_some() {
            if f.quoted {
                return vec!["quoted_atom".into()];
            }
            if ["true", "false", "on", "off"].contains(&name.as_str()) {
                return vec!["boolean".into()];
            }
            if name == "none" {
                return vec!["none".into()];
            }
            if ["0", "1"].contains(&name.as_str()) {
                return vec!["boolean_integer_literal".into()];
            }
            if name.parse::<i64>().is_ok() {
                return vec!["integer_literal".into()];
            }
            if name.parse::<f64>().is_ok() {
                return vec!["real_literal".into()];
            }
            if let Some(t) = d.params.get(&name) {
                return vec![t.clone()];
            }
            if let Some(defs) = self
                .lookup
                .get(&name)
                .filter(|defs| defs.iter().any(|d| d.kind == "global"))
            {
                return defs
                    .iter()
                    .filter(|d| d.kind == "global")
                    .map(|d| d.result.clone())
                    .collect::<BTreeSet<_>>()
                    .into_iter()
                    .collect();
            }
            let mut types: BTreeSet<String> = self
                .lookup
                .get(&name)
                .into_iter()
                .flatten()
                .map(|d| {
                    if d.kind == "command_script" {
                        "ai_command_script".into()
                    } else {
                        "script".into()
                    }
                })
                .collect();
            if let Some(entries) = self.symbols.get(&name) {
                types.extend(entries.iter().filter_map(|r| {
                    match r["category"].as_str().unwrap_or("") {
                        "squads" | "squad groups" | "ai objectives" | "tasks"
                        | "starting locations" => Some("ai".into()),
                        "point sets" | "points" => Some("point_reference".into()),
                        "trigger volumes" => Some("trigger_volume".into()),
                        "cutscene flags" => Some("cutscene_flag".into()),
                        "cutscene camera points" => Some("cutscene_camera_point".into()),
                        "zone sets" => Some("zone_set".into()),
                        "scripts" => Some("script".into()),
                        "globals" => declared_type(&r["declared_type"]),
                        // An object-name row alone does not prove the placed subtype.
                        _ => None,
                    }
                }));
            }
            if !types.is_empty() {
                types.insert("symbol_literal".into());
                // Script names and typed scenario literals occupy context-dependent
                // namespaces. A script declaration is not a global variable. Keep
                // an unproven alternate namespace instead of rejecting by name.
                if types.contains("script") || types.contains("ai_command_script") {
                    types.insert("unresolved_typed_name".into());
                }
                return types.into_iter().collect();
            }
            return self
                .cat
                .h3
                .globals
                .get(&name)
                .cloned()
                .into_iter()
                .collect::<Vec<_>>();
        }
        if let Some(defs) = self.lookup.get(&name) {
            return defs
                .iter()
                .map(|d| d.result.clone())
                .collect::<BTreeSet<_>>()
                .into_iter()
                .collect();
        }
        if let Some(sigs) = self.cat.h3.functions.get(&name) {
            let args: Vec<_> = f.list()[1..]
                .iter()
                .map(|a| self.infer(a, d, depth + 1))
                .collect();
            return compat::best(sigs, &args)
                .into_iter()
                .map(|s| s.result.clone())
                .filter(|t| !matches!(t.as_str(), "passthrough" | "expression" | "void"))
                .collect::<BTreeSet<_>>()
                .into_iter()
                .collect();
        }
        self.symbols
            .get(&name)
            .into_iter()
            .flatten()
            .filter(|r| r["category"] == "scripts")
            .filter_map(|r| declared_type(&r["declared_type"]))
            .collect()
    }
    fn atom(&mut self, f: &Form, d: &Declaration, expected: Option<&str>, call: Option<&str>) {
        let expected = expected.map(|t| if t == "script name" { "script" } else { t });
        let name = f.text().to_lowercase();
        if f.quoted
            && !expected.is_some_and(|t| {
                matches!(
                    t,
                    "object"
                        | "object_name"
                        | "unit"
                        | "vehicle"
                        | "device"
                        | "scenery"
                        | "weapon"
                        | "effect_scenery"
                        | "trigger_volume"
                        | "cutscene_flag"
                        | "cutscene_camera_point"
                        | "point_reference"
                        | "ai"
                        | "string_id"
                )
            })
        {
            return;
        }
        if name.is_empty() || d.params.contains_key(&name) {
            return;
        }
        if let Some(defs) = self.lookup.get(&name) {
            if defs.iter().any(|v| v.kind == "global") {
                self.globals.push(json!({"name":name,"kind":"user_global","location":f.location,"enclosing_script":d.name,"original_source_expression":self.original(f)}));
            } else if expected == Some("script") || expected == Some("ai_command_script") {
                self.script_calls.push(json!({"name":name,"location":f.location,"enclosing_script":d.name,"edge_kind":"script_reference","via":call,"resolution":"USER_SCRIPT","original_source_expression":self.original(f),"declaration_locations":defs.iter().map(|d|&d.location).collect::<Vec<_>>()}));
            }
            if defs.iter().any(|v| v.kind == "global")
                || matches!(expected, Some("script") | Some("ai_command_script"))
            {
                return;
            }
        }
        if let Some(matches) = self.symbols.get(&name) {
            if matches.iter().any(|r| {
                r["category"] == "globals"
                    || (r["category"] == "scripts"
                        && matches!(expected, Some("script") | Some("ai_command_script")))
            }) {
                self.script_calls.push(json!({"name":name,"location":f.location,"enclosing_script":d.name,"edge_kind":"script_reference","via":call,"resolution":"SCENARIO_DECLARATION","declaration_evidence":matches,"original_source_expression":self.original(f)}));
                return;
            }
        }
        if let Some(ty) = self.cat.h3.globals.get(&name).filter(|_| !f.quoted) {
            let target = self.cat.reach.globals.get(&name);
            self.globals.push(json!({"name":name,"kind":"engine_global","h3_type":ty,"reach_type":target,"classification":if target==Some(ty){"DIRECT"}else if target.is_some(){"SIGNATURE_CHANGE"}else{"UNSUPPORTED"},"location":f.location,"enclosing_script":d.name,"original_source_expression":self.original(f)}));
            return;
        }
        if matches!(
            expected,
            Some("string") | Some("real") | Some("short") | Some("long") | Some("boolean")
        ) {
            return;
        }
        if let Some(matches) = self.symbols.get(&name) {
            let matches: Vec<_> = matches
                .iter()
                .filter(|r| r["category"] != "scripts" && r["category"] != "globals")
                .collect();
            if matches.is_empty() {
                return;
            }
            self.uses.push(json!({"symbol":name,"location":f.location,"enclosing_script":d.name,"expected_type":expected,"call":call,"matches":matches,"status":if matches.len()==1{"RESOLVED"}else{"AMBIGUOUS"}}));
        } else if expected.is_some_and(|t| {
            matches!(
                t,
                "object"
                    | "object_name"
                    | "unit"
                    | "vehicle"
                    | "device"
                    | "scenery"
                    | "weapon"
                    | "effect_scenery"
                    | "trigger_volume"
                    | "cutscene_flag"
                    | "cutscene_camera_point"
                    | "point_reference"
                    | "ai"
                    | "ai_command_script"
            )
        }) && !["none", "true", "false"].contains(&name.as_str())
            && name.parse::<f64>().is_err()
        {
            self.unknown.push(json!({"symbol":name,"location":f.location,"enclosing_script":d.name,"expected_type":expected,"call":call,"reason":"No matching scenario name or script declaration; dynamic and engine special symbols may remain"}));
        }
    }
    fn expression(
        &mut self,
        f: &Form,
        d: &Declaration,
        expected: Option<&str>,
        parent: Option<&str>,
        control: &[Value],
    ) {
        if f.atom.is_some() {
            self.atom(f, d, expected, parent);
            return;
        }
        let v = f.list();
        if v.is_empty() {
            return;
        }
        if v[0].children.is_some() {
            for child in v {
                self.expression(child, d, None, parent, control);
            }
            return;
        }
        let name = f.head().to_lowercase();
        let argc = v.len() - 1;
        let arg_evidence: Vec<_> = v[1..].iter().map(|f| self.infer(f, d, 0)).collect();
        let mut arg_types = vec![];
        let local = d.params.contains_key(&name);
        let declared = self.lookup.get(&name);
        let scenario_matches = self.symbols.get(&name);
        let engine = self.cat.h3.functions.contains_key(&name);
        let common = json!({"name":name,"location":f.location,"enclosing_script":d.name,"enclosing_script_kind":d.kind,"argument_count":argc,"expression":f,"original_source_expression":self.original(f),"control_flow":control});
        if local
            || declared.is_some()
            || scenario_matches.is_some_and(|r| {
                r.iter()
                    .any(|r| r["category"] == "scripts" || r["category"] == "globals")
            })
        {
            let mut row = common;
            row["resolution"] = json!(if local {
                "LOCAL_PARAMETER"
            } else if engine {
                "AMBIGUOUS_USER_ENGINE_COLLISION"
            } else if declared.is_some() {
                "USER_DECLARATION"
            } else {
                "SCENARIO_DECLARATION"
            });
            row["edge_kind"] = json!("call");
            row["declaration_locations"] = json!(
                declared
                    .into_iter()
                    .flatten()
                    .map(|d| &d.location)
                    .collect::<Vec<_>>()
            );
            row["declaration_evidence"] = json!(scenario_matches);
            if engine
                || local
                || declared.is_some_and(|r| r.iter().any(|d| d.kind == "global") || r.len() > 1)
            {
                self.diagnostics.push(json!({"code":"ambiguous_or_non_callable_symbol","call":row,"note":"Declaration evidence prevents engine classification; language precedence/callability needs compiler review"}));
            }
            // Preserve parameter declaration order from the AST, not a sorted map.
            if let Some(defs) = declared.filter(|d| d.len() == 1) {
                if let Some(form) = self
                    .sources
                    .forms
                    .iter()
                    .find(|f| f.location == defs[0].location)
                {
                    let signature = form.list().get(3).filter(|f| f.children.is_some());
                    if let Some(sig) = signature {
                        arg_types = sig.list()[1..]
                            .iter()
                            .map(|p| {
                                p.list()
                                    .first()
                                    .map(|f| f.text().to_owned())
                                    .unwrap_or_default()
                            })
                            .collect();
                    }
                }
            }
            self.script_calls.push(row);
        } else if scenario_matches.is_some() {
            let mut row = common;
            row["resolution"] = json!("AMBIGUOUS_SCENARIO_CALL");
            row["declaration_evidence"] = json!(scenario_matches);
            self.diagnostics
                .push(json!({"code":"scenario_symbol_in_call_position","call":row}));
        } else if !engine {
            let mut row = common;
            row["classification"] = json!("UNKNOWN");
            row["reason"] = json!(
                "Unresolved symbol, absent from H3 engine and user/scenario declarations; not counted as an engine function"
            );
            self.unresolved_calls.push(row);
        } else {
            let sigs = compat::best(&self.cat.h3.functions[&name], &arg_evidence);
            for i in 0..argc {
                let types: BTreeSet<_> =
                    sigs.iter().filter_map(|s| compat::argument(s, i)).collect();
                arg_types.push(if types.len() == 1 {
                    types.into_iter().next().unwrap().to_owned()
                } else {
                    String::new()
                });
            }
            let mut row = compat::classify(&name, &arg_evidence, self.cat, self.review);
            for (key, value) in common.as_object().unwrap() {
                row[key] = value.clone();
            }
            row["h3_signatures"] = json!(self.cat.h3.functions.get(&name));
            row["reach_signatures"] = json!(self.cat.reach.functions.get(&name));
            if row["mapping"]["argument_transform"]["items"]
                .as_array()
                .is_some_and(|items| items.iter().any(|i| i["op"] == "player_unit_to_player"))
            {
                let helper = v
                    .get(1)
                    .filter(|a| a.list().len() == 1)
                    .map(|a| a.head().to_lowercase());
                let bound = helper
                    .as_ref()
                    .and_then(|n| self.lookup.get(n))
                    .filter(|d| d.len() == 1)
                    .and_then(|defs| stock_player_slot(defs[0]).map(|slot| (defs[0], slot)));
                let verified = bound.is_some_and(|(d, slot)| d.name == format!("player{slot}"));
                row["transform_preconditions"] = json!({"resolved_stock_player_helper":verified,"helper":helper,"player_slot":bound.map(|(_,slot)|slot),"source_declaration":bound.map(|(d,_)|&d.location),"evidence":"AST shape: static unit helper whose only body is unit(list_get(players, fixed slot))","unmet_action":"no_emitted_replacement"});
            }
            self.calls.push(row);
        }
        if name == "cond" {
            for (i, clause) in v[1..].iter().enumerate() {
                let mut nested = control.to_vec();
                nested.push(json!({"operator":"cond","branch":i,"location":f.location}));
                for arg in clause.list() {
                    self.expression(arg, d, None, Some(&name), &nested);
                }
            }
        } else {
            for (i, arg) in v[1..].iter().enumerate() {
                let mut nested = control.to_vec();
                if matches!(name.as_str(), "if" | "sleep_until" | "and" | "or") {
                    nested.push(json!({"operator":name,"argument":i,"location":f.location}));
                }
                self.expression(
                    arg,
                    d,
                    arg_types
                        .get(i)
                        .filter(|s| !s.is_empty())
                        .map(String::as_str),
                    Some(&name),
                    &nested,
                );
            }
        }
    }
}
pub fn analyze(
    sources: &Sources,
    raw_cat: &Catalogue,
    symbols: &BTreeMap<String, Vec<Value>>,
) -> Value {
    let review = compat::bundled();
    let cat = compat::supplemented(raw_cat, &review);
    let declarations: Vec<_> = sources.forms.iter().filter_map(declaration).collect();
    let mut lookup: BTreeMap<String, Vec<&Declaration>> = BTreeMap::new();
    for d in &declarations {
        lookup.entry(d.name.clone()).or_default().push(d);
    }
    let mut walk = Walk {
        sources,
        cat: &cat,
        review: &review,
        symbols,
        lookup,
        calls: vec![],
        uses: vec![],
        globals: vec![],
        script_calls: vec![],
        unknown: vec![],
        diagnostics: sources.diagnostics.clone(),
        unresolved_calls: vec![],
    };
    for (name, defs) in &walk.lookup {
        if defs.len() > 1 {
            walk.diagnostics.push(json!({"code":"duplicate_declaration","name":name,"locations":defs.iter().map(|d|&d.location).collect::<Vec<_>>(),"note":"Stub/static or include precedence is not assumed"}));
        }
    }
    for f in &sources.forms {
        if declaration(f).is_none() {
            walk.diagnostics.push(
                json!({"code":"unhandled_top_level_form","location":f.location,"head":f.head()}),
            );
        }
    }
    for d in &declarations {
        for f in &d.body {
            walk.expression(f, d, None, None, &[]);
        }
    }
    super::hsc_context::apply(&mut walk.calls, sources);
    super::hsc_context::apply(&mut walk.unresolved_calls, sources);
    let mut inventory: BTreeMap<String, Value> = BTreeMap::new();
    for call in &walk.calls {
        let name = call["name"].as_str().unwrap();
        let row=inventory.entry(name.into()).or_insert_with(||json!({"name":name,"call_count":0,"classifications":[],"raw_classifications":[],"documented_h3":true}));
        row["call_count"] = json!(row["call_count"].as_u64().unwrap() + 1);
        for (key, value) in [
            ("classifications", &call["classification"]),
            (
                "raw_classifications",
                &call["raw_name_match"]["classification"],
            ),
        ] {
            let list = row[key].as_array_mut().unwrap();
            if !list.contains(value) {
                list.push(value.clone());
                list.sort_by_key(Value::to_string);
            }
        }
    }
    for row in inventory.values_mut() {
        row["classification"] = json!(compat::aggregate(
            row["classifications"].as_array().unwrap()
        ));
        row["raw_classification"] = json!(compat::aggregate(
            row["raw_classifications"].as_array().unwrap()
        ));
    }
    let used: BTreeSet<_> = walk
        .calls
        .iter()
        .filter_map(|r| r["mapping"]["id"].as_str().map(str::to_owned))
        .collect();
    let translation_plan:Vec<_>=walk.calls.iter().map(|c|json!({"source_function":c["name"],"source_location":c["location"],"enclosing_script":c["enclosing_script"],"source_expression":c["expression"],"original_source_expression":c["original_source_expression"],"source_overload_candidates":c["source_overload_candidates"],"target_overload_candidates":c["target_overload_candidates"],"target_function":c["proposed_reach_counterpart"],"replacement":c["mapping"]["replacement"],"compatibility":c["classification"],"mapping_id":c["mapping"]["id"],"transform_preconditions":c["transform_preconditions"],"argument_transform":if c["transform_preconditions"]["resolved_stock_player_helper"]==false{json!({"op":"no_emitted_replacement","reason":"unmet_source_helper_precondition"})}else if c["classification"]=="DIRECT"{json!({"op":"identity"})}else{c["mapping"]["argument_transform"].as_object().map(|v|json!(v)).unwrap_or_else(||json!({"op":"no_emitted_replacement"}))},"return_transform":if c["classification"]=="DIRECT"{json!({"op":"identity"})}else{c["mapping"]["return_transform"].clone()},"signature_match":c["signature_match"],"confidence":c["confidence"]})).collect();
    let unsupported: Vec<_> = walk
        .calls
        .iter()
        .filter(|r| r["classification"] != "DIRECT")
        .collect();
    let globals: BTreeSet<_> = walk
        .globals
        .iter()
        .filter(|r| r["kind"] == "engine_global")
        .map(|r| r["name"].as_str().unwrap())
        .collect();
    let mut blocker_counts: BTreeMap<String, usize> = BTreeMap::new();
    for call in walk
        .calls
        .iter()
        .chain(&walk.unresolved_calls)
        .filter(|r| r["requires_review"] == true)
    {
        *blocker_counts
            .entry(
                call["blocker_severity"]
                    .as_str()
                    .unwrap_or("UNKNOWN")
                    .into(),
            )
            .or_default() += 1;
    }
    json!({"files":sources.files,"declarations":declarations.iter().map(|d|json!({"name":d.name,"kind":d.kind,"return_type":d.result,"parameters":d.params,"location":d.location})).collect::<Vec<_>>(),
      "engine_functions":inventory.values().collect::<Vec<_>>(),"call_sites":walk.calls,"unsupported_call_sites":unsupported,"user_script_calls":walk.script_calls,"unresolved_call_sites":walk.unresolved_calls,"globals":walk.globals,"scenario_symbol_uses":walk.uses,"unresolved_symbols":walk.unknown,"diagnostics":walk.diagnostics,
      "summary":{"source_files":sources.files.len(),"analyzed_source_files":sources.files.iter().filter(|f|f["scope"]!="discovered_not_in_scenario_source_table").count(),"declarations":declarations.len(),"unique_engine_functions":inventory.len(),"unique_engine_globals":globals.len(),"engine_call_sites":walk.calls.len(),"unresolved_call_sites":walk.unresolved_calls.len(),"function_classifications":compat::counts(inventory.values(),"classification"),"raw_function_classifications":compat::counts(inventory.values(),"raw_classification"),"call_site_classifications":compat::counts(walk.calls.iter(),"classification"),"script_blocker_call_sites":blocker_counts,"classification_count_basis":"One conservative classification per documented engine name: UNSUPPORTED > UNKNOWN > STUB_CANDIDATE > EMULATABLE > SIGNATURE_CHANGE > RENAMED > DIRECT. All observed call classifications are retained; unresolved names are separate."},
      "transpiler_mappings":{"format":"foundry.hsc-transpiler-mappings","version":1,"source_game":"halo3","target_game":"reach","source_rewriting_performed":false,"reviewed_catalogue":review,"used_mapping_ids":used,"call_mappings":translation_plan},
      "catalogue_evidence":raw_cat.evidence,"resolution_policy":"Local parameter, physical user declaration, scenario compiled declaration/symbol, engine primitive. Colliding declarations or non-callable symbols are diagnosed, not sent to engine compatibility. Generated bodies and compiler precedence are not invented.","limitations":["Static source inventory and partial type inference; no runtime reachability or compiler include proof","DIRECT means documented active signature compatibility, not identical semantics or resource bindings","Unknown overloads and unknown source calls remain explicit","Compiled scenario declarations identify generated scripts without reconstructing their bodies"]})
}
