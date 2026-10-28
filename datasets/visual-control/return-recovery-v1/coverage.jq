# Follow the actual native merge receipts to original source episodes.
[ $final[0].records[] as $r |
  if $r.source==0 then
    $base[0].records[$r.sourceIndex] as $b |
    {index:$r.index,fit:$r.fit,source:"base",sourceIndex:$b.sourceIndex,layout:($b.sourceIndex/16|floor),scene:($b.sourceIndex%16),audit:$old[0].dataSHA256}
  else
    $corrections[0].records[$r.sourceIndex] as $c |
    (if $c.source==0 then $first[0] else $second[0] end).records[$c.sourceIndex] as $p |
    (($c.source*2)+$p.source) as $worker |
    ($catalog[0]|map(select(.worker==$worker and .sourceIndex==$p.sourceIndex))|first) as $case |
    {index:$r.index,fit:$r.fit,source:"correction",worker:$worker,sourceIndex:$p.sourceIndex,layout:$case.layout,scene:$case.scene,audit:$audits[$worker].dataSHA256}
  end
] as $rows |
if ($rows|length)!=96 or ($rows|map(select(.fit))|length)!=72 or
   (all($rows[];.fit==(.layout<6))|not) or
   (all($rows[]; .layout>=0 and .layout<8 and .scene>=0 and .scene<16 and (.audit|type)=="string")|not) or
   (all($rows[]|select(.source=="correction"); .fit==(.sourceIndex<6))|not) or
   (all($base[0].records[];.fit==(.sourceIndex<96))|not) or
   $old[0].passed!=true or $old[0].episodes!=128 or $old[0].dataSHA256!=$base[0].sourceSHA256 or
   $final[0].sourceSHA256[0]!=$base[0].dataSHA256 or $final[0].sourceSHA256[1]!=$corrections[0].dataSHA256 or
   $corrections[0].sourceSHA256[0]!=$first[0].dataSHA256 or $corrections[0].sourceSHA256[1]!=$second[0].dataSHA256 or
   $first[0].sourceSHA256[0]!=$audits[0].dataSHA256 or $first[0].sourceSHA256[1]!=$audits[1].dataSHA256 or
   $second[0].sourceSHA256[0]!=$audits[2].dataSHA256 or $second[0].sourceSHA256[1]!=$audits[3].dataSHA256 or
   ($audits|length)!=4 or (all($audits[];.passed and .episodes==8 and .datasetEpisodes==8 and .firstEpisode==0 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .taskEventHintAbsent)|not)
then error("Native source audits do not cover all96 histories with original split roles")
else {passed:true,auditMode:"Native source audits with exact source SHA and episode indices, byte-preserving native subset/merges and identical native repack",selectedHistories:96,fittingHistories:72,validationHistories:24,baseSourceAudit:$old[0],correctionSourceAudits:$audits,allOriginalSplitRolesPreserved:true,studentInputsUnchanged:true,maximumBrickDistanceM:0.35,records:$rows} end
