use super::{
    hsc::{Catalogue, Signature, Sources},
    hsc_compat as compat, hsc_context,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
fn analyze(text: &str) -> Value {
    let mut s = Sources::default();
    s.add("fixture.hsc", text, "mission");
    s.analyze(&Catalogue::bundled(), &BTreeMap::new())
}
fn call<'a>(r: &'a Value, name: &str) -> &'a Value {
    r["call_sites"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == name)
        .unwrap()
}
fn sig(result: &str, args: &[&str]) -> Signature {
    Signature {
        result: result.into(),
        args: args.iter().map(|s| (*s).into()).collect(),
        raw: "fixture".into(),
        min_args: args.len(),
        max_args: Some(args.len()),
    }
}

#[test]
fn reviewed_vignette_rename_preserves_explicit_ai_and_boolean() {
    let r = analyze(
        "(global ai marine none) (script dormant go (vs_go_to marine TRUE factory_arm_a/buttonpush01))",
    );
    let c = call(&r, "vs_go_to");
    assert_eq!(c["classification"], "RENAMED");
    assert_eq!(c["proposed_reach_counterpart"], "cs_go_to");
    assert_eq!(c["raw_name_match"]["classification"], "UNSUPPORTED");
    assert_eq!(c["mapping"]["argument_transform"]["op"], "identity");
    assert_eq!(
        c["mapping"]["target_signature"]["args"],
        json!(["ai", "boolean", "point_reference"])
    );
}
#[test]
fn implicit_command_script_overload_is_separate_from_explicit_ai() {
    let r = analyze(
        "(global ai marine none) (script command_script go (cs_go_to p) (cs_enable_looking TRUE)) (script dormant other (vs_enable_looking marine TRUE) (vs_abort_on_damage TRUE))",
    );
    assert_eq!(call(&r, "cs_go_to")["classification"], "DIRECT");
    assert_eq!(
        call(&r, "cs_enable_looking")["source_overload_candidates"][0]["args"],
        json!(["boolean"])
    );
    assert_eq!(
        call(&r, "vs_enable_looking")["mapping"]["target_signature"]["args"],
        json!(["ai", "boolean"])
    );
    assert_eq!(
        call(&r, "vs_abort_on_damage")["mapping"]["target_signature"]["args"],
        json!(["boolean"])
    );
}
#[test]
fn lifecycle_functions_never_gain_a_prefix_rename() {
    let r = analyze(
        "(script dormant go (vs_reserve marine 1) (vs_release marine) (vs_release_all) (vs_set_cleanup_script cleanup)) (script static void cleanup (sleep 1))",
    );
    for n in [
        "vs_reserve",
        "vs_release",
        "vs_release_all",
        "vs_set_cleanup_script",
    ] {
        let c = call(&r, n);
        assert_eq!(c["classification"], "UNSUPPORTED");
        assert!(c["proposed_reach_counterpart"].is_null());
        assert_eq!(
            c["mapping"]["argument_transform"]["op"],
            "no_emitted_replacement"
        );
    }
    let mut cat = Catalogue::bundled();
    cat.h3
        .functions
        .insert("vs_unreviewed".into(), vec![sig("void", &["ai"])]);
    cat.reach
        .functions
        .insert("cs_unreviewed".into(), vec![sig("void", &["ai"])]);
    assert_eq!(
        compat::classify(
            "vs_unreviewed",
            &[vec!["ai".into()]],
            &cat,
            &compat::bundled()
        )["classification"],
        "UNSUPPORTED"
    );
}
#[test]
fn source_overloads_use_types_and_keep_ties_ambiguous() {
    let mut cat = Catalogue::bundled();
    let sigs = vec![sig("void", &["boolean"]), sig("void", &["ai"])];
    cat.h3.functions.insert("overload".into(), sigs.clone());
    cat.reach.functions.insert("overload".into(), sigs);
    let exact = compat::classify("overload", &[vec!["ai".into()]], &cat, &compat::bundled());
    assert_eq!(exact["signature_match"], "exact signature");
    assert_eq!(
        exact["source_overload_candidates"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    let ambiguous = compat::classify("overload", &[vec![]], &cat, &compat::bundled());
    assert_eq!(ambiguous["classification"], "UNKNOWN");
    assert_eq!(ambiguous["signature_match"], "ambiguous overload");
    let incompatible =
        compat::classify("overload", &[vec!["real".into()]], &cat, &compat::bundled());
    assert_eq!(incompatible["signature_match"], "incompatible signature");
}
#[test]
fn return_type_change_is_not_direct_and_type_names_are_not_global_aliases() {
    let mut cat = Catalogue::bundled();
    cat.h3
        .functions
        .insert("different".into(), vec![sig("short", &["string_id"])]);
    cat.reach
        .functions
        .insert("different".into(), vec![sig("long", &["string_id"])]);
    assert_eq!(
        compat::classify(
            "different",
            &[vec!["string_id".into()]],
            &cat,
            &compat::bundled()
        )["classification"],
        "SIGNATURE_CHANGE"
    );
    cat.reach.functions.insert(
        "different".into(),
        vec![sig("short", &["unit_seat_mapping"])],
    );
    assert_eq!(
        compat::classify(
            "different",
            &[vec!["string_id".into()]],
            &cat,
            &compat::bundled()
        )["classification"],
        "SIGNATURE_CHANGE"
    );
}
#[test]
fn duplicate_docs_and_optional_overloads_do_not_create_false_ambiguity() {
    let mut cat = Catalogue::bundled();
    let a = sig("void", &["boolean"]);
    cat.h3
        .functions
        .insert("duplicate".into(), vec![a.clone(), a.clone()]);
    cat.reach.functions.insert("duplicate".into(), vec![a]);
    let c = compat::classify(
        "duplicate",
        &[vec!["boolean".into()]],
        &cat,
        &compat::bundled(),
    );
    assert_eq!(c["classification"], "DIRECT");
    assert_eq!(c["source_overload_candidates"].as_array().unwrap().len(), 1);
}
#[test]
fn sleep_until_actual_voi_condition_period_timeout_forms_are_consistent() {
    let r = analyze(
        "(script dormant intro_nav_exit (sleep_until TRUE) (sleep_until (> (device_get_position factory_a_entry) 0) 1) (sleep_until (> (device_get_position factory_a_entry) 0) 30 (* 120 30)))",
    );
    let calls: Vec<_> = r["call_sites"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["name"] == "sleep_until")
        .collect();
    assert_eq!(calls.len(), 3);
    for c in calls {
        assert_eq!(c["classification"], "DIRECT");
    }
    assert_eq!(
        r["engine_functions"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["name"] == "sleep_until")
            .unwrap()["classifications"],
        json!(["DIRECT"])
    );
}
#[test]
fn sleep_until_wrong_types_or_four_arguments_remain_unknown() {
    let r =
        analyze("(script dormant go (sleep_until TRUE 1 30 60) (sleep_until \"bad condition\"))");
    for c in r["call_sites"].as_array().unwrap() {
        assert_eq!(c["classification"], "UNKNOWN");
    }
}
#[test]
fn every_user_declaration_kind_stays_out_of_engine_catalogue() {
    let r = analyze(
        "(global short count 0) (script static void helper (sleep 1)) (script stub void stubber (sleep 1)) (script dormant dormant_fn (sleep 1)) (script continuous loop_fn (sleep 1)) (script command_script cmd (sleep 1)) (script static void (caller (short sleep)) (sleep) (count) (helper) (stubber) (dormant_fn) (loop_fn) (cmd))",
    );
    for c in r["call_sites"].as_array().unwrap() {
        assert_eq!(c["name"], "sleep");
        assert_ne!(c["enclosing_script"], "caller");
    }
    assert_eq!(r["user_script_calls"].as_array().unwrap().len(), 7);
}
#[test]
fn generated_cinematic_declarations_are_user_scripts_without_body_invention() {
    let mut s = Sources::default();
    s.add(
        "fixture.hsc",
        "(script dormant go (040lb_cov_flee) (040lb_cov_flee_cleanup) (040pb_scarab_intro))",
        "mission",
    );
    let symbols = [
        "040lb_cov_flee",
        "040lb_cov_flee_cleanup",
        "040pb_scarab_intro",
    ]
    .into_iter()
    .map(|n| {
        (
            n.into(),
            vec![json!({"category":"scripts","address":"scripts#90[0]","declared_type":"void"})],
        )
    })
    .collect();
    let r = s.analyze(&Catalogue::bundled(), &symbols);
    assert!(r["call_sites"].as_array().unwrap().is_empty());
    assert_eq!(r["user_script_calls"].as_array().unwrap().len(), 3);
}
#[test]
fn unknown_symbols_are_separate_from_engine_inventory() {
    let r = analyze("(script dormant go (cs_go_to2 p))");
    assert_eq!(r["summary"]["unique_engine_functions"], 0);
    assert_eq!(r["unresolved_call_sites"][0]["name"], "cs_go_to2");
}
#[test]
fn expected_namespace_and_boolean_spellings_do_not_create_false_negatives() {
    let mut s = Sources::default();
    s.add("fixture.hsc","(script dormant scarab (sleep 1)) (script startup go (wake scarab) (switch_zone_set scarab) (ai_place scarab) (hud_show_training_text 1) (hud_show_training_text 0))","mission");
    let symbols = BTreeMap::from([(
        "scarab".into(),
        vec![
            json!({"category":"zone sets"}),
            json!({"category":"squads"}),
        ],
    )]);
    let r = s.analyze(&Catalogue::bundled(), &symbols);
    for c in r["call_sites"].as_array().unwrap() {
        assert_eq!(c["classification"], "DIRECT", "{c}");
    }
    assert!(
        r["user_script_calls"]
            .as_array()
            .unwrap()
            .iter()
            .any(|r| r["name"] == "scarab" && r["via"] == "wake")
    );
}
#[test]
fn seat_mapping_retains_typed_binding_requirement() {
    let r = analyze(
        "(script dormant go (vehicle_test_seat_list (ai_vehicle_get_from_starting_location intro_hog/driver) \"warthog_g\" (players)))",
    );
    let c = call(&r, "vehicle_test_seat_list");
    assert_eq!(c["classification"], "SIGNATURE_CHANGE");
    assert_eq!(
        c["mapping"]["target_function"],
        "vehicle_test_seat_unit_list"
    );
    assert_eq!(
        c["mapping"]["argument_transform"]["items"][1]["op"],
        "resolve_unit_seat_mapping"
    );
    assert_eq!(c["mapping"]["target_signature"]["result"], "boolean");
}
#[test]
fn player_gaze_transform_verifies_helper_body_not_just_its_name() {
    let r = analyze(
        "(script static unit player0 (unit (list_get (players) 0))) (script startup go (player_control_unlock_gaze (player0)))",
    );
    assert_eq!(
        call(&r, "player_control_unlock_gaze")["transform_preconditions"]["resolved_stock_player_helper"],
        true
    );
    let r = analyze(
        "(script static unit player0 (unit none)) (script startup go (player_control_unlock_gaze (player0)))",
    );
    assert_eq!(
        call(&r, "player_control_unlock_gaze")["transform_preconditions"]["resolved_stock_player_helper"],
        false
    );
    let plan = r["transpiler_mappings"]["call_mappings"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["source_function"] == "player_control_unlock_gaze")
        .unwrap();
    assert_eq!(plan["argument_transform"]["op"], "no_emitted_replacement");
}
#[test]
fn hud_broader_toggle_is_lossy_not_an_exact_rename() {
    let r = analyze("(script startup mission_voi (chud_show_fire_grenades FALSE))");
    let c = call(&r, "chud_show_fire_grenades");
    assert_eq!(c["classification"], "SIGNATURE_CHANGE");
    assert_eq!(c["fidelity_compatibility"], "LOSSY");
    assert_eq!(c["confidence"], "PROVISIONAL");
}
#[test]
fn breadcrumbs_propose_stateful_wrapper_not_a_removed_system() {
    let r = analyze(
        "(script dormant go (hud_breadcrumbs_activate_team_nav_point_object player factory_a_entry02_switch \"nav_factory_entry\" 0.2) (hud_breadcrumbs_deactivate_team_nav_point_object player \"nav_factory_entry\") (hud_breadcrumbs_using_revised_nav_points))",
    );
    for name in [
        "hud_breadcrumbs_activate_team_nav_point_object",
        "hud_breadcrumbs_deactivate_team_nav_point_object",
    ] {
        let c = call(&r, name);
        assert_eq!(c["classification"], "EMULATABLE");
        assert_eq!(
            c["mapping"]["argument_transform"]["state_key"],
            json!(["team", "identifier_or_flag"])
        );
    }
    assert_eq!(
        call(&r, "hud_breadcrumbs_using_revised_nav_points")["classification"],
        "RENAMED"
    );
}
#[test]
fn metagame_and_progression_can_have_same_api_class_different_impact() {
    let mut s = Sources::default();
    s.add("fixture.hsc","(script dormant skull (campaign_is_finished_normal)) (script dormant required_door (campaign_is_finished_normal))","mission");
    let mut r = s.analyze(&Catalogue::bundled(), &BTreeMap::new());
    let sha = s.files[0]["sha256"].clone();
    let reviews = json!({"reviews":[{"file":"fixture.hsc","source_sha256":sha,"enclosing_script":"skull","functions":["campaign_is_finished_normal"],"call_site_role":"METAGAME","blocker_severity":"OPTIONAL","evidence":["fixture context"],"confidence":"HIGH","notes":"Optional fixture branch"},{"file":"fixture.hsc","source_sha256":sha,"enclosing_script":"required_door","functions":["campaign_is_finished_normal"],"call_site_role":"MISSION_PROGRESSION","blocker_severity":"MISSION_BLOCKER","evidence":["fixture required door dependency"],"confidence":"HIGH","notes":"Required fixture branch"}]});
    hsc_context::apply_reviews(r["call_sites"].as_array_mut().unwrap(), &s, &reviews);
    assert_eq!(r["call_sites"][0]["classification"], "UNSUPPORTED");
    assert_eq!(r["call_sites"][1]["classification"], "UNSUPPORTED");
    assert_eq!(r["call_sites"][0]["blocker_severity"], "OPTIONAL");
    assert_eq!(r["call_sites"][1]["blocker_severity"], "MISSION_BLOCKER");
    s.files[0]["sha256"] = json!("changed");
    hsc_context::apply_reviews(r["call_sites"].as_array_mut().unwrap(), &s, &reviews);
    assert_eq!(r["call_sites"][1]["blocker_severity"], "UNKNOWN");
}
#[test]
fn reviewed_catalogue_is_deterministic_and_signatures_exist() {
    let review = compat::bundled();
    let cat = compat::supplemented(&Catalogue::bundled(), &review);
    let rows = review["mappings"].as_array().unwrap();
    let ids: Vec<_> = rows.iter().map(|r| r["id"].as_str().unwrap()).collect();
    assert_eq!(
        ids,
        ids.iter()
            .copied()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>()
    );
    for row in rows {
        let source: Signature = serde_json::from_value(row["source_signature"].clone()).unwrap();
        assert!(
            cat.h3.functions[row["source_function"].as_str().unwrap()]
                .iter()
                .any(|s| compat::same(s, &source))
        );
        assert!(!row["evidence"].as_array().unwrap().is_empty());
        assert_eq!(row["runtime_verified"], false);
        if let Some(target) = row["target_function"].as_str() {
            let signature: Signature =
                serde_json::from_value(row["target_signature"].clone()).unwrap();
            assert!(
                cat.reach.functions[target]
                    .iter()
                    .any(|s| compat::same(s, &signature))
            );
        }
    }
    assert_eq!(
        serde_json::to_string(&review).unwrap(),
        serde_json::to_string(&compat::bundled()).unwrap()
    );
}
#[test]
fn deterministic_analysis_retains_exact_multiline_source_locations() {
    let text = "; comment\n(script dormant go\n  (vs_enable_looking\n    marine TRUE))";
    let a = analyze(text);
    let b = analyze(text);
    assert_eq!(a, b);
    let c = call(&a, "vs_enable_looking");
    assert_eq!(c["location"]["line"], 3);
    assert_eq!(c["location"]["column"], 3);
    assert_eq!(c["enclosing_script"], "go");
    assert_eq!(
        c["original_source_expression"],
        "(vs_enable_looking\n    marine TRUE)"
    );
    assert!(
        c["expression"]["end_byte"].as_u64().unwrap() > c["location"]["byte"].as_u64().unwrap()
    );
    assert_eq!(
        a["summary"]["function_classifications"]
            .as_object()
            .unwrap()
            .values()
            .filter_map(Value::as_u64)
            .sum::<u64>(),
        a["summary"]["unique_engine_functions"].as_u64().unwrap()
    );
}
#[test]
fn changed_catalogue_cannot_silently_apply_stale_target_mapping() {
    let mut cat = Catalogue::bundled();
    cat.reach
        .functions
        .get_mut("cs_enable_looking")
        .unwrap()
        .retain(|s| s.args.len() != 2);
    let c = compat::classify(
        "vs_enable_looking",
        &[vec!["ai".into()], vec!["boolean".into()]],
        &cat,
        &compat::bundled(),
    );
    assert_eq!(c["classification"], "UNKNOWN");
    assert!(c["mapping"].is_null());
}

/// Optional developer acceptance fixture. Reads the real kit; writes only to
/// the explicitly supplied outside-kit scratch directory.
#[test]
#[ignore = "requires H3_CENSUS_REAL_DATA and H3_CENSUS_REAL_TAGS"]
fn real_040_voi_script_acceptance() {
    use std::{fs, path::PathBuf};
    let data = PathBuf::from(std::env::var("H3_CENSUS_REAL_DATA").unwrap())
        .canonicalize()
        .unwrap();
    let tags = PathBuf::from(std::env::var("H3_CENSUS_REAL_TAGS").unwrap())
        .canonicalize()
        .unwrap();
    let output = PathBuf::from(std::env::var("H3_CENSUS_SCRIPT_OUTPUT").unwrap());
    let output =
        super::output_guard(&output, &[data.clone(), tags.parent().unwrap().to_owned()]).unwrap();
    let scan = super::graph::scan(
        &tags.join("levels/solo/040_voi/040_voi.scenario"),
        true,
        false,
    );
    let selected: BTreeSet<_> = super::scenario::entities(&scan, "source files")
        .iter()
        .filter_map(|s| s["name"].as_str().map(str::to_owned))
        .collect();
    let mut sources = Sources::default();
    for dir in [
        data.join("levels/solo/040_voi/scripts"),
        data.join("globals"),
    ] {
        let mut files: Vec<_> = fs::read_dir(dir)
            .unwrap()
            .map(|p| p.unwrap().path())
            .filter(|p| p.extension().is_some_and(|s| s == "hsc"))
            .collect();
        files.sort();
        for file in files {
            let text = String::from_utf8_lossy(&fs::read(&file).unwrap()).into_owned();
            let name = file
                .strip_prefix(&data)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            let scope = if selected.contains(file.file_stem().unwrap().to_str().unwrap()) {
                "mission"
            } else {
                "discovered_not_in_scenario_source_table"
            };
            sources.add(&name, &text, scope);
        }
    }
    let result = sources.analyze(&Catalogue::bundled(), &super::scenario::symbols(&scan));
    assert!(
        result["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .all(|d| !matches!(
                d["code"].as_str(),
                Some("unexpected_close_paren" | "unterminated_form" | "unterminated_string")
            ))
    );
    println!("{}", result["summary"]);
    fs::create_dir_all(&output).unwrap();
    super::write_json_new(&output.join("040_voi_scripts.json"), &result).unwrap();
}
