// Shared read-only scalar decoding for scenario and semantic inventories.
use blam_tags::TagFieldData as D;
use blam_tags::paths::group_tag_to_extension;
use serde_json::{json, Value};

pub fn floats(values: &[f32]) -> Value {
    json!({"values": values.iter().map(|v| if v.is_finite() { Some(*v) } else { None }).collect::<Vec<_>>(),
           "bits": values.iter().map(|v| v.to_bits()).collect::<Vec<_>>()})
}

pub fn leaf(value: D) -> Value {
    match value {
        D::String(v) | D::LongString(v) => json!(v),
        D::StringId(v) | D::OldStringId(v) => json!(v.string),
        D::CharInteger(v) | D::CharBlockIndex(v) | D::CustomCharBlockIndex(v) => json!(v),
        D::ShortInteger(v) | D::ShortBlockIndex(v) | D::CustomShortBlockIndex(v) => json!(v),
        D::LongInteger(v) | D::LongBlockIndex(v) | D::CustomLongBlockIndex(v) | D::LongBlockFlags(v) => json!(v),
        D::Int64Integer(v) => json!(v),
        D::ByteInteger(v) | D::ByteBlockFlags(v) => json!(v),
        D::WordInteger(v) | D::WordBlockFlags(v) => json!(v),
        D::DwordInteger(v) | D::Tag(v) => json!(v),
        D::QwordInteger(v) => json!(v),
        D::CharEnum {value, name} => json!({"value":value, "name":name}),
        D::ShortEnum {value, name} => json!({"value":value, "name":name}),
        D::LongEnum {value, name} => json!({"value":value, "name":name}),
        D::ByteFlags {value, names} => json!({"value":value, "set_bits":names}),
        D::WordFlags {value, names} => json!({"value":value, "set_bits":names}),
        D::LongFlags {value, names} => json!({"value":value, "set_bits":names}),
        D::Angle(v) | D::Real(v) | D::RealSlider(v) | D::RealFraction(v) => floats(&[v]),
        D::RealPoint2d(v) => floats(&[v.x, v.y]),
        D::RealPoint3d(v) => floats(&[v.x, v.y, v.z]),
        D::RealVector2d(v) => floats(&[v.i, v.j]),
        D::RealVector3d(v) => floats(&[v.i, v.j, v.k]),
        D::RealEulerAngles2d(v) => floats(&[v.yaw, v.pitch]),
        D::RealEulerAngles3d(v) => floats(&[v.yaw, v.pitch, v.roll]),
        D::RealQuaternion(v) => json!({"order":"wxyz", "components":floats(&[v.w, v.i, v.j, v.k])}),
        D::TagReference(v) => match v.group_tag_and_name {
            Some((group, name)) => json!({"group":group, "group_name":String::from_utf8_lossy(&group.to_be_bytes()),
                "path":name, "extension":group_tag_to_extension(group)}),
            None => Value::Null,
        },
        other => json!({"representation":"decoder_debug", "value":format!("{other:?}")}),
    }
}

