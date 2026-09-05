//! Source material descriptions. No bitmap or destination-tag writes.
use anyhow::Result;
use blam_tags::render_method::*;
use blam_tags::{SchemaEnum, TagFieldData, TagFile, TagStruct};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

const FORMAT: &str = "foundry.h3-material";

#[derive(Clone)]
pub struct OptionSource {
    pub option: RenderMethodOption,
    fields: Vec<Value>,
}

impl OptionSource {
    pub fn from_tag(tag: &TagFile) -> Result<Self> {
        Ok(Self { fields: raw_parameters(&tag.root(), "parameters"),
            option: RenderMethodOption::from_tag(tag)? })
    }
}

fn diagnostic(code: &str, message: impl Into<String>) -> Value {
    json!({"code": code, "message": message.into()})
}

fn bitmap_path(path: &str) -> Option<String> {
    (!path.is_empty()).then(|| format!("{}.bitmap", path.replace('\\', "/")))
}

fn bytes_hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes { write!(text, "{byte:02x}").unwrap(); }
    text
}

fn raw_parameters(s: &TagStruct<'_>, block_name: &str) -> Vec<Value> {
    let Some(block) = s.field(block_name).and_then(|f| f.as_block()) else { return vec![] };
    (0..block.len()).filter_map(|i| block.element(i)).map(|p| {
        let integer_names = ["parameter type", "source extern", "bitmap flags", "bitmap filter mode",
            "bitmap comparison function", "bitmap address mode", "bitmap address mode x",
            "bitmap address mode y", "bitmap anisotropy amount", "bitmap extern RTT mode",
            "int/bool", "default int/bool value", "flags", "default filter mode",
            "default comparison function", "default address mode", "anisotropy amount"];
        let integers: BTreeMap<_, _> = integer_names.into_iter().filter_map(|name| {
            p.read_int_any(name).map(|v| (name, v as i64))
        }).collect();
        let reals: BTreeMap<_, _> = ["real", "default real value", "default bitmap scale"].into_iter()
            .filter_map(|name| p.read_real(name).map(|v| (name, v))).collect();
        let colors: BTreeMap<_, _> = ["color", "default color"].into_iter().filter_map(|name| {
            let value = match p.field(name).and_then(|f| f.value()) {
                Some(TagFieldData::ArgbColor(c)) => json!({"encoding":"argb_u32", "value":c.0}),
                Some(TagFieldData::RgbColor(c)) => json!({"encoding":"rgb_u32", "value":c.0}),
                _ => return None,
            };
            Some((name, value))
        }).collect();
        json!({"name": p.read_string_id("parameter name"), "integers": integers,
            "real_bits":reals.iter().map(|(k,v)| (*k,v.to_bits())).collect::<BTreeMap<_,_>>(),
            "reals": reals, "colors": colors, "bitmap":p.read_tag_ref_path("bitmap"),
            "default_bitmap":p.read_tag_ref_path("default bitmap"),
            "animations":raw_animations(&p, "animated parameters")})
    }).collect()
}

fn raw_animations(s: &TagStruct<'_>, block_name: &str) -> Vec<Value> {
    let Some(block) = s.field(block_name).and_then(|f| f.as_block()) else { return vec![] };
    (0..block.len()).filter_map(|i| block.element(i)).map(|a| {
        let function = a.field("function").and_then(|f| f.as_struct())
            .and_then(|s| s.field("data")).and_then(|f| f.as_data()).map(bytes_hex);
        json!({"type_index":a.read_int_any("type").map(|v| v as i64),
            "input_name":a.read_string_id("input name"), "range_name":a.read_string_id("range name"),
            "time_period_seconds":a.read_real("time period"),
            "time_period_bits":a.read_real("time period").map(f32::to_bits), "function_data_hex":function})
    }).collect()
}

fn animation_json(a: &RenderMethodAnimatedParameter) -> Value {
    json!({"type":a.parameter_type.map(|v| v.name()), "input_name":a.input_name,
        "range_name":a.range_name, "time_period_seconds":a.time_period_in_seconds,
        "time_period_bits":a.time_period_in_seconds.to_bits(), "function_decoded":a.function.is_some(),
        "function_data_hex":a.function.as_ref().map(|f| bytes_hex(&f.to_bytes()))})
}

