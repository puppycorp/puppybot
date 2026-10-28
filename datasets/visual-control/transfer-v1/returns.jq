# Offline reference-pose diagnostic; none of these values enter the actor.
map(select(.state.findReturn.consumedIndex>=0)) |
map(. as $row |
  (.state.case.container.position[0]-.state.pose[0]) as $dx |
  (.state.case.container.position[1]-.state.pose[1]) as $dy |
  atan2($dy;$dx) as $bearing |
  ($bearing-.state.pose[2]) as $delta |
  ((atan2(($delta|sin);($delta|cos))|fabs)*180/3.141592653589793) as $heading |
  (($dx*$dx+$dy*$dy)|sqrt) as $range |
  ($range>=0.3 and $range<=0.65) as $band |
  ($band and $heading<=35) as $aligned |
  {step,pose:.state.pose,rangeM:$range,headingErrorDeg:$heading,inDockBand:$band,aligned:$aligned,
   cameraReady:($aligned and .state.case.dockVision.valid and
     .state.case.dockVision.frameId==.step and .state.case.dockVision.stableObservations>=3),
   stopped:(.action[1]==0),contact:(.proprio[5]==1),passed:.state.case.passed}) as $rows |
if ($rows|length)==0 then error("return diagnostic requires actual brick consumption") else
  ($rows|map(select(.inDockBand))|length) as $close |
  ($rows|map(select(.aligned))|length) as $aligned |
  ($rows|map(select(.cameraReady))|length) as $ready |
  ($rows|reduce .[] as $r ({current:0,maximum:0};
    if $r.cameraReady and $r.stopped then .current+=1|.maximum=([.maximum,.current]|max)
    else .current=0 end)|.maximum) as $hold |
  {caseIndex:$index,returned:$rows[-1].passed,framesAfterConsumption:($rows|length),
   initialBoxRangeM:$rows[0].rangeM,closest:($rows|min_by(.rangeM)),last:$rows[-1],
   framesInDockBand:$close,alignedFrames:$aligned,cameraReadyFrames:$ready,
   stoppedFrames:($rows|map(select(.stopped))|length),maximumReadyStoppedRun:$hold,
   contactFrames:($rows|map(select(.contact))|length),
   diagnosis:(if $rows[-1].passed then "returned"
     elif $close==0 then "never reaches docking band"
     elif $aligned==0 then "reaches box with wrong heading"
     elif $ready==0 then "aligned but fresh stable marker condition absent"
     else "does not hold stopped in ready pose" end)}
end
