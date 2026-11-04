"""Synthetic simulator-only trial records for CPU audit tests."""
import hashlib
import json
import struct
from pathlib import Path

ACTION=struct.pack('<2f',0.0,0.2)
ZERO_ACTION=bytes(8)
RGB=bytes(21168)
HIDDEN=bytes(512)


def write_json(path,value):Path(path).write_text(json.dumps(value,sort_keys=True)+'\n')


def observation(sequence,tick,owner,ack,drive,detections=0):
    valid=owner==0
    return {'schema':'puppybot.physical-agent.v1','sequence':sequence,'step':tick,'timeMs':tick*20,
            'owner':owner,'ack':ack,'imageValid':valid,'rgbDetections':detections if valid else None,
            'driveCommand':drive,'jointTicks':[1,2,3,4],'totalSteps':tick,'cameraFrame':tick if valid else -1,
            'cameraDriving':valid,'cameraStill':valid}


def build_protocol(run,mode='baseline',polls=1499):
    """A fixed 90-action control or search sequence; no physical claims."""
    run=Path(run);run.mkdir(parents=True);actors=run/'actors';actors.mkdir()
    rows=[observation(1,100,0,0,[0,0,90])];intents=[{'sequence':1,'command':1,'steering':0,'speed':0,'hold':0}]
    for i in range(90):
        previous=rows[-1];stem=actors/f"actor-{previous['sequence']}"
        (Path(str(stem)+'.rgb')).write_bytes(RGB);(Path(str(stem)+'.hidden')).write_bytes(HIDDEN)
        (Path(str(stem)+'.action')).write_bytes(ACTION)
        feedback=(ZERO_ACTION if i==0 else ACTION)+struct.pack('<5f',*(0,0,0,0,0) if i==0 else (.12,.12,0,0,0))
        (Path(str(stem)+'.feedback')).write_bytes(feedback)
        seq=previous['sequence']+1;tick=previous['totalSteps']+10
        rows.append(observation(seq,tick,0,1,[12,12,90]))
        intents.append({'sequence':seq,'command':2,'steering':0,'speed':200,'hold':10})
    search=mode in ('search','target-race','lost-target');handoff=mode=='target-race'
    if search:
        seq=rows[-1]['sequence']+1;tick=rows[-1]['totalSteps']+2
        row=observation(seq,tick,1,8,[0,0,90]) if mode=='search' else observation(seq,tick,0,2,[0,0,90],1)
        rows.append(row);intents.append({'sequence':seq,'command':8,'steering':0,'speed':0,'hold':0})
        if mode!='search':
            seq+=1;tick+=2
            rows.append(observation(seq,tick,1,3,[0,0,90]) if handoff else observation(seq,tick,0,2,[0,0,90],0))
            intents.append({'sequence':seq,'command':6,'steering':0,'speed':0,'hold':0})
        if mode!='lost-target':
            for _ in range(polls):
                seq=rows[-1]['sequence']+1;tick=rows[-1]['totalSteps']+20
                rows.append(observation(seq,tick,1,4,[0,0,90]));intents.append({'sequence':seq,'command':7,'steering':0,'speed':0,'hold':20})
    seq=rows[-1]['sequence']+1;tick=rows[-1]['totalSteps']
    rows.append(observation(seq,tick,2,7,[0,0,90]));intents.append({'sequence':seq,'command':3,'steering':0,'speed':0,'hold':0})
    trace=run/'trace.jsonl';trace.write_text('synthetic test trace\n')
    result={'policyActions':90,'handoff':handoff,'collectorTerminal':False,'navigationActionLimit':90,'collectorPollLimit':1499,
            'stoppedRescanEnabled':False,'stoppedRescanAttempts':0,'stoppedRescanHandoff':False,'stoppedRescanStopReason':0,
            'stoppedRescanStopReasonText':'none','stopCommandAcknowledged':True,'outcome':'unverified',
            'traceSHA256':hashlib.sha256(trace.read_bytes()).hexdigest()}
    if search:result['searchFallbackStarted']=mode=='search'
    write_json(run/'inputs.json',{'searchFallbackEnabled':True} if search else {})
    write_protocol(run,rows,intents,result,search)
    return rows,intents,result


def write_protocol(run,rows,intents,result,enabled):
    run=Path(run);(run/'physical-agent.jsonl').write_text(''.join(json.dumps(row,sort_keys=True)+'\n' for row in rows))
    if enabled:(run/'search-requests.jsonl').write_text(''.join(json.dumps(row,sort_keys=True)+'\n' for row in intents))
    write_json(run/'result.json',result)
