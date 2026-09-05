use super::*;
use blam_tags::{Enum, TagFunction};
use blam_tags::math::ArgbColor;

fn parameter(name: &str, kind: RenderMethodParameterType) -> RenderMethodParameter {
    RenderMethodParameter { parameter_name:name.into(), parameter_type:Some(Enum::from_variant(kind)),
        bitmap_path:String::new(), real_parameter:0.0, int_parameter:0, color_parameter:ArgbColor(0),
        bitmap_flags:0, bitmap_filter_mode:Default::default(), bitmap_comparison_function:Default::default(),
        bitmap_address_mode:Default::default(), bitmap_address_mode_x:Default::default(),
        bitmap_address_mode_y:Default::default(), bitmap_anisotropy_amount:0,
        bitmap_extern_mode:None, animated_parameters:vec![] }
}

fn option(name: &str, kind: RenderMethodParameterType) -> RenderMethodOptionParameter {
    RenderMethodOptionParameter { parameter_name:name.into(), parameter_type:Some(Enum::from_variant(kind)),
        source_extern:None, default_bitmap_path:"textures/shared".into(), default_real_value:0.75,
        default_int_bool_value:1, flags:0, default_filter_mode:Default::default(),
        default_comparison_function:Default::default(), default_address_mode:Default::default(),
        anisotropy_amount:4, default_color:ArgbColor(0x80402010), default_bitmap_scale:16.0,
        help_text:String::new() }
}

fn category(name: &str, option_names: &[&str]) -> RenderMethodDefinitionCategory {
    RenderMethodDefinitionCategory { category_name:name.into(), vertex_function:String::new(),
        pixel_function:String::new(), options:option_names.iter().map(|n| RenderMethodDefinitionCategoryOption {
            option_name:(*n).into(), option_path:format!("options/{name}/{n}"),
            vertex_function:String::new(), pixel_function:String::new() }).collect() }
}

fn fixture(kind: RenderMethodParameterType) -> (RenderMethod, RenderMethodDefinition, BTreeMap<String, OptionSource>) {
    let rm = RenderMethod { definition_path:"shaders/shader".into(), options:vec![0], parameters:vec![],
        postprocess_definition:None, flags:Default::default(), sort_layer:Default::default(),
        runtime_flags:Default::default(), custom_fog_setting_index:0, prediction_atom_index:-1,
        group_tag:u32::from_be_bytes(*b"rmsh"), class:RenderMethodClass::Shader, material_names:vec![] };
    let definition = RenderMethodDefinition { global_options_path:String::new(),
        categories:vec![category("albedo", &["default"])], shared_pixel_shaders_path:String::new(),
        shared_vertex_shaders_path:String::new(), flags:0, version:1 };
    let mut options = BTreeMap::new();
    options.insert("options/albedo/default".into(), OptionSource {
        option:RenderMethodOption { parameters:vec![option("base_map", kind)] }, fields:vec![] });
    (rm, definition, options)
}

fn has_code(value: &Value, code: &str) -> bool {
    value["diagnostics"].as_array().unwrap().iter().any(|d| d["code"] == code)
}

#[test]
fn choices_follow_definition_names_after_reordering() {
    let (mut rm, mut def, options) = fixture(RenderMethodParameterType::Bitmap);
    def.categories = vec![category("blend_mode", &["opaque", "pre_multiplied_alpha"]), category("albedo", &["default"])];
    rm.options = vec![1, 0];
    let first = describe(&rm, &def, &options);
    def.categories.swap(0, 1);
    def.categories[1].options.swap(0, 1);
    rm.options = vec![0, 0];
    let second = describe(&rm, &def, &options);
    assert_eq!(first["categories"][0]["option"], "pre_multiplied_alpha");
    assert_eq!(second["categories"][1]["option"], "pre_multiplied_alpha");
    assert_eq!(first["parameters"], second["parameters"]);
}

#[test]
fn absent_selection_and_invalid_authored_selection_differ() {
    let (mut rm, def, options) = fixture(RenderMethodParameterType::Bitmap);
    rm.options.clear();
    let defaulted = describe(&rm, &def, &options);
    assert_eq!(defaulted["categories"][0]["selection_origin"], "missing_entry_default_zero");
    assert_eq!(defaulted["parameters"].as_array().unwrap().len(), 1);
    for bad in [-1, 99] {
        rm.options = vec![bad];
        let value = describe(&rm, &def, &options);
        assert!(value["parameters"].as_array().unwrap().is_empty());
        assert!(has_code(&value, "invalid_category_selection"));
        assert_eq!(value["categories"][0]["source_option_index"], bad);
    }
}

