[ $final[0].records[] as $r |
  if $r.source==0 then $base[0].records[$r.sourceIndex] as $b |
    {index:$r.index,fit:$r.fit,source:"base",sourceIndex:$b.sourceIndex,layout:($b.sourceIndex/16|floor),scene:($b.sourceIndex%16),audit:$old[0].dataSHA256}
  else $selected[0].records[$r.sourceIndex] as $s |
    {index:$r.index,fit:$r.fit,source:"correction",worker:$s.worker,catalogIndex:$s.catalogIndex,layout:$s.layout,scene:$s.scene,sourceData:$s.sourceData,sourceEpisode:$s.sourceEpisode,auditReceipt:$s.auditReceipt,auditReceiptSHA256:$s.auditReceiptSHA256}
  end
] as $rows |
if ($rows|length)!=96 or ($rows|map(select(.fit))|length)!=72 or
   (all($rows[];.fit==(.layout<6) and .layout>=0 and .layout<8 and .scene>=0 and .scene<16)|not) or
   $selected[0].episodes!=32 or $selected[0].fitTrajectories!=24 or
   $selected[0].allSelectedHistoriesHaveAudits!=true or $selected[0].allOriginalSceneIdentitiesPreserved!=true or $selected[0].splitRolesPreserved!=true or
   (all($selected[0].records[];.fit==(.catalogIndex<6) and .layout==.catalogIndex and .scene==((.worker*3+.catalogIndex*2)%16))|not) or
   ($selected[0].records|map([.worker,.catalogIndex])|unique|length)!=32 or
   $old[0].passed!=true or $old[0].episodes!=128 or $old[0].dataSHA256!=$base[0].sourceSHA256 or
   $final[0].sourceSHA256[0]!=$base[0].dataSHA256 or $final[0].sourceSHA256[1]!=$selected[0].dataSHA256
then error("Native audited source selection does not cover all96 histories with original scene roles")
else {passed:true,auditMode:"Native per-source audits with exact SHA and episode coverage, exact native source selection and byte-identical native repack",selectedHistories:96,fittingHistories:72,validationHistories:24,allOriginalSplitRolesPreserved:true,studentInputsUnchanged:true,maximumBrickDistanceM:0.35,baseSourceAudit:$old[0],correctionSelection:$selected[0],records:$rows} end
