use super::*;
use blam_tags::{TagFieldData, TagFile};
use std::sync::atomic::{AtomicUsize, Ordering};
static NEXT: AtomicUsize = AtomicUsize::new(0);
fn temp() -> PathBuf {
    let root = std::env::temp_dir().join(format!(
        "foundry_census_integration_{}_{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    fs::create_dir_all(&root).unwrap();
    root.canonicalize().unwrap()
}
fn schema(group: &str, fields: Vec<Value>, size: u32) -> Value {
    json!({"name":"fixture","tag":group,"version":1,"flags":0,"block":"root","blocks":{"root":{"max_count":1,"struct":"root"}},"structs":{"root":{"guid":"00000000000000000000000000000001","size":size,"fields":fields}},"enums_flags":{"choices":{"options":["one","two"]}}})
}
#[test]
fn cli_integration_schema_reports_collisions_and_read_only_guards() {
    let root = temp();
    let h3 = root.join("h3-kit/tags");
    let reach = root.join("reach-kit/tags");
    fs::create_dir_all(&h3).unwrap();
    fs::create_dir_all(&reach).unwrap();
    let definitions = root.join("definitions");
    fs::create_dir_all(definitions.join("halo3_mcc")).unwrap();
    fs::create_dir_all(definitions.join("haloreach_mcc")).unwrap();
    let fixture = schema(
        "scnr",
        vec![
            json!({"type":"long_integer","name":"fixture value"}),
            json!({"type":"terminator"}),
        ],
        4,
    );
    for profile in ["halo3_mcc", "haloreach_mcc"] {
        write_json_new(&definitions.join(profile).join("scenario.json"), &fixture).unwrap();
    }
    let mut tag = TagFile::new(definitions.join("halo3_mcc/scenario.json")).unwrap();
    tag.root_mut()
        .field_mut("fixture value")
        .unwrap()
        .set(TagFieldData::LongInteger(12))
        .unwrap();
    let source = h3.join("fixture.scenario");
    tag.write(&source).unwrap();
    fs::write(reach.join("fixture.scenario"), b"collision fixture").unwrap();
    let bytes = fs::read(&source).unwrap();
    let out = root.join("report");
    let cache = root.join("cache");
    let args = |output: &Path| {
        vec![
            source.to_string_lossy().into_owned(),
            "--h3-tags".into(),
            h3.to_string_lossy().into_owned(),
            "--reach-tags".into(),
            reach.to_string_lossy().into_owned(),
            "--definitions".into(),
            definitions.to_string_lossy().into_owned(),
            "--output".into(),
            output.to_string_lossy().into_owned(),
            "--cache".into(),
            cache.to_string_lossy().into_owned(),
        ]
    };
    assert!(run(args(&h3.join("report"))).is_err());
    assert!(!h3.join("report").exists());
    assert!(run(args(&root.join("reach-kit/data/reports"))).is_err());
    assert!(!root.join("reach-kit/data").exists());
    run(args(&out)).unwrap();
    let raw = fs::read(out.join("fixture_portability_report.json")).unwrap();
    let report: Value = serde_json::from_slice(&raw).unwrap();
    assert_eq!(report["format"], FORMAT);
    assert_eq!(report["version"], VERSION);
    assert_eq!(report["summary"]["unique_h3_tags"], 1);
    assert_eq!(report["path_collisions"][0]["exact_same_path"], true);
    assert_eq!(
        report["tags"][0]["structural_compatibility"]["status"],
        "IDENTICAL"
    );
    assert_eq!(report["tags"][0]["proposed_strategy"], "TRANSLATE_FIXUP");
    assert!(
        report["blockers"]
            .as_array()
            .unwrap()
            .iter()
            .any(|b| b["severity"] == "BOOT_BLOCKER")
    );
    assert_eq!(
        report["minimum_boot_set"]["source_assets"],
        json!(["fixture.scenario"])
    );
    let out2 = root.join("repeat");
    run(args(&out2)).unwrap();
    assert_eq!(
        raw,
        fs::read(out2.join("fixture_portability_report.json")).unwrap()
    );
    assert_eq!(
        fs::read(out.join("fixture_portability_report.md")).unwrap(),
        fs::read(out2.join("fixture_portability_report.md")).unwrap()
    );
    assert!(run(args(&out)).is_err());
    assert_eq!(bytes, fs::read(source).unwrap());
    assert_eq!(
        fs::read(reach.join("fixture.scenario")).unwrap(),
        b"collision fixture"
    );
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn field_loss_counts_do_not_imply_runtime_success() {
    let root = temp();
    let a = root.join("a.json");
    let b = root.join("b.json");
    write_json_new(
        &a,
        &schema(
            "scen",
            vec![
                json!({"type":"long_integer","name":"shared"}),
                json!({"type":"long_integer","name":"removed"}),
                json!({"type":"terminator"}),
            ],
            8,
        ),
    )
    .unwrap();
    write_json_new(
        &b,
        &schema(
            "scen",
            vec![
                json!({"type":"long_integer","name":"shared"}),
                json!({"type":"long_integer","name":"added"}),
                json!({"type":"terminator"}),
            ],
            8,
        ),
    )
    .unwrap();
    let a = TagFile::new(a).unwrap();
    let b = TagFile::new(b).unwrap();
    let result = compat::compare(&a, &b, &blam_tags::AliasIndex::default());
    assert_eq!(result["field_counts"]["matched_fields"], 1);
    assert_eq!(result["field_counts"]["source_only_dropped"], 1);
    assert_eq!(result["field_counts"]["target_only_defaulted"], 1);
    assert_eq!(result["proven_target_status"], "NOT_TESTED");
    fs::remove_dir_all(root).unwrap();
}