#[test]
fn zero_override_does_not_become_default() {
    let (mut rm, def, options) = fixture(RenderMethodParameterType::Real);
    assert_eq!(describe(&rm, &def, &options)["parameters"][0]["resolved"]["value"], 0.75);
    rm.parameters.push(parameter("base_map", RenderMethodParameterType::Real));
    let value = describe(&rm, &def, &options);
    assert_eq!(value["parameters"][0]["resolved"]["value"], 0.0);
    assert_eq!(value["parameters"][0]["resolved_default"]["value"], 0.75);
    assert_eq!(value["parameters"][0]["origin"], "source_parameter_merge");
}

#[test]
fn colors_are_rgba_and_authored_color_is_retained() {
    let (mut rm, def, options) = fixture(RenderMethodParameterType::ArgbColor);
    let mut p = parameter("base_map", RenderMethodParameterType::ArgbColor);
    p.color_parameter = ArgbColor(0xffffffff);
    rm.parameters.push(p);
    let value = describe(&rm, &def, &options);
    let color = &value["parameters"][0]["resolved"];
    assert_eq!(color["encoding"], "rgba");
    let channels = color["value"].as_array().unwrap();
    for (actual, expected) in channels.iter().zip([64.0,32.0,16.0,128.0]) {
        assert!((actual.as_f64().unwrap() - expected / 255.0).abs() < 1e-6);
    }
    assert_eq!(value["source_parameters"][0]["color_argb_u32"], 0xffffffffu32);
}

#[test]
fn declared_bitmap_scale_is_not_mistaken_for_cbuffer_transform() {
    let (rm, def, options) = fixture(RenderMethodParameterType::Bitmap);
    let value = describe(&rm, &def, &options);
    assert_eq!(value["declarations"][0]["default"]["bitmap_scale"], 16.0);
    assert_eq!(value["parameters"][0]["texture_transform"]["scale"], json!([1.0,1.0]));
}

fn animation(kind: RenderMethodAnimatedParameterType, value: f32) -> RenderMethodAnimatedParameter {
    let mut bytes = [0u8;32];
    bytes[0] = 1;
    bytes[4..8].copy_from_slice(&value.to_le_bytes());
    RenderMethodAnimatedParameter { parameter_type:Some(Enum::from_variant(kind)),
        input_name:"object_function".into(), range_name:"range_function".into(),
        time_period_in_seconds:2.0, function:Some(TagFunction::parse(&bytes).unwrap()) }
}

#[test]
fn transform_channels_and_animation_inputs_survive() {
    let (mut rm, def, options) = fixture(RenderMethodParameterType::Bitmap);
    let mut p = parameter("base_map", RenderMethodParameterType::Bitmap);
    p.animated_parameters = vec![animation(RenderMethodAnimatedParameterType::ScaleUniform, 3.0),
        animation(RenderMethodAnimatedParameterType::ScaleY, 4.0),
        animation(RenderMethodAnimatedParameterType::TranslationX, 0.25)];
    rm.parameters.push(p);
    let value = describe(&rm, &def, &options);
    assert_eq!(value["parameters"][0]["texture_transform"]["scale"], json!([3.0,4.0]));
    assert_eq!(value["parameters"][0]["texture_transform"]["translation"], json!([0.25,0.0]));
    assert_eq!(value["source_parameters"][0]["animations"][0]["range_name"], "range_function");
    assert!(has_code(&value, "animation_not_converted"));
}

#[test]
fn externs_are_not_artist_bitmaps() {
    let (mut rm, def, mut options) = fixture(RenderMethodParameterType::Bitmap);
    options.get_mut("options/albedo/default").unwrap().option.parameters[0].source_extern = Some(Enum::from_variant(RenderMethodExtern::SceneLdrTexture));
    let value = describe(&rm, &def, &options);
    assert_eq!(value["parameters"][0]["resolved"]["kind"], "extern");
    assert!(value["parameters"][0]["resolved"]["value"].is_null());
    options.get_mut("options/albedo/default").unwrap().option.parameters[0].source_extern = None;
    let mut p = parameter("base_map", RenderMethodParameterType::Bitmap);
    p.bitmap_extern_mode = Some(RenderMethodExtern::SceneLdrTexture);
    rm.parameters.push(p);
    let value = describe(&rm, &def, &options);
    assert!(value["parameters"][0]["resolved"]["bitmap"].is_null());
    assert_eq!(value["parameters"][0]["resolved"]["authored_or_default_bitmap"], "textures/shared.bitmap");
    assert!(value["parameters"][0]["texture_transform"].is_null());
    assert!(has_code(&value, "runtime_dependency"));
}

