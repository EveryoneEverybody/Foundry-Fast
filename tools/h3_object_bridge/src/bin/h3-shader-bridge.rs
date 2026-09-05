//! Read H3 material recipes and texture previews. No tag writes.
use anyhow::{bail, Context, Result};
use blam_tags::{Bitmap, TagFile};
use blam_tags::render_method::{
    compile_real_constant, ParameterSource, RenderMethod, RenderMethodChoices,
    RenderMethodDefinition, RenderMethodParameter,
    RenderMethodParameterType, ResolvedRenderMethod, ResolvedValue,
};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{BufWriter, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::{Component, Path, PathBuf};

#[path = "../material_description.rs"]
mod material_description;
use material_description::OptionSource;

fn resolve(root: &Path, name: &str, ext: Option<&str>) -> Result<PathBuf> {
    let name = name.replace('\\', "/");
    if name.is_empty() || name.contains(':') || name.starts_with('/')
        || name.split('/').any(|s| s.is_empty() || s == "." || s == "..")
        || Path::new(&name).components().any(|c| !matches!(c, Component::Normal(_))) {
        bail!("Unsafe tag reference: {name}");
    }
    let relative = match ext { Some(ext) => format!("{name}.{ext}"), None => name };
    let path = root.join(&relative).canonicalize()
        .with_context(|| format!("Missing dependency: {relative}"))?;
    if !path.starts_with(root) || !path.is_file() { bail!("Invalid dependency: {relative}"); }
    Ok(path)
}

fn kind(t: RenderMethodParameterType) -> &'static str {
    match t {
        RenderMethodParameterType::Bitmap => "bitmap",
        RenderMethodParameterType::Color => "color",
        RenderMethodParameterType::ArgbColor => "argb color",
        RenderMethodParameterType::Real => "real",
        RenderMethodParameterType::Int => "int",
        RenderMethodParameterType::Bool => "bool",
    }
}

fn enum_name<T: Into<&'static str>>(value: T) -> String { value.into().to_string() }
fn hex(bytes: &[u8]) -> String { bytes.iter().map(|b| format!("{b:02x}")).collect() }

fn authored(p: &RenderMethodParameter) -> Value {
    let functions: Vec<_> = p.animated_parameters.iter().map(|a| json!({
        "channel": a.parameter_type.map(|t| enum_name(t.get())),
        "input": a.input_name, "range": a.range_name, "period": a.time_period_in_seconds,
        "function_hex": a.function.as_ref().map(|f| hex(&f.to_bytes())),
    })).collect();
    json!({"name":p.parameter_name, "type":p.parameter_type.map(|t|kind(t.get())),
        "bitmap":p.bitmap_path, "real":p.real_parameter, "int":p.int_parameter,
        "argb_packed":p.color_parameter.0, "bitmap_flags":p.bitmap_flags,
        "filter":enum_name(p.bitmap_filter_mode),
        "comparison":enum_name(p.bitmap_comparison_function),
        "address":enum_name(p.bitmap_address_mode),
        "address_x":enum_name(p.bitmap_address_mode_x), "address_y":enum_name(p.bitmap_address_mode_y),
        "anisotropy":p.bitmap_anisotropy_amount,
        "extern":p.bitmap_extern_mode.map(enum_name), "functions":functions})
}

struct Reader {
    root: PathBuf,
    output: PathBuf,
    reach: Option<PathBuf>,
    options: BTreeMap<PathBuf, OptionSource>,
    definitions: BTreeMap<PathBuf, RenderMethodDefinition>,
    bitmaps: BTreeMap<String, Value>,
}

impl Reader {
    fn definition(&mut self, root: &Path, name: &str) -> Result<RenderMethodDefinition> {
        let path = resolve(root, name, Some("render_method_definition"))?;
        if let Some(value) = self.definitions.get(&path) { return Ok(value.clone()); }
        let value = RenderMethodDefinition::from_tag(&TagFile::read(&path)?)?;
        self.definitions.insert(path, value.clone());
        Ok(value)
    }

    fn option(&mut self, root: &Path, name: &str) -> Result<OptionSource> {
        let path = resolve(root, name, Some("render_method_option"))?;
        if let Some(value) = self.options.get(&path) { return Ok(value.clone()); }
        let value = OptionSource::from_tag(&TagFile::read(&path)?)?;
        self.options.insert(path, value.clone());
        Ok(value)
    }

