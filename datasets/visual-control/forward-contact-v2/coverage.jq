def merge_ok($m;$a;$b):
  $m.episodes==($a.episodes+$b.episodes) and $m.fitTrajectories==($a.fitTrajectories+$b.fitTrajectories) and
  $m.sourceSHA256==[$a.dataSHA256,$b.dataSHA256] and
  ($m.records|map(.index))==[range(0;$m.episodes)] and ($m.records|all(.fit==(.index<$m.fitTrajectories))) and
  ($m.records|map(select(.source==0)|.sourceIndex)|sort)==[range(0;$a.episodes)] and
  ($m.records|map(select(.source==1)|.sourceIndex)|sort)==[range(0;$b.episodes)] and
  ($m.records|all(if .source==0 then .fit==(.sourceIndex<$a.fitTrajectories)
                 elif .source==1 then .fit==(.sourceIndex<$b.fitTrajectories) else false end));
$workers[0] as $w |
{episodes:132,fitTrajectories:104,dataSHA256:"d709d3378a1241c34ec885e1cce131dfa9cc5984208032a031ed315a4ba70eff"} as $base |
{passed:(($w|length)==2 and ($w|map(.worker))==[0,1] and
  ($w|all(.episodes==5 and .fitTrajectories==4 and .auditedEpisodes==5 and .physicalCompletions==5 and .studentCommands==(.window*5))) and
  ($w|map(.window))==[60,8] and ($w|map(.fittingForwardContactFrames)|add)>=200 and
  $state[0].passed and $state[0].newFittingForwardContactFrames==($w|map(.fittingForwardContactFrames)|add) and
  ($state[0].sources|map(.dataSHA256))==($w|map(.dataSHA256)) and
  $catalog[0].fittingScenes==8 and $catalog[0].validationScenes==2 and ($catalog[0].records|length)==10 and
  ($catalog[0].records|all(.fit==(.episode<4) and (if .fit then .layout==5 else .layout==6+.worker end))) and
  $old[0].passed and $old[0].episodes==132 and $old[0].fittingHistories==104 and
  merge_ok($new[0];$w[0];$w[1]) and merge_ok($final[0];$base;$new[0]) and
  $final[0].episodes==142 and $final[0].fitTrajectories==112 and $final[0].sequenceLength<=354),
 episodes:$final[0].episodes,fittingHistories:$final[0].fitTrajectories,
 validationHistories:($final[0].episodes-$final[0].fitTrajectories),existingHistoriesRetained:132,newAuditedHistories:10,
 newFittingForwardContactFrames:($w|map(.fittingForwardContactFrames)|add),
 sourceAudits:$w,dataSHA256:$final[0].dataSHA256,completeHistoriesAndOriginalRolesPreserved:true,
 independentJournalContactCountsMatched:true,studentInputsUnchanged:true,finalLayoutsExcludedFromFitting:[10,11],
 teacherSuccessIsNotAutonomousPerformance:true}
