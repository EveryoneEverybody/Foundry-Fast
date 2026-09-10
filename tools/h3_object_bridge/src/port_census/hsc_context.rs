//! Context reviews are pinned to source contents. Names alone never establish impact.
use super::hsc::Sources;
use serde_json::{Value, json};
pub fn bundled() -> Value {
    serde_json::from_str(include_str!("../../data/hsc_context_reviews.json"))
        .expect("HSC context reviews")
}
pub fn apply(calls: &mut [Value], sources: &Sources) {
    apply_reviews(calls, sources, &bundled());
}
pub fn apply_reviews(calls: &mut [Value], sources: &Sources, reviews: &Value) {
    for call in calls {
        let file = call["location"]["file"].as_str().unwrap_or("");
        let sha = sources
            .files
            .iter()
            .find(|r| r["path"] == file)
            .map(|r| &r["sha256"]);
        let matched: Vec<_> = reviews["reviews"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|r| {
                r["file"] == file
                    && r["enclosing_script"] == call["enclosing_script"]
                    && Some(&r["source_sha256"]) == sha
                    && r["functions"]
                        .as_array()
                        .is_some_and(|f| f.contains(&call["name"]))
            })
            .collect();
        call["call_site_role"] = json!("UNKNOWN");
        call["blocker_severity"] = json!("UNKNOWN");
        call["impact_evidence"] = json!([]);
        call["impact_confidence"] = json!("UNKNOWN");
        call["impact_notes"] = json!(
            "No current content-pinned context review. API absence and function-name similarity do not prove mission impact."
        );
        if matched.len() == 1 {
            let row = matched[0];
            call["call_site_role"] = row["call_site_role"].clone();
            call["blocker_severity"] = row["blocker_severity"].clone();
            call["impact_evidence"] = row["evidence"].clone();
            call["impact_confidence"] = row["confidence"].clone();
            call["impact_notes"] = row["notes"].clone();
        }
        call["requires_review"] = json!(!matches!(
            call["classification"].as_str(),
            Some("DIRECT") | Some("RENAMED")
        ));
        if call["requires_review"] == false {
            call["blocker_severity"] = json!("OPTIONAL");
        }
    }
}