    fn bitmap(&mut self, name: &str, index: i16) -> String {
        let key = format!("{}#{index}", name.replace('\\', "/"));
        if self.bitmaps.contains_key(&key) { return key; }
        let number = self.bitmaps.len();
        let result = (|| -> Result<Value> {
            if index < 0 { bail!("Negative bitmap index"); }
            let path = resolve(&self.root, name, Some("bitmap"))?;
            let tag = TagFile::read(&path)?;
            let bitmap = Bitmap::new(&tag)?;
            let image = bitmap.image(index as usize).context("Bitmap image index out of range")?;
            let mut result = json!({"path":name, "index":index, "image_count":bitmap.len(),
                "width":image.width(), "height":image.height(), "depth":image.depth(),
                "format":image.format_name(), "curve":format!("{:?}", image.curve()),
                "type":image.type_name(), "mips":image.mipmap_levels(), "status":"metadata_only"});
            // Full mip data stays separate from the RGBA8 Blender preview.
            let dds = format!("textures/{number:05}.dds");
            let mut out = Vec::new();
            match image.write_dds(&mut out) {
                Ok(()) => { write_new(&self.output.join(&dds), &out)?; result["dds"] = json!(dds); }
                Err(e) => result["dds_error"] = json!(e.to_string()),
            }
            let format = image.format_name().unwrap_or_default().to_lowercase();
            let large = u64::from(image.width()) * u64::from(image.height()) > 67_108_864;
            if !image.type_name().is_some_and(|t| t.eq_ignore_ascii_case("2d texture"))
                || image.depth() != 1 || bitmap.len() != 1 || !bitmap.sequences().is_empty() {
                result["preview_error"] = json!("Cube, volume, array, multi-image or sprite bitmap needs a dedicated preview");
            } else if large || image.width() == 0 || image.height() == 0 {
                result["preview_error"] = json!("Invalid or oversized preview dimensions");
            } else if format.contains("fp") || format.starts_with("f16") || format.contains("16g16")
                || format.contains("10g10") || format == "l16" {
                result["preview_error"] = json!("High-precision image retained without an RGBA8 preview");
            } else {
                let tiff = format!("textures/{number:05}.tif");
                out.clear();
                match image.write_tiff(&mut out) {
                    Ok(()) => {
                        write_new(&self.output.join(&tiff), &out)?;
                        result["preview"] = json!(tiff);
                        result["status"] = json!("preview");
                    }
                    Err(e) => result["preview_error"] = json!(e.to_string()),
                }
            }
            Ok(result)
        })();
        let value = result.unwrap_or_else(|e| json!({"path":name,"index":index,"status":"error","error":format!("{e:#}")}));
        self.bitmaps.insert(key.clone(), value);
        key
    }

    fn shader(&mut self, source: &str) -> Result<Value> {
        let tag = TagFile::read(resolve(&self.root, source, None)?)?;
        let mut result = json!({"source":source,"status":"unresolved"});
        let outcome = catch_unwind(AssertUnwindSafe(|| self.shader_from_tag(source, &tag, &mut result)));
        let error = match outcome {
            Ok(Ok(())) => None,
            Ok(Err(e)) => Some(format!("{e:#}")),
            Err(_) => Some("Shader decoder panicked; source fields and geometry retained".into()),
        };
        if let Some(error) = error {
            result["status"] = json!("error");
            result["error"] = json!(error);
        }
        let description = result.as_object_mut().unwrap().remove("source_description")
            .unwrap_or_else(|| material_description::failed("material_not_resolved",
                result["error"].as_str().unwrap_or("Source material has no resolved description")));
        result["source_description"] = material_description::finish(source, Some(&tag), description);
        Ok(result)
    }