#[test]
fn sampler_anisotropy_override_requires_its_flag() {
    let (mut rm, def, options) = fixture(RenderMethodParameterType::Bitmap);
    let mut p = parameter("base_map", RenderMethodParameterType::Bitmap);
    p.bitmap_anisotropy_amount = 16;
    rm.parameters.push(p);
    assert_eq!(describe(&rm, &def, &options)["parameters"][0]["resolved"]["sampler"]["anisotropy"], 4);
    rm.parameters[0].bitmap_flags = 0x10;
    assert_eq!(describe(&rm, &def, &options)["parameters"][0]["resolved"]["sampler"]["anisotropy"], 16);
}

#[test]
fn undeclared_and_duplicate_parameters_are_retained() {
    let (mut rm, def, options) = fixture(RenderMethodParameterType::Real);
    rm.parameters = vec![parameter("custom", RenderMethodParameterType::Real), parameter("custom", RenderMethodParameterType::Real)];
    let value = describe(&rm, &def, &options);
    assert_eq!(value["source_parameters"].as_array().unwrap().len(), 2);
    assert!(has_code(&value, "undeclared_source_parameter"));
    assert!(has_code(&value, "duplicate_source_parameter"));
}

#[test]
fn nonfinite_values_keep_bits_and_block_the_resolved_value() {
    let (mut rm, def, options) = fixture(RenderMethodParameterType::Real);
    let mut p = parameter("base_map", RenderMethodParameterType::Real);
    p.real_parameter = f32::from_bits(0x7fc01234);
    rm.parameters.push(p);
    let value = describe(&rm, &def, &options);
    assert!(has_code(&value, "non_finite_parameter"));
    assert_eq!(value["source_parameters"][0]["real_bits"], 0x7fc01234u32);
    assert!(value["parameters"][0]["resolved"].is_null());
}

#[test]
fn global_defaults_and_postprocess_are_reported_not_discarded() {
    let (mut rm, mut def, mut options) = fixture(RenderMethodParameterType::Real);
    def.global_options_path = "global".into();
    options.insert("global".into(), options["options/albedo/default"].clone());
    rm.postprocess_definition = Some(RenderMethodPostprocessDefinition {
        real_constants:vec![[1.0,2.0,3.0,4.0]], ..Default::default() });
    let value = describe(&rm, &def, &options);
    assert!(has_code(&value, "global_options_not_merged"));
    assert!(has_code(&value, "postprocess_not_applied"));
    assert_eq!(value["global_options"]["parameters"].as_array().unwrap().len(), 1);
    assert_eq!(value["postprocess"]["real_constants"][0], json!([1.0,2.0,3.0,4.0]));
}

#[test]
fn missing_options_and_unknown_types_do_not_invent_values() {
    let (rm, def, mut options) = fixture(RenderMethodParameterType::Real);
    let value = describe(&rm, &def, &BTreeMap::new());
    assert!(has_code(&value, "missing_option"));
    options.get_mut("options/albedo/default").unwrap().option.parameters[0].parameter_type = None;
    let value = describe(&rm, &def, &options);
    assert!(has_code(&value, "unresolved_parameter_type"));
    assert!(value["parameters"].as_array().unwrap().is_empty());
    assert_eq!(value["declarations"].as_array().unwrap().len(), 1);
}

#[test]
fn shared_bitmap_does_not_collapse_distinct_material_configuration() {
    let (mut rm, def, options) = fixture(RenderMethodParameterType::Bitmap);
    let first = describe(&rm, &def, &options);
    let mut p = parameter("base_map", RenderMethodParameterType::Bitmap);
    p.animated_parameters = vec![animation(RenderMethodAnimatedParameterType::ScaleX, 2.0)];
    rm.parameters.push(p);
    let second = describe(&rm, &def, &options);
    assert_eq!(first["parameters"][0]["resolved"]["bitmap"], second["parameters"][0]["resolved"]["bitmap"]);
    assert_ne!(first["parameters"][0]["texture_transform"], second["parameters"][0]["texture_transform"]);
}

#[test]
fn failed_material_retains_source_identity_without_assigning_a_destination() {
    let value = finish("missing.shader", None, failed("missing", "Missing source tag"));
    assert_eq!(value["format"], FORMAT);
    assert_eq!(value["version"], 1);
    assert_eq!(value["description_status"], "failed");
    assert_eq!(value["source_shader"], "missing.shader");
    assert_eq!(value["source_class"], "shader");
    assert_eq!(value["conversion_status"], "source_only");
    assert!(value["destination_shader"].is_null());
}

#[test]
fn raw_function_encoding_is_lossless() {
    assert_eq!(bytes_hex(&[0,1,0x7f,0x80,0xff]), "00017f80ff");
}