fn parameter_json(p: &RenderMethodParameter) -> Value {
    json!({"name":p.parameter_name, "type":p.parameter_type.map(|v| v.name()),
        "bitmap":bitmap_path(&p.bitmap_path), "real":p.real_parameter, "real_bits":p.real_parameter.to_bits(), "int_bool":p.int_parameter,
        "color_argb_u32":p.color_parameter.0, "bitmap_flags":p.bitmap_flags,
        "sampler":{"filter":p.bitmap_filter_mode.schema_name(),
            "comparison":p.bitmap_comparison_function.schema_name(),
            "address":p.bitmap_address_mode.schema_name(),
            "address_x":p.bitmap_address_mode_x.schema_name(),
            "address_y":p.bitmap_address_mode_y.schema_name(),
            "anisotropy":p.bitmap_anisotropy_amount},
        "bitmap_extern":p.bitmap_extern_mode.map(|v| v.schema_name()),
        "animations":p.animated_parameters.iter().map(animation_json).collect::<Vec<_>>()})
}

fn default_json(p: &RenderMethodOptionParameter) -> Value {
    json!({"name":p.parameter_name, "type":p.parameter_type.map(|v| v.name()),
        "source_extern":p.source_extern.map(|v| v.name()),
        "bitmap":bitmap_path(&p.default_bitmap_path), "real":p.default_real_value, "real_bits":p.default_real_value.to_bits(),
        "int_bool":p.default_int_bool_value, "color_argb_u32":p.default_color.0,
        "bitmap_scale":p.default_bitmap_scale, "bitmap_scale_bits":p.default_bitmap_scale.to_bits(), "flags":p.flags,
        "sampler":{"filter":p.default_filter_mode.name(), "comparison":p.default_comparison_function.name(),
            "address":p.default_address_mode.name(), "anisotropy":p.anisotropy_amount},
        "help_text":p.help_text})
}

fn resolved_json(p: &ResolvedParameter) -> Value {
    match &p.source {
        ParameterSource::Extern(ext) => json!({"kind":"extern", "extern":ext.schema_name(), "value":null}),
        ParameterSource::Inline(value) => match value {
            ResolvedValue::Bitmap(b) => json!({"kind":"bitmap", "bitmap":if b.extern_texture_mode.is_some() { None } else { bitmap_path(&b.bitmap_path) },
                "authored_or_default_bitmap":bitmap_path(&b.bitmap_path),
                "image_index":b.bitmap_index, "extern":b.extern_texture_mode.map(|v| v.schema_name()),
                "sampler":{"filter":b.filter_mode.schema_name(), "address":b.address_mode.schema_name(),
                    "address_x":b.address_mode_x.schema_name(), "address_y":b.address_mode_y.schema_name(),
                    "anisotropy":b.anisotropy_amount}}),
            // The pinned walker forwards compile_real_constant's RGBA vector.
            ResolvedValue::Color(c) => json!({"kind":"color", "encoding":"rgba", "value":c}),
            ResolvedValue::Real(v) => json!({"kind":"real", "value":v}),
            ResolvedValue::Int(v) => json!({"kind":"int", "value":v}),
            ResolvedValue::Bool(v) => json!({"kind":"bool", "value":v}),
        }
    }
}