    fn shader_from_tag(&mut self, source: &str, tag: &TagFile, result: &mut Value) -> Result<()> {
        let rm = RenderMethod::from_tag(tag)?;
        let root = tag.root();
        let rm_struct = root.descend("render_method").unwrap_or(root);
        let reference = rm_struct.read_tag_ref_path("reference").unwrap_or_default();
        *result = json!({"source":source,"group":String::from_utf8_lossy(&rm.group_tag.to_be_bytes()).to_string(),
            "definition":rm.definition_path,"reference":reference,"options_raw":rm.options,
            "authored_parameters":rm.parameters.iter().map(authored).collect::<Vec<_>>(),
            "material_names":rm.material_names,"status":"unresolved","categories":[],"parameters":[]});
        // The convenience walker does not traverse reference shaders.
        if !reference.is_empty() {
            result["error"] = json!("Reference shader inheritance is retained but not flattened in this build");
            result["source_description"] = json!({"description_status":"unsupported",
                "diagnostics":[{"code":"reference_inheritance_not_flattened", "message":reference}]});
            return Ok(());
        }
        let source_root = self.root.clone();
        let mut definition = self.definition(&source_root, &rm.definition_path)?;
        let mut diagnostics = Vec::<String>::new();
        let mut selected = BTreeMap::new();
        let mut required_failures = Vec::new();
        let mut paths = BTreeSet::new();
        for (i, category) in definition.categories.iter().enumerate() {
            let index = rm.options.get(i).copied().unwrap_or(0).max(0) as usize;
            if let Some(option) = category.options.get(index).filter(|o| !o.option_path.is_empty()) {
                paths.insert(option.option_path.clone());
            }
        }
        for path in paths {
            match catch_unwind(AssertUnwindSafe(|| self.option(&source_root, &path))) {
                Ok(Ok(option)) => { selected.insert(path, option); }
                other => {
                    let error = match other { Ok(Err(e)) => format!("{e:#}"), _ => "Option decoder panicked".into() };
                    required_failures.push(format!("{path}: {error}"));
                }
            }
        }
        if !definition.global_options_path.is_empty() && !selected.contains_key(&definition.global_options_path) {
            match catch_unwind(AssertUnwindSafe(|| self.option(&source_root, &definition.global_options_path))) {
                Ok(Ok(option)) => { selected.insert(definition.global_options_path.clone(), option); }
                _ => diagnostics.push(format!("Global option declarations unavailable: {}", definition.global_options_path)),
            }
        }
        result["source_description"] = if rm.group_tag.to_be_bytes() == *b"rmsh" {
            match catch_unwind(AssertUnwindSafe(|| material_description::describe(&rm, &definition, &selected))) {
                Ok(value) => value,
                Err(_) => material_description::failed("description_decoder_failed", "Source description decoder panicked"),
            }
        } else {
            json!({"description_status":"unsupported", "diagnostics":[{
                "code":"unsupported_shader_class", "message":"Resolved descriptions currently cover ordinary object shaders"}]})
        };
        if !required_failures.is_empty() { bail!("{}", required_failures.join("; ")); }
        let mut seen = BTreeSet::new();
        for (i, c) in definition.categories.iter().enumerate() {
            if c.category_name.is_empty() || !seen.insert(c.category_name.clone()) {
                bail!("Missing or duplicate category name");
            }
            let n = rm.options.get(i).copied().unwrap_or(0);
            if n < -1 || n.max(0) as usize >= c.options.len() { bail!("Invalid option for {}: {n}",c.category_name); }
        }
        let choices = RenderMethodChoices::resolve(&rm, &definition);
        result["categories"] = json!(choices.choices().iter().map(|c| json!({
            "category":c.category_name,"option":c.option_name,"source_index":c.option_index
        })).collect::<Vec<_>>());
        result["global_options"] = json!(definition.global_options_path);
        if !definition.global_options_path.is_empty() {
            diagnostics.push("Global render-method options are recorded, not included in the preview parameter walk".into());
        }
        // Globals are retained above; the selected-category walker stays unchanged.
        definition.global_options_path.clear();
        let resolved = ResolvedRenderMethod::resolve(&rm, &definition, |p| selected.get(p).map(|s| s.option.clone()));
        let declarations: Vec<_> = definition.categories.iter().zip(choices.choices()).flat_map(|(c, choice)| {
            let path = &c.options[choice.option_index as usize].option_path;
            selected.get(path).into_iter().flat_map(|s| s.option.parameters.iter())
        }).collect();
        let mut parameters = Vec::new();
        for p in &resolved.parameters {
            let op = declarations.iter().find(|op| op.parameter_name == p.name).context("Missing parameter declaration")?;
            if op.parameter_type.is_none() { bail!("Unrecognized parameter type for {}",p.name); }
            let raw = rm.parameters.iter().find(|x| x.parameter_name == p.name);
            let (slot, _) = compile_real_constant(op, raw);
            let mut value = json!({"name":p.name,"type":kind(p.parameter_type),
                "origin":if raw.is_some(){"authored"}else{"rmop_default"},
                "has_functions":raw.is_some_and(|p| !p.animated_parameters.is_empty())});
            match &p.source {
                ParameterSource::Extern(e) => { value["extern"] = json!(enum_name(*e)); }
                ParameterSource::Inline(v) => match v {
                    ResolvedValue::Bitmap(b) => {
                        value["transform"] = json!(slot);
                        value["sampler"] = json!({"filter":enum_name(b.filter_mode),
                            "address_x":enum_name(b.address_mode_x),"address_y":enum_name(b.address_mode_y),
                            "anisotropy":b.anisotropy_amount});
                        if let Some(e) = b.extern_texture_mode { value["extern"] = json!(enum_name(e)); }
                        else if !b.bitmap_path.is_empty() { value["bitmap"] = json!(self.bitmap(&b.bitmap_path,b.bitmap_index)); }
                    }
                    // compile_real_constant returns RGBA, despite the walker's ARGB doc comment.
                    ResolvedValue::Color(_) => value["value"] = json!(slot),
                    ResolvedValue::Real(v) => value["value"] = json!(v),
                    ResolvedValue::Int(v) => value["value"] = json!(v),
                    ResolvedValue::Bool(v) => value["value"] = json!(v),
                }
            }
            parameters.push(value);
        }
        result["parameters"] = json!(parameters);
        result["status"] = json!("resolved_snapshot");
        result["diagnostics"] = json!(diagnostics);
        result["evaluation"] = json!("Static snapshot at time 0; named object functions have no runtime provider");
        if let Some(reach_root) = self.reach.clone() {
            result["reach"] = match self.definition(&reach_root, &rm.definition_path) {
                Ok(dest) => crosswalk(&result, &dest),
                Err(e) => json!({"status":"unresolved","error":format!("{e:#}")}),
            };
        }
        Ok(())
    }
}

