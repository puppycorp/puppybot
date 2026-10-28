def merge_ok($m;$a;$b):
  $m.episodes==($a.episodes+$b.episodes) and
  $m.fitTrajectories==($a.fitTrajectories+$b.fitTrajectories) and
  $m.sourceSHA256==[$a.dataSHA256,$b.dataSHA256] and
  ($m.records|map(.index))==[range(0;$m.episodes)] and
  ($m.records|all(.fit==(.index<$m.fitTrajectories))) and
  ($m.records|map(select(.source==0)|.sourceIndex)|sort)==[range(0;$a.episodes)] and
  ($m.records|map(select(.source==1)|.sourceIndex)|sort)==[range(0;$b.episodes)] and
  ($m.records|all(if .source==0 then .fit==(.sourceIndex<$a.fitTrajectories)
                 elif .source==1 then .fit==(.sourceIndex<$b.fitTrajectories) else false end));
($workers[0]) as $w |
{episodes:96,fitTrajectories:72,dataSHA256:"a4dd1b61727f82e7ed044ebaf89268509cf47631a1392f7caa8249d826f3d6f8"} as $base |
{passed:(($w|length)==4 and ($w|map(.worker))==[0,1,2,3] and
  ($w|all(.episodes==9 and .fitTrajectories==8 and .auditedEpisodes==9 and .physicalCompletions==9 and .studentCommands==0)) and
  $catalog[0].fittingScenes==32 and $catalog[0].validationScenes==4 and
  ($catalog[0].records|length)==36 and ($catalog[0].records|all(.fit==(.layout<6) and .layout<8)) and
  $old[0].passed and $old[0].selectedHistories==96 and $old[0].allOriginalSplitRolesPreserved and
  merge_ok($m01[0];$w[0];$w[1]) and merge_ok($m012[0];$m01[0];$w[2]) and
  merge_ok($new[0];$m012[0];$w[3]) and merge_ok($final[0];$base;$new[0]) and
  $final[0].episodes==132 and $final[0].fitTrajectories==104 and $final[0].sequenceLength<=354),
 episodes:$final[0].episodes,fittingHistories:$final[0].fitTrajectories,
 validationHistories:($final[0].episodes-$final[0].fitTrajectories),
 existingHistoriesRetained:96,newAuditedHistories:36,
 sourceAudits:$w,dataSHA256:$final[0].dataSHA256,
 completeHistoriesAndOriginalRolesPreserved:true,studentInputsUnchanged:true,
 finalLayoutsExcludedFromData:[10,11],teacherSuccessIsNotNeuralSuccess:true}
