//! Reviewed, overload-specific proposals. This module never emits HaloScript.
use super::hsc::{Catalogue, Signature};
use serde_json::{Value, json};
use std::collections::BTreeMap;

pub const CLASSES: [&str; 7] = [
    "DIRECT",
    "RENAMED",
    "SIGNATURE_CHANGE",
    "EMULATABLE",
    "STUB_CANDIDATE",
    "UNSUPPORTED",
    "UNKNOWN",
];
pub fn bundled() -> Value {
    serde_json::from_str(include_str!("../../data/hsc_compatibility.json"))
        .expect("reviewed HSC mappings")
}
pub fn supplemented(cat: &Catalogue, review: &Value) -> Catalogue {
    let mut out = cat.clone();
    for row in review["signature_supplements"]
        .as_array()
        .into_iter()
        .flatten()
    {
        let profile = if row["game"] == "h3" {
            &mut out.h3
        } else {
            &mut out.reach
        };
        let sig: Signature =
            serde_json::from_value(row["signature"].clone()).expect("reviewed signature");
        let signatures = profile
            .functions
            .entry(row["function"].as_str().unwrap().into())
            .or_default();
        if !signatures.iter().any(|s| same(s, &sig)) {
            signatures.push(sig);
        }
    }
    out
}
pub fn accepts(s: &Signature, argc: usize) -> bool {
    argc >= s.min_args && s.max_args.is_none_or(|n| argc <= n)
}
pub fn argument(s: &Signature, index: usize) -> Option<&str> {
    s.args
        .get(index)
        .or_else(|| {
            if s.max_args.is_none() {
                s.args.last()
            } else {
                None
            }
        })
        .map(String::as_str)
}
fn normalized(t: &str) -> &str {
    match t {
        "number(s)" => "number",
        "expression(s)" => "expression",
        "boolean(s)" => "boolean",
        "script name" => "script",
        _ => t,
    }
}
pub fn same(a: &Signature, b: &Signature) -> bool {
    a.result == b.result && a.args == b.args && a.min_args == b.min_args && a.max_args == b.max_args
}
/// Cost 0 is identical, 1 is a source-language conversion/contextual literal,
/// 2 is unknown. A definite mismatch is never hidden by an arity match.
fn type_cost(actual: &[String], expected: &str) -> Option<usize> {
    let expected = normalized(expected);
    if actual.is_empty() {
        return Some(2);
    }
    if matches!(
        expected,
        "expression"
            | "passthrough"
            | "variable name"
            | "any"
            | "then"
            | "else"
            | "result1"
            | "result2"
    ) {
        return Some(1);
    }
    actual
        .iter()
        .filter_map(|a| {
            let a = normalized(a);
            if a == expected {
                return Some(0);
            }
            if matches!(a, "integer_literal" | "boolean_integer_literal")
                && matches!(expected, "short" | "long" | "real" | "number")
            {
                return Some(1);
            }
            if a == "boolean_integer_literal" && expected == "boolean" {
                return Some(1);
            }
            if a == "game_difficulty" && matches!(expected, "number" | "short" | "long") {
                return Some(1);
            }
            if a == "symbol_literal" && expected == "string_id" {
                return Some(1);
            }
            if a == "unresolved_typed_name"
                && !matches!(
                    expected,
                    "boolean" | "number" | "short" | "long" | "real" | "void"
                )
            {
                return Some(2);
            }
            if a == "real_literal" && matches!(expected, "real" | "number") {
                return Some(1);
            }
            if a == "quoted_atom"
                && !matches!(
                    expected,
                    "short" | "long" | "real" | "number" | "boolean" | "void"
                )
            {
                return Some(1);
            }
            if a == "none"
                && !matches!(
                    expected,
                    "short" | "long" | "real" | "number" | "boolean" | "void"
                )
            {
                return Some(1);
            }
            // HSC expressions are coerced in the expected numeric context. A
            // numeric result is not a proof of range safety.
            if matches!(a, "short" | "long" | "real" | "number")
                && matches!(expected, "short" | "long" | "real" | "number")
            {
                return Some(1);
            }
            if expected == "object"
                && matches!(
                    a,
                    "object_name"
                        | "unit"
                        | "vehicle"
                        | "device"
                        | "scenery"
                        | "weapon"
                        | "effect_scenery"
                        | "ai"
                )
            {
                return Some(1);
            }
            if expected == "unit" && matches!(a, "vehicle" | "ai" | "object") {
                return Some(1);
            }
            // Single-object and AI expressions occur in stock object-list inputs
            // (040_voi vehicle seat tests); do not equate the signature types.
            if expected == "object_list" && matches!(a, "object" | "unit" | "vehicle" | "ai") {
                return Some(1);
            }
            None
        })
        .min()
}
pub fn best<'a>(sigs: &'a [Signature], args: &[Vec<String>]) -> Vec<&'a Signature> {
    let mut ranked: Vec<(usize, &Signature)> = Vec::new();
    for s in sigs.iter().filter(|s| accepts(s, args.len())) {
        let cost: Option<usize> = args
            .iter()
            .enumerate()
            .map(|(i, a)| argument(s, i).and_then(|t| type_cost(a, t)))
            .sum();
        if let Some(cost) = cost {
            if !ranked.iter().any(|(_, previous)| same(s, previous)) {
                ranked.push((cost, s));
            }
        }
    }
    let min = ranked.iter().map(|r| r.0).min();
    ranked
        .into_iter()
        .filter(|r| Some(r.0) == min)
        .map(|r| r.1)
        .collect()
}
fn same_call_signature(a: &Signature, b: &Signature, argc: usize) -> bool {
    accepts(b, argc)
        && a.result == b.result
        && (0..argc).all(|i| argument(a, i).map(normalized) == argument(b, i).map(normalized))
}
pub fn classify(name: &str, args: &[Vec<String>], cat: &Catalogue, review: &Value) -> Value {
    let source = cat.h3.functions.get(name).map(Vec::as_slice).unwrap_or(&[]);
    let candidates = best(source, args);
    let targets = cat
        .reach
        .functions
        .get(name)
        .map(Vec::as_slice)
        .unwrap_or(&[]);
    let raw = if source.is_empty() {
        "UNKNOWN"
    } else if targets.is_empty() {
        "UNSUPPORTED"
    } else if source.iter().filter(|s| accepts(s, args.len())).any(|s| {
        targets
            .iter()
            .any(|t| same_call_signature(s, t, args.len()))
    }) {
        "DIRECT"
    } else {
        "SIGNATURE_CHANGE"
    };
    let mut result = json!({"classification":"UNKNOWN","raw_name_match":{"same_name_reach_function":!targets.is_empty(),"classification":raw},"signature_match":"incompatible signature","source_overload_candidates":candidates,"target_overload_candidates":[],"proposed_reach_counterpart":null,"mapping":null,"argument_types":args,"evidence":[],"confidence":"UNKNOWN","fidelity_compatibility":"UNKNOWN","reason":"No H3 overload matches the observed argument count and known types","proven_target_status":"NOT_TESTED"});
    if candidates.is_empty() {
        return result;
    }
    if candidates.len() > 1 {
        result["signature_match"] = json!("ambiguous overload");
        result["reason"] =
            json!("Multiple equally supported H3 overloads remain; no arbitrary overload selected");
        return result;
    }
    let source = candidates[0];
    let mappings: Vec<_> = review["mappings"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|r| {
            r["source_function"] == name
                && serde_json::from_value::<Signature>(r["source_signature"].clone())
                    .is_ok_and(|s| same(&s, source))
        })
        .collect();
    if mappings.len() > 1 {
        result["reason"] = json!("Conflicting reviewed mappings; catalogue requires review");
        return result;
    }
    if let Some(mapping) = mappings.first() {
        if let Some(target) = mapping["target_function"].as_str() {
            let valid = serde_json::from_value::<Signature>(mapping["target_signature"].clone())
                .ok()
                .is_some_and(|sig| {
                    cat.reach
                        .functions
                        .get(target)
                        .is_some_and(|sigs| sigs.iter().any(|s| same(s, &sig)))
                });
            if !valid {
                result["reason"] =
                    json!("Reviewed target signature is absent from the supplied Reach catalogue");
                return result;
            }
        }
        result["classification"] = mapping["mapping_kind"].clone();
        result["mapping"] = (*mapping).clone();
        result["proposed_reach_counterpart"] = mapping["target_function"].clone();
        result["target_overload_candidates"] = if mapping["target_signature"].is_null() {
            json!([])
        } else {
            json!([mapping["target_signature"]])
        };
        for field in ["evidence", "confidence", "fidelity_compatibility"] {
            result[field] = mapping[field].clone();
        }
        result["reason"] = mapping["notes"].clone();
        result["signature_match"] = json!(match mapping["mapping_kind"].as_str().unwrap() {
            "RENAMED" | "SAME" => "compatible signature",
            "SIGNATURE_CHANGE" | "EMULATABLE" | "STUB_CANDIDATE" => "transformed signature",
            _ => "incompatible signature",
        });
        if mapping["mapping_kind"] == "SAME" {
            result["classification"] = json!("DIRECT");
        }
        return result;
    }
    let matches: Vec<_> = targets
        .iter()
        .filter(|t| same_call_signature(source, t, args.len()))
        .collect();
    if !matches.is_empty() {
        result["classification"] = json!("DIRECT");
        result["signature_match"] =
            json!(if args
                .iter()
                .enumerate()
                .all(|(i, a)| argument(source, i).and_then(|t| type_cost(a, t)) == Some(0))
            {
                "exact signature"
            } else {
                "compatible signature"
            });
        result["proposed_reach_counterpart"] = json!(name);
        result["target_overload_candidates"] = json!(matches);
        result["confidence"] = json!("HIGH");
        result["evidence"] = json!([{"kind":"DOCS_MATCH","source":cat.evidence}]);
        result["fidelity_compatibility"] = json!("UNVERIFIED");
        result["reason"] = json!(
            "The resolved H3 overload has matching Reach return and active parameter types. Documentation compatibility does not establish runtime semantics, numeric ranges or resource bindings."
        );
    } else if targets.is_empty() {
        result["classification"] = json!("UNSUPPORTED");
        result["reason"] = json!(
            "Documented H3 overload has no same-name Reach API or reviewed replacement; this is catalogue-relative absence, not proof emulation is impossible"
        );
        result["confidence"] = json!("PROVISIONAL");
    } else {
        result["classification"] = json!("SIGNATURE_CHANGE");
        result["reason"] = json!(
            "Same-name Reach API has incompatible active parameter or return types; no reviewed transform is available"
        );
        result["target_overload_candidates"] = json!(targets);
    }
    result
}
pub fn counts<'a>(values: impl Iterator<Item = &'a Value>, field: &str) -> BTreeMap<String, usize> {
    let mut counts: BTreeMap<_, _> = CLASSES.into_iter().map(|c| (c.into(), 0)).collect();
    for v in values {
        *counts
            .entry(v[field].as_str().unwrap_or("UNKNOWN").into())
            .or_default() += 1;
    }
    counts
}
/// One conservative bucket per unique engine name. Per-overload/call facts
/// remain in the report; totals never count one name in multiple categories.
pub fn aggregate(classes: &[Value]) -> &'static str {
    for c in [
        "UNSUPPORTED",
        "UNKNOWN",
        "STUB_CANDIDATE",
        "EMULATABLE",
        "SIGNATURE_CHANGE",
        "RENAMED",
        "DIRECT",
    ] {
        if classes.iter().any(|v| v == c) {
            return c;
        }
    }
    "UNKNOWN"
}
