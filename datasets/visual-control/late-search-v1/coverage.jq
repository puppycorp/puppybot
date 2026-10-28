def merge_ok($m;$a;$b):
  $m.episodes==($a.episodes+$b.episodes) and $m.fitTrajectories==($a.fitTrajectories+$b.fitTrajectories) and
  $m.sourceSHA256==[$a.dataSHA256,$b.dataSHA256] and
  ($m.records|map(.index))==[range(0;$m.episodes)] and ($m.records|all(.fit==(.index<$m.fitTrajectories))) and
  ($m.records|map(select(.source==0)|.sourceIndex)|sort)==[range(0;$a.episodes)] and
  ($m.records|map(select(.source==1)|.sourceIndex)|sort)==[range(0;$b.episodes)] and
  ($m.records|all(if .source==0 then .fit==(.sourceIndex<$a.fitTrajectories)
                 elif .source==1 then .fit==(.sourceIndex<$b.fitTrajectories) else false end));
$workers[0] as $w |
{episodes:142,fitTrajectories:112,dataSHA256:"852a80123d19dc45e6ec78587c5ea19c30388d9381c7d634faebb22501f349f9"} as $base |
(reduce range(0;5) as $i ({passed:true,meta:$w[0]};
  .passed=(.passed and merge_ok($merges[0][$i];.meta;$w[$i+1])) | .meta=$merges[0][$i])) as $chain |
{passed:(($w|length)==6 and ($w|map(.worker))==[0,1,2,3,4,5] and
  ($w|all(.episodes==5 and .fitTrajectories==4 and .auditedEpisodes==5 and .physicalCompletions==5 and .studentCommands>=1 and .studentCommands<=600)) and
  $state[0].passed and $state[0].fittingLaterDisagreements>=300 and $state[0].fittingHistoriesWith20LaterDisagreements>=8 and
  ($state[0].sources|map(.dataSHA256))==($w|map(.dataSHA256)) and
  $catalog[0].fittingScenes==24 and $catalog[0].validationScenes==6 and ($catalog[0].records|length)==30 and
  ($catalog[0].records|all(.fit==(.episode<4) and (if .fit then .layout==.worker else .layout==6+.worker%2 end))) and
  ($catalog[0].records|map(select(.fit)|.layout)|unique)==[0,1,2,3,4,5] and
  $old[0].passed and $old[0].episodes==142 and $old[0].fittingHistories==112 and $old[0].dataSHA256==$base.dataSHA256 and
  ($merges[0]|length)==5 and $chain.passed and merge_ok($final[0];$base;$chain.meta) and
  $final[0].episodes==172 and $final[0].fitTrajectories==136 and $final[0].sequenceLength<=512),
 episodes:$final[0].episodes,fittingHistories:$final[0].fitTrajectories,
 validationHistories:($final[0].episodes-$final[0].fitTrajectories),existingHistoriesRetained:142,newAuditedHistories:30,
 fittingLaterDisagreements:$state[0].fittingLaterDisagreements,
 fittingHistoriesWith20LaterDisagreements:$state[0].fittingHistoriesWith20LaterDisagreements,
 sourceAudits:$w,dataSHA256:$final[0].dataSHA256,completeHistoriesAndOriginalRolesPreserved:true,
 studentInputsUnchanged:true,finalLayoutsExcludedFromFitting:[10,11],teacherSuccessIsNotAutonomousPerformance:true}
