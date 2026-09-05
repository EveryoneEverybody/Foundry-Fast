//! Compose time overlays against a named local graph base.
use super::{supported, transform_json, writer};
use anyhow::{bail, Context, Result};
use blam_tags::animation::{
    base_state_candidates, AnimatedStreamStatus, AnimationClip, AnimationGraph,
    AnimationGroup, AnimationName, AnimationStateType, BitArray, JmaKind,
    MovementKind, NodeTransform, Pose, Skeleton,
};
use blam_tags::{Animation, TagFile};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::Write;
use std::path::Path;

pub struct OverlayExtractor {
    graph: AnimationGraph,
    bases: BTreeMap<usize, Vec<NodeTransform>>,
}

fn base_index(graph: &AnimationGraph, name: &str, overlay_index: usize) -> Result<(usize, String)> {
    let parsed = AnimationName::parse(name);
    if !parsed.valid || parsed.custom || parsed.state_type != AnimationStateType::Action {
        bail!("Overlay has no supported graph action scope; no bind-pose fallback was applied");
    }
    for state in base_state_candidates(&parsed.state) {
        let Some(action) = graph.find_action(&parsed.mode, &parsed.weapon_class,
            &parsed.weapon_type, &parsed.set, &state) else { continue; };
        if !action.is_local() { bail!("Overlay base {state} is inherited; parent graph resolution is not implemented"); }
        if action.animation_index < 0 { continue; }
        let index = action.animation_index as usize;
        if index != overlay_index { return Ok((index, state)); }
    }
    bail!("No local graph base for overlay {name}; no bind-pose fallback was applied")
}

fn validate_pose(frame: &[NodeTransform], nodes: usize) -> Result<()> {
    if frame.len() != nodes { bail!("Overlay pose node count mismatch"); }
    for t in frame {
        let q = t.rotation;
        let norm = q.w*q.w + q.i*q.i + q.j*q.j + q.k*q.k;
        if ![t.translation.x, t.translation.y, t.translation.z, norm, t.scale].into_iter().all(f32::is_finite)
            || (norm - 1.0).abs() > 0.01 || t.scale <= 0.0 {
            bail!("Overlay pose contains a non-finite, non-normalized, or non-positive transform");
        }
    }
    Ok(())
}

fn validate_tracks(clip: &AnimationClip, nodes: usize) -> Result<()> {
    if matches!(clip.animated_status, AnimatedStreamStatus::Unsupported(_) | AnimatedStreamStatus::Unknown(_)) {
        bail!("Overlay animated stream was not decoded; refusing a static-only substitute");
    }
    let flags = clip.node_flags.as_ref().context("Overlay node flags are missing")?;
    let animated = clip.animated_tracks.as_ref();
    for (label, fixed, moving, fixed_lengths, moving_lengths) in [
        ("rotation", &flags.static_rotation, &flags.animated_rotation,
         clip.static_tracks.rotations.iter().map(Vec::len).collect::<Vec<_>>(),
         animated.map(|t| t.rotations.iter().map(Vec::len).collect::<Vec<_>>()).unwrap_or_default()),
        ("translation", &flags.static_translation, &flags.animated_translation,
         clip.static_tracks.translations.iter().map(Vec::len).collect::<Vec<_>>(),
         animated.map(|t| t.translations.iter().map(Vec::len).collect::<Vec<_>>()).unwrap_or_default()),
        ("scale", &flags.static_scale, &flags.animated_scale,
         clip.static_tracks.scales.iter().map(Vec::len).collect::<Vec<_>>(),
         animated.map(|t| t.scales.iter().map(Vec::len).collect::<Vec<_>>()).unwrap_or_default()),
    ] {
        if (0..nodes).any(|i| fixed.bit(i) && moving.bit(i)) {
            bail!("Overlay {label} has overlapping static and animated flags");
        }
        if fixed.popcount_below(nodes) != fixed_lengths.len() || moving.popcount_below(nodes) != moving_lengths.len()
            || fixed_lengths.iter().any(|n| *n != 1)
            || moving_lengths.iter().any(|n| *n != clip.frame_count as usize) {
            bail!("Overlay {label} track dimensions disagree with node flags");
        }
    }
    Ok(())
}

fn compose(clip: &AnimationClip, skeleton: &Skeleton, base: &[NodeTransform]) -> Result<(Vec<NodeTransform>, Pose)> {
    if clip.frame_count == 0 { bail!("Overlay has no frames"); }
    if clip.movement.kind != MovementKind::None || !clip.movement.frames.is_empty() {
        bail!("Time overlays with movement data are not supported");
    }
    validate_tracks(clip, skeleton.len())?;
    validate_pose(base, skeleton.len())?;
    let (reference, pose) = clip.overlay_pose(skeleton, base);
    validate_pose(&reference, skeleton.len())?;
    for frame in &pose.frames { validate_pose(frame, skeleton.len())?; }
    Ok((reference, pose))
}

impl OverlayExtractor {
    pub fn new(tag: &TagFile) -> Self {
        Self { graph: AnimationGraph::from_tag(tag), bases: BTreeMap::new() }
    }