pub fn describe(rm: &RenderMethod, definition: &RenderMethodDefinition,
            options: &BTreeMap<String, OptionSource>) -> Value {
    let mut diagnostics = Vec::new();
    let mut active = definition.clone();
    let mut categories = Vec::new();
    let mut declarations = Vec::new();
    let mut names = BTreeSet::new();
    let choices = RenderMethodChoices::resolve(rm, definition);
    for (i, category) in definition.categories.iter().enumerate() {
        let raw_index = rm.options.get(i).copied();
        let index = raw_index.unwrap_or(0);
        let selected = usize::try_from(index).ok().and_then(|n| category.options.get(n));
        let unique = !category.category_name.is_empty() && names.insert(category.category_name.clone());
        let mut status = "resolved";
        if selected.is_none() || !unique {
            active.categories[i].options.clear();
            status = "unresolved";
            diagnostics.push(diagnostic("invalid_category_selection", format!("Category {i} {:?}, option {index}", category.category_name)));
        }
        let choice = if unique && selected.is_some() { choices.get(&category.category_name) } else { None };
        if let Some(selected) = selected.filter(|_| unique) {
            if !selected.option_path.is_empty() {
                if let Some(source) = options.get(&selected.option_path) {
                    for (parameter_index, parameter) in source.option.parameters.iter().enumerate() {
                        declarations.push(json!({"category":category.category_name, "option":selected.option_name,
                            "option_tag":format!("{}.render_method_option", selected.option_path.replace('\\', "/")),
                            "parameter_index":parameter_index, "default":default_json(parameter),
                            "source_fields":source.fields.get(parameter_index)}));
                        if parameter.parameter_type.is_none() || parameter.parameter_name.is_empty() {
                            diagnostics.push(diagnostic("unresolved_parameter_type", parameter.parameter_name.clone()));
                        }
                    }
                } else {
                    status = "unresolved";
                    diagnostics.push(diagnostic("missing_option", selected.option_path.clone()));
                }
            }
        }
        categories.push(json!({"category_index":i, "category":category.category_name,
            "source_option_index":raw_index, "selection_origin":if raw_index.is_some() { "source" } else { "missing_entry_default_zero" },
            "option":choice, "option_tag":selected.filter(|s| !s.option_path.is_empty())
                .map(|s| format!("{}.render_method_option", s.option_path.replace('\\', "/"))),
            "vertex_function":category.vertex_function, "pixel_function":category.pixel_function,
            "option_vertex_function":selected.map(|s| &s.vertex_function),
            "option_pixel_function":selected.map(|s| &s.pixel_function), "status":status}));
    }
    if rm.options.len() > definition.categories.len() {
        diagnostics.push(diagnostic("extra_option_entries", "Source options extend beyond the definition's categories"));
    }
    let load = |path: &str| options.get(path).map(|s| {
        let mut op = s.option.clone();
        op.parameters.retain(|p| p.parameter_type.is_some() && !p.parameter_name.is_empty());
        op
    });
    let resolved = ResolvedRenderMethod::resolve(rm, &active, load);
    let mut defaults_rm = rm.clone();
    defaults_rm.parameters.clear();
    let defaults = ResolvedRenderMethod::resolve(&defaults_rm, &active, load);
    let op_parameters = build_rmop_param_list(rm, &active, load);
    let mut parameters = Vec::new();
    for p in &resolved.parameters {
        let source_index = rm.parameters.iter().position(|s| s.parameter_name == p.name);
        let source = source_index.map(|i| &rm.parameters[i]);
        let declaration = op_parameters.iter().find(|s| s.parameter_name == p.name).unwrap();
        let nonfinite = !declaration.default_real_value.is_finite() || !declaration.default_bitmap_scale.is_finite() ||
            source.is_some_and(|s| !s.real_parameter.is_finite() ||
                s.animated_parameters.iter().any(|a| !a.time_period_in_seconds.is_finite()));
        if nonfinite { diagnostics.push(diagnostic("non_finite_parameter", p.name.clone())); }
        let animated = source.is_some_and(|s| !s.animated_parameters.is_empty());
        let runtime = matches!(&p.source, ParameterSource::Extern(_)) ||
            matches!(&p.source, ParameterSource::Inline(ResolvedValue::Bitmap(b)) if b.extern_texture_mode.is_some());
        if runtime { diagnostics.push(diagnostic("runtime_dependency", p.name.clone())); }
        if animated { diagnostics.push(diagnostic("animation_not_converted", p.name.clone())); }
        let transform = if !nonfinite && !runtime && p.parameter_type == RenderMethodParameterType::Bitmap {
            let (value, _) = compile_real_constant(declaration, source);
            Some(json!({"scale":&value[0..2], "translation":&value[2..4],
                "basis":"decoder_cbuffer_sample_at_zero", "animated":animated}))
        } else { None };
        if source.is_some_and(|s| s.parameter_type.map(|t| t.get()) != Some(p.parameter_type)) {
            diagnostics.push(diagnostic("parameter_type_mismatch", p.name.clone()));
        }
        let mut value = resolved_json(p);
        let mut default_value = defaults.find(&p.name).map(resolved_json);
        if let Some(sampler) = value.get_mut("sampler") {
            let comparison = source.filter(|s| s.bitmap_flags & 0x20 != 0)
                .map(|s| s.bitmap_comparison_function).unwrap_or(declaration.default_comparison_function.get());
            sampler["comparison"] = json!(comparison.schema_name());
        }
        if let Some(sampler) = default_value.as_mut().and_then(|v| v.get_mut("sampler")) {
            sampler["comparison"] = json!(declaration.default_comparison_function.name());
        }
        parameters.push(json!({"name":p.name, "type":p.parameter_type.schema_name(),
            "origin":if runtime { "engine_extern" } else if source.is_some() { "source_parameter_merge" } else { "option_default" },
            "source_parameter_index":source_index, "resolved":if nonfinite { Value::Null } else { value },
            "resolved_default":if nonfinite { None } else { default_value },
            "texture_transform":transform, "animated":animated}));
    }
    let mut source_names = BTreeSet::new();
    for p in &rm.parameters {
        if !source_names.insert(p.parameter_name.clone()) {
            diagnostics.push(diagnostic("duplicate_source_parameter", p.parameter_name.clone()));
        }
        if resolved.find(&p.parameter_name).is_none() {
            diagnostics.push(diagnostic("undeclared_source_parameter", p.parameter_name.clone()));
        }
    }
    let global = if definition.global_options_path.is_empty() { Value::Null } else {
        diagnostics.push(diagnostic("global_options_not_merged", "Global option declarations are retained separately; the pinned walker only resolves active categories"));
        json!({"source_tag":format!("{}.render_method_option", definition.global_options_path.replace('\\', "/")),
            "parameters":options.get(&definition.global_options_path)
                .map(|s| s.option.parameters.iter().map(default_json).collect::<Vec<_>>()),
            "source_fields":options.get(&definition.global_options_path).map(|s| &s.fields)})
    };
    let postprocess = rm.postprocess_definition.as_ref().map(|p| {
        if !p.textures.is_empty() || !p.real_constants.is_empty() || !p.int_constants.is_empty() ||
                p.bool_constants != 0 || !p.overlays.is_empty() {
            diagnostics.push(diagnostic("postprocess_not_applied", "Postprocess constants and bindings are retained, not merged into authored parameters"));
        }
        json!({"template":p.template_path, "real_constants":p.real_constants, "int_constants":p.int_constants,
            "bool_constants":p.bool_constants, "blend_mode_index":p.blend_mode, "flags":p.flags,
            "runtime_queryable_properties":p.runtime_queryable_properties,
            "textures":p.textures.iter().map(|t| json!({"bitmap":bitmap_path(&t.bitmap_path), "image_index":t.bitmap_index,
                "address_x":t.address_mode_x.schema_name(), "address_y":t.address_mode_y.schema_name(),
                "filter":t.filter_mode.schema_name(), "comparison":t.comparison_function.schema_name(),
                "extern":t.extern_texture_mode.map(|v| v.schema_name()),
                "transform_constant_index":t.texture_transform_constant_index,
                "transform_overlay_indices":t.texture_transform_overlay_indices.0})).collect::<Vec<_>>(),
            "entry_points":p.entry_points.iter().map(|i| i.0).collect::<Vec<_>>(),
            "passes":p.passes.iter().map(|p| json!({"bitmaps":p.bitmaps.0,
                "vertex_real_constants":p.vertex_real_constants.0, "pixel_real_constants":p.pixel_real_constants.0})).collect::<Vec<_>>(),
            "routing":p.routing_info.iter().map(|r| json!({"destination":r.destination_index,
                "source":r.source_index,"type_specific":r.type_specific})).collect::<Vec<_>>(),
            "overlays":p.overlays.iter().map(animation_json).collect::<Vec<_>>()})
    });
    json!({"description_status":if diagnostics.is_empty() { "resolved" } else { "partial" },
        "definition":format!("{}.render_method_definition", rm.definition_path.replace('\\', "/")),
        "definition_version":definition.version, "definition_flags":definition.flags,
        "source_options":rm.options, "categories":categories, "parameters":parameters,
        "declarations":declarations, "source_parameters":rm.parameters.iter().map(parameter_json).collect::<Vec<_>>(),
        "global_options":global, "postprocess":postprocess, "material_names":rm.material_names,
        "evaluation":"decoder_sample_at_zero; runtime inputs are not supplied",
        "diagnostics":diagnostics})
}

