//! Retain regular H3 aiming-screen definitions and source-order pose samples.
use anyhow::{bail, Context, Result};
use blam_tags::TagFile;
use serde_json::{json, Value};

pub struct BlendScreen {
    pub index: i16,
    label: String,
    counts: [i64; 4],
    angles: [f32; 4],
    source_fields: Value,
}

impl BlendScreen {
    pub fn read(tag: &TagFile, index: i16) -> Result<Self> {
        if index < 0 { bail!("Missing blend-screen index"); }
        let element = tag.root().descend(&format!("definitions/blend screens[{index}]"))
            .context("Blend-screen index is outside the H3 definitions block")?;
        let aiming = element.field("aiming screen").and_then(|f| f.as_struct())
            .context("Blend screen has no supported H3 aiming-screen definition")?;
        let integer = |name: &str| aiming.read_int_any(name).with_context(|| format!("Missing screen field: {name}"));
        let angle = |name: &str| aiming.read_real(name).with_context(|| format!("Missing screen angle: {name}"));
        let screen = Self {
            index,
            label: element.read_string_id("label").context("Blend screen has no label")?,
            counts: [integer("right frame count")?, integer("left frame count")?,
                integer("down pitch frame count")?, integer("up pitch frame count")?],
            angles: [angle("right yaw per frame")?, angle("left yaw per frame")?,
                angle("down pitch per frame")?, angle("up pitch per frame")?],
            source_fields: super::snapshot(element, 0),
        };
        screen.sample_count()?;
        Ok(screen)
    }

    fn sample_count(&self) -> Result<usize> {
        if self.index < 0 || self.label.is_empty() { bail!("Invalid blend-screen identity"); }
        for (&count, &angle) in self.counts.iter().zip(&self.angles) {
            if !(0..=32767).contains(&count) || !angle.is_finite() || angle < 0.0 || (count > 0 && angle == 0.0) {
                bail!("Invalid blend-screen count or angle step");
            }
        }
        let count = (self.counts[0] + self.counts[1] + 1) * (self.counts[2] + self.counts[3] + 1);
        if count > 32767 { bail!("Blend-screen grid exceeds the animation sample limit"); }
        Ok(count as usize)
    }

    pub fn validate_samples(&self, header_count: i16, resource_count: Option<i16>, decoded_count: usize) -> Result<()> {
        let expected = self.sample_count()?;
        if header_count <= 0 || decoded_count != expected
            || resource_count.is_some_and(|n| n <= 0 || n as usize != expected) {
            bail!("Blend-screen grid/resource/decoded sample counts disagree");
        }
        // Keep header duration separate from the resource's pose count.
        Ok(())
    }

    pub fn metadata(&self) -> Result<Value> {
        Ok(json!({"index":self.index, "label":self.label,
            "layout":"h3_aiming_screen", "angle_units":"radians",
            "counts":{"right":self.counts[0], "left":self.counts[1], "down":self.counts[2], "up":self.counts[3]},
            "angles":{"right":self.angles[0], "left":self.angles[1], "down":self.angles[2], "up":self.angles[3]},
            "sample_count":self.sample_count()?, "sample_order":"source_codec_order",
            "sample_coordinates":"unresolved", "source_fields":self.source_fields}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use blam_tags::animation::{AnimationGroup, AnimatedStreamStatus, JmaKind, NodeTransform,
        PackedDataSizes, Skeleton, SkeletonNode};
    use blam_tags::math::{RealPoint3d, RealQuaternion};

    fn screen() -> BlendScreen {
        BlendScreen {index:0, label:"aim".into(), counts:[1;4],
            angles:[std::f32::consts::FRAC_PI_4;4], source_fields:json!({"raw_hex":"test"})}
    }

    #[test] fn regular_grids_keep_asymmetric_counts_and_radians() {
        let mut s = screen();
        assert_eq!(s.sample_count().unwrap(), 9);
        assert_eq!(s.metadata().unwrap()["angles"]["right"], json!(std::f32::consts::FRAC_PI_4));
        s.counts = [2,1,1,0];
        assert_eq!(s.sample_count().unwrap(), 8);
        s.counts = [0;4];
        s.angles = [0.0;4];
        assert_eq!(s.sample_count().unwrap(), 1);
    }

    #[test] fn invalid_screen_values_fail_without_defaulting() {
        for counts in [[-1,1,1,1], [32768,0,0,0], [32767;4]] {
            let mut s = screen(); s.counts = counts;
            assert!(s.sample_count().is_err());
        }
        for angle in [f32::NAN, f32::INFINITY, -0.1, 0.0] {
            let mut s = screen(); s.angles[0] = angle;
            assert!(s.sample_count().is_err());
        }
        let mut s = screen(); s.index = -1;
        assert!(s.sample_count().is_err());
    }

    #[test] fn resource_pose_count_is_not_header_duration() {
        let s = screen();
        s.validate_samples(9, Some(9), 9).unwrap();
        s.validate_samples(60, Some(9), 9).unwrap();
        s.validate_samples(9, None, 9).unwrap();
        for (header, resource, decoded) in [(0,Some(9),9),(9,Some(8),9),(9,Some(9),8),(9,Some(0),9)] {
            assert!(s.validate_samples(header, resource, decoded).is_err());
        }
    }