fn crosswalk(source: &Value, dest: &RenderMethodDefinition) -> Value {
    let mut rows = Vec::new();
    for c in source["categories"].as_array().unwrap() {
        let matches: Vec<_> = dest.categories.iter().enumerate()
            .filter(|(_, d)| d.category_name == c["category"].as_str().unwrap()).collect();
        let mut row = c.clone();
        row["status"] = json!("missing_or_ambiguous_category");
        if let [(i, d)] = matches.as_slice() {
            let options: Vec<_> = d.options.iter().enumerate().filter(|(_,o)|o.option_name == c["option"].as_str().unwrap()).collect();
            row["status"] = json!("missing_or_ambiguous_option");
            if let [(j, o)] = options.as_slice() {
                row["destination_category_index"] = json!(i);
                row["destination_option_index"] = json!(j);
                row["destination_rmop"] = json!(o.option_path);
                row["status"] = json!("name_match");
            }
        }
        rows.push(row);
    }
    let extra: Vec<_> = dest.categories.iter().filter(|d| !rows.iter().any(|s|s["category"] == d.category_name))
        .map(|d|d.category_name.clone()).collect();
    json!({"status":"names_only_not_export_ready","categories":rows,"destination_only_categories":extra,
        "note":"Matching labels are candidates, not proof of equivalent HLSL or parameter contracts. No tags were generated."})
}

fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut f = BufWriter::new(OpenOptions::new().write(true).create_new(true).open(path)?);
    f.write_all(bytes)?;
    f.flush()?;
    Ok(())
}