pub fn failed(code: &str, message: impl Into<String>) -> Value {
    json!({"description_status":"failed", "diagnostics":[diagnostic(code, message)]})
}

pub fn finish(source: &str, tag: Option<&TagFile>, mut value: Value) -> Value {
    value["format"] = json!(FORMAT);
    value["version"] = json!(1);
    value["game"] = json!("halo3_mcc");
    value["source_shader"] = json!(source);
    value["source_class"] = json!(source.rsplit_once('.').map(|p| p.1));
    value["conversion_status"] = json!("source_only");
    value["destination_shader"] = Value::Null;
    if let Some(tag) = tag {
        let root = tag.root();
        let rm = root.descend("render_method").unwrap_or(root);
        value["source_group"] = json!(String::from_utf8_lossy(&tag.header.group_tag.to_be_bytes()).to_string());
        value["source_parameter_fields"] = json!(raw_parameters(&rm, "parameters"));
        value["source_postprocess_overlays"] = rm.field("postprocess").and_then(|f| f.as_block())
            .and_then(|b| b.element(0)).map(|s| json!(raw_animations(&s, "overlays"))).unwrap_or(json!([]));
        value["source_definition"] = json!(rm.read_tag_ref_path("definition"));
        value["source_reference"] = json!(rm.read_tag_ref_path("reference"));
        value["source_render_state"] = json!({"shader_flags":rm.read_int_any("shader flags").map(|v| v as i64),
            "sort_layer":rm.read_int_any("sort layer").map(|v| v as i64),
            "runtime_flags":rm.read_int_any("runtime flags").map(|v| v as i64),
            "custom_fog_setting_index":rm.read_int_any("Custom fog setting index").map(|v| v as i64)});
    }
    value
}

#[cfg(test)]
#[path = "material_description/tests.rs"]
mod tests;
