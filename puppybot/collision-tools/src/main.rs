//! Thin PuppyBot-owned runner around PGE's public per-link collider API.
//!
//! The project owns URDF parsing and review policy. PGE owns mesh loading and
//! collision candidate generation; this binary only keeps its ordered report in
//! a stable JSON file for `generate_final2_collision_manifest.py` to consume.

use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

use pge_collision::{
    CollisionGenerationConfig, CompoundSelectionEvidence, LinkAssetColliderRequest,
    LinkAssetCollisionResult, LinkCollisionAggregateResult, ReviewedCollisionProfile,
    generate_link_asset_collision_candidates,
};
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct GeneratedEntry {
    link_name: String,
    asset_id: String,
    asset_to_link: pge_collision::LinkAssetTransform,
    provenance: pge_collision::AssetMeshProvenance,
}

#[derive(Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
enum Entry {
    Generated(GeneratedEntry),
    Failed {
        link_name: String,
        asset_id: String,
        asset_path: PathBuf,
        reason: String,
    },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct GeneratedLinkEntry {
    link_name: String,
    source_assets: Vec<pge_collision::LinkCollisionSourceAsset>,
    candidates: pge_collision::CollisionCandidates,
    reviewed_profile: ReviewedCollisionProfile,
    selection_evidence: CompoundSelectionEvidence,
}

#[derive(Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
enum LinkEntry {
    Generated(GeneratedLinkEntry),
    Failed {
        link_name: String,
        asset_count: usize,
        generated_asset_count: usize,
        reason: String,
    },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Report {
    format: &'static str,
    generator: &'static str,
    pge_collision_version: &'static str,
    generation_config: CollisionGenerationConfig,
    maximum_reviewed_colliders: usize,
    results: Vec<Entry>,
    link_results: Vec<LinkEntry>,
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("puppybot-pge-link-collider-report: {message}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut arguments = env::args_os();
    let _program = arguments.next();
    let input = arguments.next().map(PathBuf::from).ok_or_else(|| {
        "usage: puppybot-pge-link-collider-report INPUT.json OUTPUT.json".to_string()
    })?;
    let output = arguments.next().map(PathBuf::from).ok_or_else(|| {
        "usage: puppybot-pge-link-collider-report INPUT.json OUTPUT.json".to_string()
    })?;
    if arguments.next().is_some() {
        return Err("usage: puppybot-pge-link-collider-report INPUT.json OUTPUT.json".to_string());
    }

    let input_text = fs::read_to_string(&input)
        .map_err(|error| format!("could not read {}: {error}", input.display()))?;
    let requests: Vec<LinkAssetColliderRequest> = serde_json::from_str(&input_text)
        .map_err(|error| format!("could not parse {}: {error}", input.display()))?;
    let generation_config = CollisionGenerationConfig::default();
    let maximum_reviewed_colliders = 4;
    // PGE deliberately returns full candidate geometry. Process one URDF link at a
    // time and immediately reduce it to reviewed-profile evidence so the final2
    // inventory cannot retain every source mesh's convex-hull point cloud at once.
    // A link's adjacent visuals stay in the same PGE batch so PGE can create
    // one complete physical-link aggregate from all of its source assets.
    let mut results = Vec::with_capacity(requests.len());
    let mut link_results = Vec::new();
    let mut start = 0;
    while start < requests.len() {
        let link_name = requests[start].link_name.as_str();
        let mut end = start + 1;
        while end < requests.len() && requests[end].link_name == link_name {
            end += 1;
        }
        let pge_report =
            generate_link_asset_collision_candidates(&requests[start..end], generation_config);
        let reduced = pge_report
            .results
            .into_iter()
            .map(|result| match result {
                LinkAssetCollisionResult::Generated(generated) => {
                    Ok(Entry::Generated(GeneratedEntry {
                        link_name: generated.link_name,
                        asset_id: generated.asset_id,
                        asset_to_link: generated.asset_to_link,
                        provenance: generated.provenance,
                    }))
                }
                LinkAssetCollisionResult::Failed(failure) => Ok(Entry::Failed {
                    link_name: failure.link_name,
                    asset_id: failure.asset_id,
                    asset_path: failure.asset_path,
                    reason: format!("{:?}", failure.reason),
                }),
            })
            .collect::<Result<Vec<_>, String>>()?;
        results.extend(reduced);
        let reduced_links = pge_report
            .link_results
            .into_iter()
            .map(|result| match result {
                LinkCollisionAggregateResult::Generated(generated) => {
                    let selection = generated
                        .candidates
                        .select_compound_profile(maximum_reviewed_colliders)
                        .map_err(|error| error.to_string())?;
                    Ok(LinkEntry::Generated(GeneratedLinkEntry {
                        link_name: generated.link_name,
                        source_assets: generated.source_assets,
                        candidates: generated.candidates,
                        reviewed_profile: selection.profile,
                        selection_evidence: selection.evidence,
                    }))
                }
                LinkCollisionAggregateResult::Failed(failure) => Ok(LinkEntry::Failed {
                    link_name: failure.link_name,
                    asset_count: failure.asset_count,
                    generated_asset_count: failure.generated_asset_count,
                    reason: format!("{:?}", failure.reason),
                }),
            })
            .collect::<Result<Vec<_>, String>>()?;
        link_results.extend(reduced_links);
        start = end;
    }
    let report = Report {
        format: "puppybot.pge-link-collider-report.v1",
        generator: "puppybot-pge-link-collider-report",
        pge_collision_version: "0.1.0",
        generation_config,
        maximum_reviewed_colliders,
        results,
        link_results,
    };
    let text = serde_json::to_string_pretty(&report)
        .map_err(|error| format!("could not serialize report: {error}"))?;
    fs::write(&output, format!("{text}\n"))
        .map_err(|error| format!("could not write {}: {error}", output.display()))?;
    Ok(())
}