    pub fn export(&mut self, animations: &Animation<'_>, group: &AnimationGroup<'_>,
        skeleton: &Skeleton, defaults: &[NodeTransform], output: &Path, blend_screen: Option<i16>) -> Result<Value> {
        if group.animation_type.as_deref() != Some("overlay") || group.world_relative
            || group.frame_info_type.as_deref() != Some("none") {
            bail!("Only local time overlays without movement are supported");
        }
        if blend_screen != Some(-1) || !group.object_space_parents.is_empty() {
            bail!("Blend-screen and object-space pose overlays are not supported in this pass");
        }
        if group.node_count as u8 as usize != skeleton.len() || group.movement_type_mismatch() {
            bail!("Overlay header node count or movement type mismatch");
        }
        let name = group.name.as_deref().context("Overlay has no name")?;
        let (index, state) = base_index(&self.graph, name, group.index)?;
        let base_group = animations.get(index).context("Overlay base index is outside local animations")?;
        if !supported(base_group.animation_type.as_deref(), base_group.frame_info_type.as_deref(), base_group.world_relative)
            || base_group.node_count as u8 as usize != skeleton.len()
            || base_group.node_list_checksum != group.node_list_checksum
            || base_group.movement_type_mismatch() {
            bail!("Overlay base is not a compatible local base animation");
        }
        if !self.bases.contains_key(&index) {
            let decoded = base_group.decode().context("Decode overlay composition base")?;
            if matches!(decoded.animated_status, AnimatedStreamStatus::Unsupported(_) | AnimatedStreamStatus::Unknown(_)) {
                bail!("Overlay base animated stream was not decoded");
            }
            let pose = decoded.pose(skeleton, Some(defaults));
            if pose.frames.len() != base_group.frame_count as usize { bail!("Overlay base frame count mismatch"); }
            let first = pose.frames.first().context("Overlay base is empty")?.clone();
            validate_pose(&first, skeleton.len())?;
            self.bases.insert(index, first);
        }
        let base = &self.bases[&index];
        let clip = group.decode().context("Decode time overlay")?;
        if clip.frame_count as i16 != group.frame_count { bail!("Overlay decoded/header frame count mismatch"); }
        let (reference, pose) = compose(&clip, skeleton, base)?;
        let flags = clip.node_flags.as_ref().unwrap();
        let bits = |b: &BitArray| (0..skeleton.len()).map(|i| b.bit(i)).collect::<Vec<_>>();
        let file = format!("clip_{:04}.jmo", group.index);
        let mut out = writer(&output.join(&file))?;
        pose.write_jma(&mut out, skeleton, &reference, group.node_list_checksum, JmaKind::Jmo, "actor", None)?;
        out.flush()?;
        Ok(json!({"jma_file":file, "motion_file":null, "kind":"JMO", "fps":30,
            "decoded_frame_count":pose.frames.len(), "file_frame_count":pose.frames.len()+1,
            "frame_layout":"reference_then_codec_frames", "movement_samples":[],
            "overlay":{
                "composition":"static_reference_then_parent_local_delta", "preview":"composed_on_fixed_reference",
                "base":{"method":"graph_action_candidate_first_frame", "animation_index":index,
                    "animation_name":base_group.name, "state":state, "frame":0, "graph_index":-1},
                "base_pose":base.iter().map(transform_json).collect::<Vec<_>>(),
                "reference_pose":reference.iter().map(transform_json).collect::<Vec<_>>(),
                "node_flags":{"static_rotation":bits(&flags.static_rotation), "static_translation":bits(&flags.static_translation),
                    "static_scale":bits(&flags.static_scale), "animated_rotation":bits(&flags.animated_rotation),
                    "animated_translation":bits(&flags.animated_translation), "animated_scale":bits(&flags.animated_scale)},
                "reference_frame":1, "first_sample_frame":2,
                "notes":["Graph candidate selection is recorded, not proof of the original authoring base.",
                    "Standalone composed preview, not runtime layering over a moving base.",
                    "Blend screens, pose overlays, replacements and event conversion are not implemented."]}}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use blam_tags::animation::{AnimationTracks, Codec, GraphAction, GraphActionAnimation, GraphMode,
        GraphSet, GraphWeaponClass, GraphWeaponType, MovementData, NodeFlags, SkeletonNode};
    use blam_tags::math::{RealPoint3d, RealQuaternion};

    fn fixture() -> (AnimationClip, Skeleton, Vec<NodeTransform>) {
        let flags = NodeFlags { static_translation: BitArray::from_u64(2),
            animated_translation: BitArray::from_u64(1), animated_rotation: BitArray::from_u64(1),
            animated_scale: BitArray::from_u64(1), ..Default::default() };
        let q = RealQuaternion { w:0.70710677, i:0.70710677, j:0.0, k:0.0 };
        let delta = RealQuaternion { w:0.70710677, i:0.0, j:0.0, k:0.70710677 };
        let clip = AnimationClip { frame_count:2,
            static_tracks:AnimationTracks {codec:Codec::UncompressedStatic,frame_count:1,
                rotations:vec![], translations:vec![vec![RealPoint3d{x:9.0,y:8.0,z:7.0}]], scales:vec![]},
            animated_tracks:Some(AnimationTracks {codec:Codec::UncompressedStatic,frame_count:2,
                rotations:vec![vec![RealQuaternion::IDENTITY,delta]],
                translations:vec![vec![RealPoint3d{x:0.0,y:0.0,z:0.0},RealPoint3d{x:1.0,y:2.0,z:3.0}]],
                scales:vec![vec![1.0,1.25]]}), animated_status:AnimatedStreamStatus::Decoded,
            node_flags:Some(flags), movement:MovementData::default() };
        let skeleton=Skeleton {nodes:vec![SkeletonNode{name:"hull".into(),parent:-1,first_child:1,next_sibling:-1},
            SkeletonNode{name:"leg".into(),parent:0,first_child:-1,next_sibling:-1},
        ]};
        let base=vec![NodeTransform {translation:RealPoint3d{x:4.0,y:5.0,z:6.0},rotation:q,scale:2.0},NodeTransform::IDENTITY];
        (clip,skeleton,base)
    }

    #[test] fn overlay_composition_and_reference_layout() {
        let (clip,skeleton,base)=fixture();
        let (reference,pose)=compose(&clip,&skeleton,&base).unwrap();
        assert_eq!(reference[1].translation.x,9.0);
        assert_eq!(pose.frames[0][0].scale,2.0);
        assert_eq!(pose.frames[1][0].scale,2.5);
        assert_eq!(pose.frames[1][0].translation.x,5.0);
        assert_eq!(pose.frames[1][0].translation.y,7.0);
        assert_eq!(pose.frames[1][0].translation.z,9.0);
        let q=pose.frames[1][0].rotation;
        for (a,b) in [q.w,q.i,q.j,q.k].into_iter().zip([0.5,0.5,-0.5,0.5]) { assert!((a-b).abs()<1e-5); }
        assert_eq!(pose.frames[1][1].translation.x,9.0);
        let mut bytes=Vec::new();
        pose.write_jma(&mut bytes,&skeleton,&reference,42,JmaKind::Jmo,"actor",None).unwrap();
        let text=String::from_utf8(bytes).unwrap(); let lines=text.lines().collect::<Vec<_>>();
        assert_eq!(lines[1],"3");
        assert_eq!(lines.len(),7+3*2+3*2*3);
        let position=|line:usize| lines[line].split_whitespace().map(|v| v.parse::<f32>().unwrap()).collect::<Vec<_>>();
        assert_eq!(position(13),vec![400.0,500.0,600.0]);
        assert_eq!(position(19),vec![400.0,500.0,600.0]);
        assert_eq!(position(25),vec![500.0,700.0,900.0]);
    }

    #[test] fn incomplete_or_ambiguous_tracks_are_rejected() {
        let (clip,skeleton,base)=fixture();
        let mut bad=clip.clone(); bad.animated_status=AnimatedStreamStatus::Unknown(255);
        assert!(compose(&bad,&skeleton,&base).is_err());
        let mut bad=clip.clone(); bad.node_flags=None; assert!(compose(&bad,&skeleton,&base).is_err());
        let mut bad=clip.clone(); bad.animated_tracks.as_mut().unwrap().scales[0].pop();
        assert!(compose(&bad,&skeleton,&base).is_err());
        let mut bad=clip.clone(); bad.node_flags.as_mut().unwrap().static_rotation=BitArray::from_u64(1);
        assert!(compose(&bad,&skeleton,&base).is_err());
        let mut bad=clip.clone(); bad.animated_tracks.as_mut().unwrap().scales[0][1]=f32::NAN;
        assert!(compose(&bad,&skeleton,&base).is_err());
    }

    fn graph(graph_index:i16) -> AnimationGraph {
        AnimationGraph { modes:vec![GraphMode { label:"combat".into(), weapon_classes:vec![GraphWeaponClass {
            label:"any".into(),weapon_types:vec![GraphWeaponType {label:"any".into(),sets:vec![GraphSet {
                label:"any".into(),actions:vec![GraphAction {label:"idle".into(),animation:GraphActionAnimation {
                    graph_index,animation_index:8}}], ..Default::default()}]}]}]}] }
    }
    #[test] fn buckle_wobble_resolves_local_idle() {
        assert_eq!(base_index(&graph(-1),"combat:buckle_wobble",5).unwrap(),(8,"idle".into()));
    }
    #[test] fn missing_inherited_and_self_bases_are_rejected() {
        assert!(base_index(&AnimationGraph::default(),"combat:buckle_wobble",5).is_err());
        assert!(base_index(&graph(0),"combat:buckle_wobble",5).is_err());
        assert!(base_index(&graph(-1),"combat:buckle_wobble",8).is_err());
        assert!(base_index(&graph(-1),"custom",5).is_err());
    }
}
