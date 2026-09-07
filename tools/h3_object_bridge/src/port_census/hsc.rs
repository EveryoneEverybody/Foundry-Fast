//! HaloScript census parser. No code execution or source rewriting.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Location {
    pub file: String,
    pub line: usize,
    pub column: usize,
    pub byte: usize,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Form {
    pub location: Location,
    pub end_byte: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub atom: Option<String>,
    pub quoted: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub children: Option<Vec<Form>>,
}
impl Form {
    fn text(&self) -> &str {
        self.atom.as_deref().unwrap_or("")
    }
    fn list(&self) -> &[Form] {
        self.children.as_deref().unwrap_or(&[])
    }
    fn head(&self) -> &str {
        self.list().first().map(Form::text).unwrap_or("")
    }
}
struct Parser<'a> {
    text: &'a str,
    file: String,
    at: usize,
    line: usize,
    column: usize,
    diagnostics: Vec<Value>,
    nodes: usize,
}
impl Parser<'_> {
    fn loc(&self) -> Location {
        Location {
            file: self.file.clone(),
            line: self.line,
            column: self.column,
            byte: self.at,
        }
    }
    fn peek(&self) -> Option<char> {
        self.text[self.at..].chars().next()
    }
    fn advance(&mut self) -> Option<char> {
        let c = self.peek()?;
        self.at += c.len_utf8();
        if c == '\n' {
            self.line += 1;
            self.column = 1;
        } else {
            self.column += 1;
        }
        Some(c)
    }
    fn error(&mut self, code: &str, location: Location) {
        self.diagnostics
            .push(json!({"code":code,"location":location}));
    }
    fn whitespace(&mut self) {
        loop {
            while self.peek().is_some_and(char::is_whitespace) || self.peek() == Some('\u{feff}') {
                self.advance();
            }
            if self.text[self.at..].starts_with(";*") {
                let loc = self.loc();
                self.advance();
                self.advance();
                let mut depth = 1;
                while self.peek().is_some() && depth > 0 {
                    if self.text[self.at..].starts_with(";*") {
                        depth += 1;
                        self.advance();
                        self.advance();
                    } else if self.text[self.at..].starts_with("*;") {
                        depth -= 1;
                        self.advance();
                        self.advance();
                    } else {
                        self.advance();
                    }
                }
                if depth > 0 {
                    self.error("unterminated_block_comment", loc);
                }
            } else if self.peek() == Some(';') {
                while self.peek().is_some_and(|c| c != '\n') {
                    self.advance();
                }
            } else {
                break;
            }
        }
    }
    fn form(&mut self, depth: usize) -> Option<Form> {
        self.whitespace();
        let location = self.loc();
        let c = self.peek()?;
        if depth > 256 || self.nodes >= 2_000_000 {
            self.error("parser_budget_exceeded", location);
            self.at = self.text.len();
            return None;
        }
        self.nodes += 1;
        if c == ')' {
            self.error("unexpected_close_paren", location);
            self.advance();
            return None;
        }
        if c == '(' {
            self.advance();
            let mut children = Vec::new();
            loop {
                self.whitespace();
                if self.peek() == Some(')') {
                    self.advance();
                    break;
                }
                if self.peek().is_none() {
                    self.error("unterminated_form", location.clone());
                    break;
                }
                if let Some(f) = self.form(depth + 1) {
                    children.push(f);
                }
            }
            Some(Form {
                location,
                end_byte: self.at,
                atom: None,
                quoted: false,
                children: Some(children),
            })
        } else if c == '"' {
            self.advance();
            let mut atom = String::new();
            let mut closed = false;
            while let Some(c) = self.advance() {
                if c == '"' {
                    closed = true;
                    break;
                }
                if c == '\\' && matches!(self.peek(), Some('"') | Some('\\')) {
                    atom.push(self.advance().unwrap());
                } else {
                    atom.push(c);
                }
            }
            if !closed {
                self.error("unterminated_string", location.clone());
            }
            Some(Form {
                location,
                end_byte: self.at,
                atom: Some(atom),
                quoted: true,
                children: None,
            })
        } else {
            let start = self.at;
            while self
                .peek()
                .is_some_and(|c| !c.is_whitespace() && !['(', ')', ';', '"'].contains(&c))
            {
                self.advance();
            }
            Some(Form {
                location,
                end_byte: self.at,
                atom: Some(self.text[start..self.at].into()),
                quoted: false,
                children: None,
            })
        }
    }
}
pub fn parse(file: &str, text: &str) -> (Vec<Form>, Vec<Value>) {
    let mut parser = Parser {
        text,
        file: file.into(),
        at: 0,
        line: 1,
        column: 1,
        diagnostics: vec![],
        nodes: 0,
    };
    let mut forms = Vec::new();
    while parser.at < text.len() {
        if let Some(f) = parser.form(0) {
            forms.push(f);
        }
    }
    (forms, parser.diagnostics)
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Signature {
    pub result: String,
    pub args: Vec<String>,
    pub raw: String,
    pub min_args: usize,
    pub max_args: Option<usize>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
pub struct Profile {
    pub functions: BTreeMap<String, Vec<Signature>>,
    pub globals: BTreeMap<String, String>,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct Catalogue {
    pub format: String,
    pub version: u32,
    pub evidence: Value,
    pub h3: Profile,
    pub reach: Profile,
}
impl Catalogue {
    pub fn bundled() -> Self {
        serde_json::from_str(include_str!("../../data/hsc_signatures.json"))
            .expect("bundled HSC catalogue")
    }
}

pub fn compatibility(name: &str, argc: usize, cat: &Catalogue) -> (&'static str, String) {
    let Some(source) = cat.h3.functions.get(name) else {
        return ("UNKNOWN","Name is absent from the supplied H3 catalogue; may be an external script or undocumented function".into());
    };
    let usable: Vec<_> = source
        .iter()
        .filter(|s| argc >= s.min_args && s.max_args.is_none_or(|n| argc <= n))
        .collect();
    if usable.is_empty() {
        return (
            "UNKNOWN",
            "No documented H3 overload accepts this argument count".into(),
        );
    }
    if let Some(target) = cat.reach.functions.get(name) {
        if usable.iter().any(|a| {
            target.iter().any(|b| {
                a.result == b.result
                    && a.args == b.args
                    && a.min_args == b.min_args
                    && a.max_args == b.max_args
            })
        }) {
            return ("DIRECT","Documented overload matches; argument expression types and runtime behavior are not validated".into());
        }
        return (
            "SIGNATURE_CHANGE",
            "Name exists in Reach but no identical documented overload matches this call".into(),
        );
    }
    if name.starts_with("cortana_") && usable.iter().all(|s| s.result == "void") {
        return ("STUB_CANDIDATE","Absent from the Reach catalogue; review Cortana presentation and call-site control flow before a void stub".into());
    }
    (
        "UNSUPPORTED",
        "Documented in H3 and absent from the supplied Reach catalogue; no reviewed counterpart"
            .into(),
    )
}

#[derive(Clone)]
struct Declaration {
    name: String,
    kind: String,
    result: String,
    params: BTreeMap<String, String>,
    location: Location,
    body: Vec<Form>,
}
fn declaration(form: &Form) -> Option<Declaration> {
    let v = form.list();
    if form.head() == "global" && v.len() >= 4 {
        return Some(Declaration {
            name: v[2].text().to_lowercase(),
            kind: "global".into(),
            result: v[1].text().into(),
            params: BTreeMap::new(),
            location: form.location.clone(),
            body: v[3..].to_vec(),
        });
    }
    if form.head() != "script" || v.len() < 4 {
        return None;
    }
    let kind = v[1].text();
    let typed = matches!(kind, "static" | "stub");
    let i = if typed { 3 } else { 2 };
    let name = v.get(i)?;
    let mut params = BTreeMap::new();
    let name = if name.children.is_some() {
        for p in &name.list()[1..] {
            if p.list().len() == 2 {
                params.insert(p.list()[1].text().to_lowercase(), p.list()[0].text().into());
            }
        }
        name.head()
    } else {
        name.text()
    };
    if name.is_empty() {
        return None;
    }
    Some(Declaration {
        name: name.to_lowercase(),
        kind: kind.into(),
        result: if typed {
            v[2].text().into()
        } else {
            "void".into()
        },
        params,
        location: form.location.clone(),
        body: v[i + 1..].to_vec(),
    })
}

#[derive(Default)]
pub struct Sources {
    pub files: Vec<Value>,
    pub forms: Vec<Form>,
    pub diagnostics: Vec<Value>,
}
impl Sources {
    pub fn add(&mut self, path: &str, text: &str, scope: &str) {
        let (forms, errors) = parse(path, text);
        self.files.push(json!({"path":path,"scope":scope,"bytes":text.len(),"sha256":super::digest(text.as_bytes()),"forms":forms.len(),"diagnostics":errors.len(),"ast":forms}));
        if scope != "discovered_not_in_scenario_source_table" {
            self.forms.extend(forms);
            self.diagnostics.extend(errors);
        }
    }
    pub fn analyze(&self, cat: &Catalogue, symbols: &BTreeMap<String, Vec<Value>>) -> Value {
        let declarations: Vec<_> = self.forms.iter().filter_map(declaration).collect();
        let mut lookup: BTreeMap<String, Vec<&Declaration>> = BTreeMap::new();
        for d in &declarations {
            lookup.entry(d.name.clone()).or_default().push(d);
        }
        let mut calls = Vec::new();
        let mut symbol_uses = Vec::new();
        let mut global_uses = Vec::new();
        let mut script_calls = Vec::new();
        let mut unknown = Vec::new();
        let mut diagnostics = self.diagnostics.clone();
        for (name, defs) in &lookup {
            if defs.len() > 1 {
                diagnostics.push(json!({"code":"duplicate_declaration","name":name,"locations":defs.iter().map(|d|&d.location).collect::<Vec<_>>(),"note":"Source discovery does not prove which files the compiler includes"}));
            }
        }
        for form in &self.forms {
            if declaration(form).is_none() {
                diagnostics.push(json!({"code":"unhandled_top_level_form","location":form.location,"head":form.head()}));
            }
        }
        struct Walk<'a> {
            cat: &'a Catalogue,
            symbols: &'a BTreeMap<String, Vec<Value>>,
            lookup: &'a BTreeMap<String, Vec<&'a Declaration>>,
            calls: &'a mut Vec<Value>,
            uses: &'a mut Vec<Value>,
            globals: &'a mut Vec<Value>,
            script_calls: &'a mut Vec<Value>,
            unknown: &'a mut Vec<Value>,
        }
        impl Walk<'_> {
            fn atom(
                &mut self,
                f: &Form,
                d: &Declaration,
                expected: Option<&str>,
                call: Option<&str>,
            ) {
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
                        self.globals.push(json!({"name":name,"kind":"user_global","location":f.location,"enclosing_script":d.name}));
                    }
                    return;
                }
                if let Some(ty) = self.cat.h3.globals.get(&name).filter(|_| !f.quoted) {
                    let target = self.cat.reach.globals.get(&name);
                    self.globals.push(json!({"name":name,"kind":"engine_global","h3_type":ty,"reach_type":target,"classification":if target==Some(ty){"DIRECT"}else if target.is_some(){"SIGNATURE_CHANGE"}else{"UNSUPPORTED"},"location":f.location,"enclosing_script":d.name}));
                    return;
                }
                let required = expected.is_some_and(|t| {
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
                });
                if matches!(
                    expected,
                    Some("string") | Some("real") | Some("short") | Some("long") | Some("boolean")
                ) {
                    return;
                }
                let matches = self.symbols.get(&name);
                if let Some(matches) = matches {
                    self.uses.push(json!({"symbol":name,"location":f.location,"enclosing_script":d.name,"expected_type":expected,"call":call,"matches":matches,"status":if matches.len()==1{"RESOLVED"}else{"AMBIGUOUS"}}));
                } else if required
                    && !["none", "true", "false"].contains(&name.as_str())
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
                call: Option<&str>,
            ) {
                if f.atom.is_some() {
                    self.atom(f, d, expected, call);
                    return;
                }
                let v = f.list();
                if v.is_empty() {
                    return;
                }
                if v[0].children.is_some() {
                    for child in v {
                        self.expression(child, d, None, call);
                    }
                    return;
                }
                let name = f.head().to_lowercase();
                let argc = v.len() - 1;
                let mut arg_types: Vec<String> = vec![];
                if let Some(defs) = self.lookup.get(&name) {
                    self.script_calls.push(json!({"name":name,"location":f.location,"enclosing_script":d.name,"argument_count":argc,"declaration_locations":defs.iter().map(|x|&x.location).collect::<Vec<_>>() }));
                } else {
                    let (classification, reason) = compatibility(&name, argc, self.cat);
                    let sigs: Vec<_> = self
                        .cat
                        .h3
                        .functions
                        .get(&name)
                        .into_iter()
                        .flatten()
                        .filter(|s| argc >= s.min_args && s.max_args.is_none_or(|n| argc <= n))
                        .collect();
                    if let Some(first) = sigs.first() {
                        if sigs.iter().all(|s| s.args == first.args) {
                            arg_types = first.args.clone();
                        }
                    }
                    self.calls.push(json!({"name":name,"location":f.location,"enclosing_script":d.name,"argument_count":argc,"classification":classification,"reason":reason,"expression":f,"h3_signatures":self.cat.h3.functions.get(&name),"reach_signatures":self.cat.reach.functions.get(&name),"evidence":"documented_signature_comparison","proven_target_status":"NOT_TESTED","mission_impact":if classification=="STUB_CANDIDATE"{"presentation_candidate_requires_review"}else if classification=="UNSUPPORTED"{"control_flow_review_required"}else{"unknown"},"tentative_mvp_policy":if classification=="STUB_CANDIDATE"{"STUB_VOID"}else if classification=="UNSUPPORTED"{"MANUAL"}else{"REVIEW"}}));
                }
                if name == "cond" {
                    for clause in &v[1..] {
                        for arg in clause.list() {
                            self.expression(arg, d, None, Some(&name));
                        }
                    }
                } else {
                    for (i, arg) in v[1..].iter().enumerate() {
                        self.expression(arg, d, arg_types.get(i).map(String::as_str), Some(&name));
                    }
                }
            }
        }
        let mut walk = Walk {
            cat,
            symbols,
            lookup: &lookup,
            calls: &mut calls,
            uses: &mut symbol_uses,
            globals: &mut global_uses,
            script_calls: &mut script_calls,
            unknown: &mut unknown,
        };
        for d in &declarations {
            for f in &d.body {
                walk.expression(f, d, None, None);
            }
        }
        let mut inventory: BTreeMap<String, Value> = BTreeMap::new();
        let mut counts: BTreeMap<String, usize> = BTreeMap::new();
        for call in &calls {
            let name = call["name"].as_str().unwrap();
            let row=inventory.entry(name.into()).or_insert_with(||json!({"name":name,"call_count":0,"classifications":[],"documented_h3":cat.h3.functions.contains_key(name)}));
            row["call_count"] = json!(row["call_count"].as_u64().unwrap() + 1);
            if !row["classifications"]
                .as_array()
                .unwrap()
                .contains(&call["classification"])
            {
                row["classifications"]
                    .as_array_mut()
                    .unwrap()
                    .push(call["classification"].clone());
            }
        }
        for row in inventory.values() {
            for status in row["classifications"].as_array().unwrap() {
                *counts.entry(status.as_str().unwrap().into()).or_default() += 1;
            }
        }
        let engine_count = inventory
            .values()
            .filter(|r| r["documented_h3"] == true)
            .count();
        let unsupported: Vec<_> = calls
            .iter()
            .filter(|r| r["classification"] != "DIRECT")
            .cloned()
            .collect();
        let names: BTreeSet<_> = global_uses
            .iter()
            .filter(|r| r["kind"] == "engine_global")
            .map(|r| r["name"].clone().to_string())
            .collect();
        json!({"files":self.files,"declarations":declarations.iter().map(|d|json!({"name":d.name,"kind":d.kind,"return_type":d.result,"parameters":d.params,"location":d.location})).collect::<Vec<_>>(),
            "engine_functions":inventory.values().collect::<Vec<_>>(),"call_sites":calls,"unsupported_call_sites":unsupported,"user_script_calls":script_calls,"globals":global_uses,"scenario_symbol_uses":symbol_uses,"unresolved_symbols":unknown,"diagnostics":diagnostics,
            "summary":{"source_files":self.files.len(),"analyzed_source_files":self.files.iter().filter(|f| f["scope"]!="discovered_not_in_scenario_source_table").count(),"declarations":declarations.len(),"unique_engine_functions":engine_count,"unique_engine_globals":names.len(),"function_classifications":counts,"classification_count_basis":"Unique function names per observed call classification, including unknown names; a name can occur in multiple classifications"},
            "catalogue_evidence":cat.evidence,"limitations":["Static source inventory, not compiler include resolution or execution reachability","DIRECT compares documented overloads and argument counts, not expression types or runtime equivalence","Unresolved calls may be external shared scripts or undocumented functions; no guessed renames or emulation"]})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn nested_comments_strings_and_locations() {
        let (forms, errors) = parse(
            "x.hsc",
            "; ignored\n;* outer ;* inner *; *;\n(script static void (foo (short n)) (print \"a; (b)\") (sleep n))",
        );
        assert!(errors.is_empty());
        assert_eq!(forms.len(), 1);
        assert_eq!(forms[0].location.line, 3);
        let d = declaration(&forms[0]).unwrap();
        assert_eq!(d.name, "foo");
        assert_eq!(d.params["n"], "short");
        assert_eq!(d.body[0].list()[1].text(), "a; (b)");
    }
    #[test]
    fn malformed_forms_are_diagnostics() {
        let (f, e) = parse("bad", ") (print \"oops");
        assert_eq!(f.len(), 1);
        assert_eq!(e.len(), 3);
    }
    #[test]
    fn quoted_paths_preserve_backslashes() {
        let (f, e) = parse("p", "(f \"sound\\dialog\\thing\")");
        assert!(e.is_empty());
        assert_eq!(f[0].list()[1].text(), "sound\\dialog\\thing");
    }
    #[test]
    fn engine_and_user_functions_and_typed_symbols() {
        let cat = Catalogue::bundled();
        let mut source = Sources::default();
        source.add("x","(script static void helper (sleep 1))\n(script startup go (helper) (volume_test_players tv_start) (cortana_effect_kill))","mission");
        let symbols = BTreeMap::from([(
            "tv_start".into(),
            vec![json!({"category":"trigger volumes"})],
        )]);
        let r = source.analyze(&cat, &symbols);
        assert_eq!(r["user_script_calls"].as_array().unwrap().len(), 1);
        assert_eq!(r["scenario_symbol_uses"].as_array().unwrap().len(), 1);
        assert!(
            r["unsupported_call_sites"]
                .as_array()
                .unwrap()
                .iter()
                .any(|x| x["name"] == "cortana_effect_kill")
        );
        assert_eq!(r["declarations"][1]["location"]["line"], 2);
    }
    #[test]
    fn unknown_never_becomes_direct() {
        assert_eq!(
            compatibility("made_up_function", 0, &Catalogue::bundled()).0,
            "UNKNOWN"
        );
    }
    #[test]
    fn quoted_text_is_not_an_engine_global() {
        let mut s = Sources::default();
        s.add("x", "(script startup go (print \"game_speed\"))", "mission");
        let r = s.analyze(&Catalogue::bundled(), &BTreeMap::new());
        assert!(r["globals"].as_array().unwrap().is_empty());
    }
    #[test]
    fn cond_branches_are_not_function_calls() {
        let mut s = Sources::default();
        s.add(
            "x",
            "(script startup go (cond ((= 1 1) (sleep 1)) (true (sleep 2))))",
            "mission",
        );
        let r = s.analyze(&Catalogue::bundled(), &BTreeMap::new());
        assert!(
            !r["engine_functions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|x| x["name"] == "true")
        );
    }
}
