#!/usr/bin/env bash
# Check exact-input grouping, split-specific disagreements and ignored labels.
set -euo pipefail
summary="${1:?Summary binary required}"
out="${2:?New output directory required}"
mkdir "$out"
perl -e 'use strict;use warnings;binmode STDOUT;print "PVDATA03",pack("Q< Q< Q<",8,4,1);for my $i(0..7){my $image="\0"x21168;substr($image,0,1,"\1") if $i==6;my $row="\0"x56;substr($row,0,4,pack("f<",0.5)) if $i==3;my $steering=($i==0 || $i==4)?-0.6:0;substr($row,28,8,pack("f< f<",$steering,1));substr($row,40,8,pack("f< f<",$i==2?0:1,1));print $image,$row;}' > "$out/data.bin"
"$summary" "$out/data.bin" > "$out/summary.json"
jq -e '.passed and .episodes==8 and .fittingHistories==4 and .supervisedInitialFrames==7 and .distinctInitialInputs==3 and .conflictingInputsWithinSplit==1 and .minimumInitialClassificationErrors==[1,1] and (.conflicts|length)==1 and .conflicts[0].fit==[1,1,0,0,0,0,0] and .conflicts[0].validation==[1,2,0,0,0,0,0] and ([.conflicts[0].examples[].episode]==[0,1,4,5,7]) and .initialMemoryZero and .actorInputsUnchanged' "$out/summary.json" > /dev/null
head -c 100 "$out/data.bin" > "$out/truncated.bin"
if "$summary" "$out/truncated.bin" > "$out/truncated.json" 2> "$out/truncated.log";then echo 'Truncated data accepted.' >&2;exit 1;fi
# Drive inputs are zeroed as a group, while contact remains part of the input.
perl -e 'use strict;use warnings;binmode STDOUT;print "PVDATA03",pack("Q< Q< Q<",4,2,1);for my $i(0..3){my $image="\0"x21168;my $row="\0"x56;substr($row,0,4,pack("f<",0.5)) if $i%2==0;substr($row,20,4,pack("f<",1)) if $i>=2;substr($row,28,8,pack("f< f<",$i%2==0?-0.6:0,1));substr($row,40,8,pack("f< f<",1,1));print $image,$row;}' > "$out/neutral-data.bin"
"$summary" "$out/neutral-data.bin" > "$out/full-feedback.json"
"$summary" "$out/neutral-data.bin" --neutral-drive > "$out/neutral-feedback.json"
jq -e '.passed and (.driveFeedbackNeutralized|not) and .distinctInitialInputs==4 and .conflictingInputsWithinSplit==0 and .minimumInitialClassificationErrors==[0,0]' "$out/full-feedback.json" > /dev/null
jq -e '.passed and .driveFeedbackNeutralized and .distinctInitialInputs==2 and .conflictingInputsWithinSplit==2 and .minimumInitialClassificationErrors==[1,1] and .initialMemoryZero and .actorInputsUnchanged' "$out/neutral-feedback.json" > /dev/null
if "$summary" "$out/neutral-data.bin" --unknown > "$out/unknown.json" 2> "$out/unknown.log"; then echo 'Unknown initial-label option accepted.' >&2; exit 1; fi
echo 'Initial-label audit groups exact actor inputs and counts split-specific conflicts.'
