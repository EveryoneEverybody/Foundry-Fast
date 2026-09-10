//! HaloScript census parser. No code execution or source rewriting.
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;

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
    pub(super) fn text(&self) -> &str {
        self.atom.as_deref().unwrap_or("")
    }
    pub(super) fn list(&self) -> &[Form] {
        self.children.as_deref().unwrap_or(&[])
    }
    pub(super) fn head(&self) -> &str {
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

#[cfg(test)]
pub fn compatibility(name: &str, argc: usize, cat: &Catalogue) -> (String, String) {
    let review = super::hsc_compat::bundled();
    let cat = super::hsc_compat::supplemented(cat, &review);
    let r = super::hsc_compat::classify(name, &vec![vec![]; argc], &cat, &review);
    (
        r["classification"].as_str().unwrap().into(),
        r["reason"].as_str().unwrap().into(),
    )
}

#[derive(Clone)]
pub(super) struct Declaration {
    pub(super) name: String,
    pub(super) kind: String,
    pub(super) result: String,
    pub(super) params: BTreeMap<String, String>,
    pub(super) location: Location,
    pub(super) body: Vec<Form>,
}
pub(super) fn declaration(form: &Form) -> Option<Declaration> {
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
    pub texts: BTreeMap<String, String>,
}
impl Sources {
    pub fn add(&mut self, path: &str, text: &str, scope: &str) {
        self.texts.insert(path.into(), text.into());
        let (forms, errors) = parse(path, text);
        self.files.push(json!({"path":path,"scope":scope,"bytes":text.len(),"sha256":super::digest(text.as_bytes()),"forms":forms.len(),"diagnostics":errors.len(),"ast":forms}));
        if scope != "discovered_not_in_scenario_source_table" {
            self.forms.extend(forms);
            self.diagnostics.extend(errors);
        }
    }
    pub fn analyze(&self, cat: &Catalogue, symbols: &BTreeMap<String, Vec<Value>>) -> Value {
        super::hsc_analysis::analyze(self, cat, symbols)
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