    fn codec_fixture(codec: u8) -> Vec<u8> {
        // One node, nine uncompressed quaternion/translation/scale samples.
        let count = 9usize;
        let translation = 32 + 16 * count;
        let scale = translation + 12 * count;
        let mut blob = vec![0u8;32];
        blob[..4].copy_from_slice(&[codec,1,1,1]);
        for (offset,value) in [(12,translation),(16,scale),(20,16*count),(24,12*count),(28,4*count)] {
            blob[offset..offset+4].copy_from_slice(&(value as u32).to_le_bytes());
        }
        for i in 0..count {
            let angle = (i as f32 - 4.0) * 0.1;
            for value in [0.0f32,0.0,(angle/2.0).sin(),(angle/2.0).cos()] {
                blob.extend(value.to_le_bytes());
            }
        }
        for i in 0..count {
            for value in [i as f32,0.0,0.0] { blob.extend(value.to_le_bytes()); }
        }
        for i in 0..count { blob.extend((1.0+i as f32*0.01).to_le_bytes()); }
        for word in [0u32,0,0,1,1,1] { blob.extend(word.to_le_bytes()); }
        blob
    }

    #[test] fn fullframe_and_blend_screen_codecs_keep_all_nine_samples() {
        for codec in [2u8,8] {
            let blob = codec_fixture(codec);
            let sizes = PackedDataSizes {fields:vec![("default_data".into(),0),
                ("static_node_flags".into(),12),("animated_node_flags".into(),12),("movement_data".into(),0)]};
            let mut group = AnimationGroup::for_blob(&blob,Some(sizes),60,1,Some("none".into()));
            group.codec_frame_count = Some(9);
            let clip = group.decode().unwrap();
            assert!(matches!(clip.animated_status,AnimatedStreamStatus::Decoded));
            screen().validate_samples(group.frame_count,group.codec_frame_count,clip.frame_count as usize).unwrap();
            let skeleton = Skeleton {nodes:vec![SkeletonNode{name:"hull".into(),parent:-1,first_child:-1,next_sibling:-1}]};
            let base = [NodeTransform {translation:RealPoint3d{x:20.0,y:30.0,z:40.0},
                rotation:RealQuaternion{w:std::f32::consts::FRAC_1_SQRT_2,i:std::f32::consts::FRAC_1_SQRT_2,j:0.0,k:0.0},scale:2.0}];
            let (reference,pose) = crate::overlay::compose(&clip,&skeleton,&base).unwrap();
            assert_eq!(pose.frames.len(),9);
            for (i,frame) in pose.frames.iter().enumerate() {
                assert!((frame[0].translation.x-(20.0+i as f32)).abs()<1e-5);
                assert!((frame[0].scale-2.0*(1.0+i as f32*0.01)).abs()<1e-5);
                let angle = (i as f32 - 4.0)*0.1/2.0;
                let q = frame[0].rotation;
                let h = std::f32::consts::FRAC_1_SQRT_2;
                for (actual,expected) in [q.w,q.i,q.j,q.k].into_iter().zip([h*angle.cos(),h*angle.cos(),-h*angle.sin(),h*angle.sin()]) {
                    assert!((actual-expected).abs()<1e-5);
                }
            }
            let mut bytes=Vec::new();
            pose.write_jma(&mut bytes,&skeleton,&reference,0,JmaKind::Jmo,"actor",None).unwrap();
            let text=String::from_utf8(bytes).unwrap();
            let lines:Vec<_>=text.lines().collect();
            assert_eq!(lines[1],"10");
            assert_eq!(lines.len(),7+3+10*3);
            let first_x=|line:usize| lines[line].split_whitespace().next().unwrap().parse::<f32>().unwrap();
            assert_eq!(first_x(10),2000.0);
            for i in 0..9 { assert_eq!(first_x(13+i*3),2000.0+i as f32*100.0); }
        }
    }
}
