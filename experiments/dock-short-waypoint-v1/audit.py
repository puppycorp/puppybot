#!/usr/bin/env python3
"""Audit short-waypoint outcome without inferring physical safety."""
import importlib.util
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


prior=load('waypoint_floor_audit',ROOT/'experiments/dock-floor-refresh-v1/audit.py')
prior.prior.original.base.__file__=str(HERE/'audit.py')
old_rows=prior.rows;old_retry=prior.retry_report


def rows(path):
    result=old_rows(path)
    if Path(path).name=='trace.jsonl':
        for row in result:row.get('case',{}).get('boxSearch',{}).pop('shortWaypoint',None)
    return result


def retry_report(trace,enabled):return old_retry(trace,True)


prior.prior.original.base.rows=rows
prior.retry_report=retry_report


def waypoint_report(trace,enabled):
    previous=None;attempt=None;accepted=None
    with Path(trace).open() as stream:
        for line in stream:
            row=json.loads(line);case=row.get('case',{});box=case.get('boxSearch',{})
            state=box.get('shortWaypoint') if isinstance(box,dict) else None
            if not enabled:
                if state is not None:raise ValueError('disabled waypoint metadata present')
                continue
            if (not isinstance(state,dict) or set(state)!={'attempted','accepted','plans'} or
                type(state['attempted']) is not bool or type(state['accepted']) is not bool or
                type(state['plans']) is not int or not 0<=state['plans']<=9):
                raise ValueError('invalid waypoint metadata')
            if state['accepted'] and not state['attempted']:raise ValueError('accepted waypoint without attempt')
            if previous and ((previous['attempted'] and not state['attempted']) or
                    (previous['accepted'] and not state['accepted']) or state['plans']<previous['plans']):
                raise ValueError('waypoint counters unexpectedly reset')
            if state['attempted'] and attempt is None:attempt=row['step']
            if state['accepted'] and accepted is None:
                nav=case.get('navigation',{});gripper=row.get('gripper',{})
                if (not state['plans'] or not isinstance(nav,dict) or type(nav.get('pathCount')) is not int or
                    not 1<=nav['pathCount']<=8 or not isinstance(gripper,dict) or gripper.get('held') is not True):
                    raise ValueError('accepted waypoint contradicts recorded path or payload')
                accepted=row['step']
            previous=state
    if enabled and previous is None:raise ValueError('waypoint metadata absent')
    return {'enabled':enabled,'attemptTick':attempt,'acceptedTick':accepted,
            'plans':previous['plans'] if previous else 0,
            'scope':'simulator counters and recorded route only; no motor, payload-clearance or physical safety attestation'}


def audit(root):
    root=Path(root).absolute();result=prior.audit(root)
    if all(arm.get('status')=='complete' for arm in result['arms']):
        result['shortWaypoint']={name:waypoint_report(root/name/'run/trace.jsonl',name=='candidate-search')
                                 for name in prior.prior.original.base.ARMS}
    else:result['shortWaypoint']={'status':'censored_incomplete_arm'}
    result['mechanismEligible']=False;result['mechanismCensorReason']='waypoint_swept_route_not_independently_attested'
    result['scope']=('one known simulator selection case; same binary and floor retry enabled in all arms; '
                     'short waypoint enabled only in candidate; no execution or physical safety attestation')
    return result


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    try:print(json.dumps(audit(sys.argv[1]),sort_keys=True))
    except (OSError,ValueError,KeyError,TypeError) as error:raise SystemExit('Invalid trial: '+str(error))
