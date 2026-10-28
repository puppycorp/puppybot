#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
output="${1:?New summary file is required}"
[[ ! -e "$output" ]]
/usr/bin/jq -e '.passed and .episodes==222 and .existingDataBytePreserved' "$base/contact-admission-v1/coverage.json" > /dev/null
/usr/bin/jq -e '.passed and .episodes==222 and .actorInputsUnchanged' "$base/contact-labels-v1/targets/receipt.json" > /dev/null
for comparison in "$base/contact-quick-v1/comparison.json" "$base/return-quick-v1/comparison.json" "$base/return-quick-final-v1/comparison.json";do
    /usr/bin/jq -e '.exploratory and .allEpisodeAuditsPassed and (.qualifiesForPromotion|not)' "$comparison" > /dev/null
done
/usr/bin/jq -e '.audited and .episodes==16 and .notStudentTaskPerformance' "$base/contact-cohort-diagnostic-v1/result.json" > /dev/null
/usr/bin/jq -e '.audited and .notAutonomousWholeEpisodePerformance and (.rows|length)==2' "$base/return-pilot-diagnostic-v1/result.json" > /dev/null
/usr/bin/jq -e --slurpfile data "$base/contact-admission-v1/coverage.json" '.dataSHA256==$data[0].dataSHA256 and .caseHashesInBothSplits==0 and .environmentHashesInBothSplits==0' "$base/case-duplication-analysis-v4/result.json" > /dev/null
/usr/bin/jq -e '.allEpisodeAuditsPassed and .original.episodes==32 and .expanded.episodes==32' "$project/datasets/visual-control/expanded-rooms-v1/matched-comparison-results.json" > /dev/null
/usr/bin/jq -e '.audited and .episodes==12 and .studentReturnsAfterTeacherApproach==1 and .notAutonomousWholeEpisodePerformance' "$base/return-cohort-diagnostic-v1/result.json" > /dev/null
/usr/bin/jq -n --slurpfile data "$base/contact-admission-v1/coverage.json" --slurpfile labels "$base/contact-labels-v1/targets/receipt.json" --slurpfile cases "$base/case-duplication-analysis-v4/result.json" --slurpfile matched "$project/datasets/visual-control/expanded-rooms-v1/matched-comparison-results.json" --slurpfile cohortReturn "$base/return-cohort-diagnostic-v1/result.json" --slurpfile contacts "$base/contact-cohort-diagnostic-v1/result.json" --slurpfile contact "$base/contact-quick-v1/comparison.json" --slurpfile selected "$base/return-quick-v1/comparison.json" --slurpfile last "$base/return-quick-final-v1/comparison.json" --slurpfile returns "$base/return-pilot-diagnostic-v1/result.json" --slurpfile motion "$base/return-quick-motion-v1/result.json" '
  def score: {episodes,auditedEpisodes,auditedApproaches,physicalReturns,openReturns,hiddenReturns};
  {task:"simulator consumes a brick approached within 35 cm; robot must return and dock",scope:"adaptive eight-case development screens; no physical pickup or independent final-layout claim",runtimeInputs:["TCP RGB","own feedback","recurrent state"],teacherSimulatorStateTrainingOnly:true,
   dataset:{episodes:$data[0].episodes,fittingHistories:$data[0].fittingHistories,validationHistories:$data[0].validationHistories,dataSHA256:$data[0].dataSHA256,priorHistoriesPreserved:$data[0].previousHistoriesRetained,uniqueFittingCaseHashes:$cases[0].uniqueFittingCaseHashes,uniqueValidationCaseHashes:$cases[0].uniqueValidationCaseHashes,caseHashesInBothSplits:$cases[0].caseHashesInBothSplits,environmentHashesInBothSplits:$cases[0].environmentHashesInBothSplits,targetSHA256:$labels[0].targetsSHA256,fittingTargetCandidates:$labels[0].fittingCandidates,validationTargetCandidates:$labels[0].validationCandidates,targetVisibilityHeuristicNotProvenSegmentation:true},
   matchedDevelopmentComparison:{allEpisodeAuditsPassed:$matched[0].allEpisodeAuditsPassed,original:{approaches:$matched[0].original.approaches,returns:$matched[0].original.returns},expanded:{approaches:$matched[0].expanded.approaches,returns:$matched[0].expanded.returns},sharedTwoRoomStartView:true},
   recoveryCollection:{episodes:$contacts[0].episodes,studentActions:$contacts[0].studentActions,postContactDecisions:$contacts[0].afterBlocked,studentRepeatedPriorAction:$contacts[0].studentRepeated,oracleReversedDriveDirection:$contacts[0].teacherDirectionReversed},
   contactContinuation:{initial:($contact[0].initial|score),continued:($contact[0].continued|score),allEpisodeAuditsPassed:$contact[0].allEpisodeAuditsPassed},
   returnPilot:{teacherAssisted:true,episodes:[$returns[0].rows[]|{fit,teacherApproachActions,studentReturnActions,oracleDiffers,validBoxVisionFrames,studentReturnedAfterTeacherApproach}],auditedCohortWindows:{episodes:$cohortReturn[0].episodes,studentReturnsAfterTeacherApproach:$cohortReturn[0].studentReturnsAfterTeacherApproach,studentReturnActions:$cohortReturn[0].studentReturnActions,oracleDiffers:$cohortReturn[0].oracleDiffers}},
   returnContinuation:{selectedCheckpointUnchanged:true,initial:($selected[0].initial|score),selected:($selected[0].continued|score),postHocEpoch20:($last[0].epoch20|score),allSelectedAuditsPassed:$selected[0].allEpisodeAuditsPassed,allPostHocAuditsPassed:$last[0].allEpisodeAuditsPassed,motion:[$motion[0].arms[]|{candidate,stop,blocked,meanPathM,meanMaxExcursionM,hiddenLeftStartRoom}]},
   promotionQualified:false,retainedPolicyOverwritten:false}' > "$output"
/usr/bin/jq -e '.dataset.episodes==222 and .recoveryCollection.episodes==16 and .contactContinuation.continued.auditedApproaches==1 and .contactContinuation.continued.physicalReturns==0 and .returnContinuation.selectedCheckpointUnchanged and .returnContinuation.postHocEpoch20.physicalReturns==0 and (.promotionQualified|not)' "$output" > /dev/null
echo 'Recovery progress summary written from audited artifacts.'
