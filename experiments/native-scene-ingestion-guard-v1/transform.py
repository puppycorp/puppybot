#!/usr/bin/env python3
"""Apply a guarded-collector-only integration to copied control sources."""


def once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('guard integration anchor missing or ambiguous')
    return text.replace(before, after, 1)


def main_source(text):
    text = once(text, '            if pl_equal(flag,"--output") {vw_output=vc_absolute(value);}',
                '            if pl_equal(flag,"--scene-guard-policy") {vc_require(!vg_policy,"duplicate scene guard policy");vg_policy=vc_absolute(value);}\n'
                '            else if pl_equal(flag,"--scene-guard-sha256") {vc_require(!vg_expected_sha,"duplicate scene guard digest");vg_expected_sha=value;}\n'
                '            else if pl_equal(flag,"--scene-guard-selection") {vc_require(!vg_selection_manifest,"duplicate selection reservation");vg_selection_manifest=vc_absolute(value);}\n'
                '            else if pl_equal(flag,"--scene-guard-heldout") {vc_require(!vg_heldout_manifest,"duplicate heldout reservation");vg_heldout_manifest=vc_absolute(value);}\n'
                '            else if pl_equal(flag,"--output") {vw_output=vc_absolute(value);}')
    return once(text, '    vc_require(vw_output,"--output DIRECTORY is required");',
                '    vc_require(vw_output,"--output DIRECTORY is required");\n'
                '    vc_require(pl_equal(command,"collect") && vw_chase && vw_fetch && vw_catalog && !vw_scene && vg_policy && vg_expected_sha && vg_selection_manifest && vg_heldout_manifest,"protected binary only permits guarded fetch catalog collection");')


def chase_source(text):
    text = once(text, 'import "workflow.flex";', 'import "workflow.flex";\nimport "scene-guard.flex";')
    text = once(text, 'fn vx_scene(episode) {if vw_catalog {return vc_path(vw_catalog,vc_int(episode));}return vw_scene;}',
                'fn vx_scene(episode) {vc_require(vg_directory,"scene snapshots were not prepared");return vc_path(vg_directory,vc_int(episode));}')
    anchor = 'vc_require(vw_horizon<=512,"collection horizon must be in 1..512");vc_mkdir(vw_output);'
    return once(text, anchor, anchor + 'vg_prepare(vw_output,vw_catalog,vw_episodes,vw_validation,vw_seed);')