fn run() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let mut values = BTreeMap::new();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--tags-root" | "--asset" | "--output" | "--reach-tags-root" => {
                values.insert(arg,args.next().context("Missing argument value")?);
            }
            "--version" => { println!("h3-shader-bridge 0.2.0; material schema 1; source description schema 1"); return Ok(()); }
            _ => bail!("Unknown argument: {arg}"),
        }
    }
    let get = |key: &str| -> Result<PathBuf> { Ok(PathBuf::from(values.get(key).with_context(||format!("Required: {key}"))?).canonicalize()?) };
    let root = get("--tags-root")?;
    let asset = get("--asset")?;
    let output = get("--output")?;
    let reach = if values.contains_key("--reach-tags-root") { Some(get("--reach-tags-root")?) } else { None };
    if !root.is_dir() || !output.is_dir() || output.starts_with(&root)
        || reach.as_ref().is_some_and(|r| !r.is_dir() || output.starts_with(r) || r == &root) {
        bail!("Extraction output must be outside both tags directories");
    }
    if !asset.starts_with(&output) { bail!("Asset manifest must be in the extraction directory"); }
    if output.join("shader_manifest.json").exists() { bail!("Shader manifest already exists"); }
    let geometry: Value = serde_json::from_slice(&fs::read(&asset)?)?;
    if geometry["format"] != "foundry.h3-object" || geometry["game"] != "halo3_mcc" || geometry["version"] != 1 {
        bail!("Unsupported object manifest");
    }
    fs::create_dir(output.join("textures"))?;
    let mut reader = Reader {root,output:output.clone(),reach,options:BTreeMap::new(),definitions:BTreeMap::new(),bitmaps:BTreeMap::new()};
    let paths = geometry["shader_paths"].as_array().context("Missing shader paths")?;
    let mut shaders = BTreeMap::new();
    for (i, source) in paths.iter().enumerate() {
        let source = source.as_str().context("Shader path is not text")?;
        if shaders.contains_key(source) { continue; }
        let result = catch_unwind(AssertUnwindSafe(||reader.shader(source)));
        let mut record = match result {
            Ok(Ok(value)) => value,
            Ok(Err(e)) => json!({"source":source,"status":"error","error":format!("{e:#}")}),
            Err(_) => json!({"source":source,"status":"error","error":"Shader decoder panicked; geometry retained"}),
        };
        if record.get("source_description").is_none() {
            record["source_description"] = material_description::finish(source, None,
                material_description::failed("material_read_failed", record["error"].as_str().unwrap_or("Material read failed")));
        }
        shaders.insert(source.to_string(),record);
        if i % 10 == 0 || i+1 == paths.len() { println!("H3 shader metadata: {} / {}",i+1,paths.len()); }
    }
    let manifest = json!({"format":"foundry.h3-shaders","version":1,"source_tag":geometry["source_tag"],
        "source_game":"halo3_mcc","shaders":shaders,"bitmaps":reader.bitmaps,
        "notes":["Blender previews are approximations, not game shader conversions.",
            "Source function blobs, parameter values and sampler settings are retained.",
            "Runtime externs, reference inheritance and animated materials require additional work."]});
    write_new(&output.join("shader_manifest.json"),&serde_json::to_vec_pretty(&manifest)?)?;
    println!("H3 shader extraction complete: {} shaders, {} bitmap bindings",shaders.len(),reader.bitmaps.len());
    Ok(())
}

fn main() { if let Err(e) = run() { eprintln!("{e:#}"); std::process::exit(1); } }

#[cfg(test)]
mod tests {
    use super::*;
    use blam_tags::render_method::{RenderMethodDefinitionCategory, RenderMethodDefinitionCategoryOption};
    fn option(name:&str)->RenderMethodDefinitionCategoryOption {
        RenderMethodDefinitionCategoryOption{option_name:name.into(),option_path:format!("options/{name}"),vertex_function:String::new(),pixel_function:String::new()}
    }
    fn definition()->RenderMethodDefinition {
        RenderMethodDefinition{global_options_path:String::new(),categories:vec![
            RenderMethodDefinitionCategory{category_name:"blend_mode".into(),vertex_function:String::new(),pixel_function:String::new(),options:vec![option("opaque"),option("alpha_blend")]},
            RenderMethodDefinitionCategory{category_name:"albedo".into(),vertex_function:String::new(),pixel_function:String::new(),options:vec![option("constant_color"),option("default")]},
        ],shared_pixel_shaders_path:String::new(),shared_vertex_shaders_path:String::new(),flags:0,version:0}
    }
    #[test] fn options_are_matched_by_name_not_index() {
        let source=json!({"categories":[{"category":"albedo","option":"default","source_index":0}]});
        let v=crosswalk(&source,&definition());
        assert_eq!(v["categories"][0]["destination_category_index"],1);
        assert_eq!(v["categories"][0]["destination_option_index"],1);
        assert_eq!(v["status"],"names_only_not_export_ready");
    }
    #[test] fn missing_option_is_not_substituted() {
        let v=crosswalk(&json!({"categories":[{"category":"albedo","option":"unknown"}]}),&definition());
        assert_eq!(v["categories"][0]["status"],"missing_or_ambiguous_option");
        assert!(v["categories"][0].get("destination_option_index").is_none());
    }
    #[test] fn ambiguous_category_is_not_guessed() {
        let mut d=definition();d.categories.push(d.categories[1].clone());
        let v=crosswalk(&json!({"categories":[{"category":"albedo","option":"default"}]}),&d);
        assert_eq!(v["categories"][0]["status"],"missing_or_ambiguous_category");
    }
    #[test] fn unsafe_references_are_rejected() {
        for name in ["../bad","a/../bad","a//b","/bad","C:\\bad","\\\\server\\bad",""] {
            assert!(resolve(Path::new("."),name,None).is_err());
        }
    }
    #[test] fn function_bytes_are_encoded_without_numeric_conversion() { assert_eq!(hex(&[0,128,255]),"0080ff"); }
}