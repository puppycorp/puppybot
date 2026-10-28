# Reconstruct teacher search goals from recorded pre-action state. This does
# not read case.objects or use the prop position in the reconstruction.
def near($a; $b): (($a-$b)|fabs) < 0.00001;
def same3($a; $b): all(range(0;3); . as $i | near($a[$i]; $b[$i]));
def point($rooms; $start; $index):
  ($index % (($rooms|length)*9)) as $ordinal |
  $rooms[(($start + (($ordinal/9)|floor)) % ($rooms|length))] as $r |
  ($ordinal % 9) as $cell | (($cell/3)|floor) as $row |
  (if $row == 1 then 2-($cell%3) else $cell%3 end) as $col |
  [$r[0]+($r[2]-$r[0])*($col+1)/4, $r[1]+($r[3]-$r[1])*($row+1)/4];
def forward_candidates($rooms; $start; $pose; $from; $to):
  [$pose[2]|cos, $pose[2]|sin] as $dir |
  [range($from;$to) as $i | point($rooms;$start;$i) as $p |
   ($p[0]-$pose[0]) as $x | ($p[1]-$pose[1]) as $y |
   (($x*$x+$y*$y)|sqrt) as $d |
   select($d>0.4 and $dir[0]*$x+$dir[1]*$y>0.5*$d) | {index:$i,distance:$d}];
def first_point($rooms; $start; $pose):
  forward_candidates($rooms;$start;$pose;9;(($rooms|length)*9)) as $other |
  (if ($other|length)>0 then $other else forward_candidates($rooms;$start;$pose;0;9) end) |
  if length==0 then 0 else min_by(.distance).index end;
def coverage_goal($rooms; $start; $pose; $first; $index):
  point($rooms;$start;$index) as $p | point($rooms;$start;($index+1)) as $next |
  [$p[0],$p[1],(if $index==$first then $pose[2] else atan2($next[1]-$p[1];$next[0]-$p[0]) end)];
def camera_goal($pre):
  $pre.case.perception.detections[0].targetM as $p | $pre.localization.pose as $local | $pre.pose as $pose |
  ($p[0]-$local[0]) as $x | ($p[1]-$local[1]) as $y |
  (($local[2]|cos)*$x+($local[2]|sin)*$y) as $forward |
  (($local[2]|cos)*$y-($local[2]|sin)*$x) as $lateral |
  (($pose[2]|cos)*$forward-($pose[2]|sin)*$lateral) as $dx |
  (($pose[2]|sin)*$forward+($pose[2]|cos)*$lateral) as $dy |
  atan2($dy;$dx) as $heading |
  [$pose[0]+$dx-0.24*($heading|cos),$pose[1]+$dy-0.24*($heading|sin),$heading];
$initial[0] as $initial_state | $layout[0].rooms as $rooms | $layout[0].startRoom as $start |
first_point($rooms;$start;$initial_state.pose) as $first |
if ($trace|length)==0 or ($trace|length)!=($decisions|length) then error("trace and action lengths differ") else . end |
[range(0;($trace|length)) as $i | $trace[$i] as $t | $decisions[$i] as $decision |
 (if $i==0 then $initial_state else $decisions[$i-1].state end) as $pre |
 (if $i==0 then $first else $trace[$i-1].coverageIndex end) as $previous |
 ($pre.findReturn.consumedIndex>=0) as $found |
 (if $t.source=="coverage" and ($found|not) then
     same3($t.goal; coverage_goal($rooms;$start;$initial_state.pose;$first;$t.coverageIndex))
  elif $t.source=="camera" and ($found|not) then
     (if ($pre.case.perception.detections|length)>0 and $pre.case.perception.frameId==$pre.totalSteps then
       ($pre.case.perception.detections[0].targetM[0]-$pre.localization.pose[0]) as $dx |
       ($pre.case.perception.detections[0].targetM[1]-$pre.localization.pose[1]) as $dy |
       (($dx*$dx+$dy*$dy)|sqrt) as $distance |
       $distance>=0.3 and $distance<=2 and same3($t.goal;camera_goal($pre)) else false end)
  elif $t.source=="return" and $found then true
  else false end) as $goal_ok |
 {step:$i,source:$t.source,goalMatchesSearchInputs:$goal_ok,
  labelMatchesOracle:near($t.label[0];$decision.state.trainingOracle.label[0]) and near($t.label[1];$decision.state.trainingOracle.label[1]),
  ordered:($t.step==$i and $t.coverageIndex >= $previous and $t.coverageIndex <= $previous+16 and $decision.state.totalSteps==$pre.totalSteps+10)}] as $rows |
if all($rows[]; .goalMatchesSearchInputs and .labelMatchesOracle and .ordered) then
  {passed:true,steps:($rows|length),coverageGoals:([$rows[]|select(.source=="coverage")]|length),cameraGoals:([$rows[]|select(.source=="camera")]|length),returnGoals:([$rows[]|select(.source=="return")]|length),reconstructedFromRoomBoundsAndRecordedCamera:true,oracleLabelsMatched:true,actorInputsChecked:false,teacherGeometryPrivileged:true,brickPositionNotReadBySearchReconstruction:true,independentTeacherExecutionReplay:false}
else error("coverage teacher trace does not match the recorded search inputs and oracle labels") end
