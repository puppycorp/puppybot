#!/usr/bin/env python3
"""Unregistered fixed three-arm training-family simulator diagnostic."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
P=ROOT/'build/flex/sim/levels-v2/pitch82'
SCENES=ROOT/'build/flex/sim/expanded-rooms-v1/scenes'
BUILD=P/'l5-steering-hysteresis-build-v1'
MANIFEST=P/'l5-steering-hysteresis-plan-v1.json'
OUTPUT=P/'l5-steering-hysteresis-diagnostic-v1'
MODEL=P/'search-dagger-heading/models/heading-epoch8-pair/treatment'


def design():
    rows=[]
    for layout in (13,15,17):
        for variant in range(4,8):
            index=len(rows);rows.append({'index':index,'layout':layout,'variant':variant,'seed':6800200+index,'scene':str(SCENES/str(layout)/str(variant))})
    return {'schema':'puppybot.l5-steering-hysteresis-draft.v1','status':'draft_not_registered','conditions':rows,
            'arms':['control','kick','kick-hysteresis'],'episodesPerArm':12,'horizon':300,'level':5,'cameraPitch':82,'model':str(MODEL),
            'gate':{'windowAppliedActions':8,'allSpeedValuesNonzero':True,'minimumAdjacentReversals':6,
                    'odometryDisplacementMStrictlyBelow':.15,'odometryHeadingChangeDegreesStrictlyBelow':45,
                    'oncePerEpisode':True,'overrideDecisions':2,'cancelOnCarry':True,'cancelActiveOnContact':True,
                    'onlyAfterKickTrigger':True,'preserveSteeringAndSpeedMagnitude':True,'zeroSpeedRemainsZero':True},
            'denominator':'all 12 matched games per arm, including no-op and censored games',
            'prerequisite':'verify named history and scene inventory, independently reviewed frozen inputs and bounded monitored executor before any GPU run',
            'scope':'post-hoc rule derived from earlier saved training-family simulator trajectories; new training-family cases only, no held-out, physical or actor-execution attestation'}


if __name__=='__main__':raise SystemExit('Disabled; diagnostic is not registered or authorized to run.')
