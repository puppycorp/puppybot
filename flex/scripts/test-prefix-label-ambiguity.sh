#!/usr/bin/env bash
# Identical complete prefixes constrain a deterministic recurrent actor.
set -euo pipefail
summary="$(realpath "${1:?Prefix audit executable required}")"
out="$(realpath -m "${2:?New output directory required}")"
[[ ! -e "$out" ]]; mkdir "$out"
perl -e 'use strict;use warnings;binmode STDOUT;print "PVDATA03",pack("Q< Q< Q<",4,2,3);for my $e(0..3){for my $t(0..2){my $image="\0"x21168;substr($image,0,1,"\1") if $e==3 && $t==2;print $image;}for my $t(0..2){my $row="\0"x56;substr($row,0,4,pack("f<",0.5)) if $t==0 && $e%2==0;substr($row,28,8,pack("f< f<",$e%2==0?-0.6:0,1));substr($row,36,12,pack("f< f< f<",($t>0 && $e%2==1)?1:0,1,1));print $row;}}' > "$out/data.bin"
"$summary" "$out/data.bin" > "$out/full.json"
"$summary" "$out/data.bin" --neutral-drive > "$out/neutral.json"
jq -e '.passed and (.driveFeedbackNeutralized|not) and .validFrames==12 and .distinctObservationPrefixes==7 and .conflictingPrefixesWithinSplit==0 and .minimumClassificationErrors==[0,0]' "$out/full.json" > /dev/null
jq -e '.passed and .driveFeedbackNeutralized and .supervisedFrames==[6,6] and .distinctObservationPrefixes==4 and .conflictingPrefixesWithinSplit==3 and .conflictingPrefixesWithMixedPhase==2 and .minimumClassificationErrors==[3,2] and .initialFrameErrors==[1,1] and .laterFrameErrors==[2,1] and .errorByPhase==[[1,1],[0,0],[2,1]] and .errorByTime==[[1,1],[2,1],[0,0],[0,0],[0,0],[0,0]] and .initialMemoryZero and .prefixBytesIndependentlyCompared and (.conflicts|length)==3 and (.conflictExamplesTruncated|not)' "$out/neutral.json" > /dev/null
# Identical later frames with different earlier images are different prefixes.
perl -e 'use strict;use warnings;binmode STDOUT;print "PVDATA03",pack("Q< Q< Q<",4,2,3);for my $e(0..3){for my $t(0..2){my $image="\0"x21168;substr($image,0,1,"\1") if $t==1 && $e%2==1;print $image;}for my $t(0..2){my $row="\0"x56;substr($row,28,8,pack("f< f<",$e%2==0?-0.6:0,1));substr($row,40,8,pack("f< f<",1,1));print $row;}}' > "$out/ancestry.bin"
"$summary" "$out/ancestry.bin" --neutral-drive > "$out/ancestry.json"
jq -e '.distinctObservationPrefixes==5 and .conflictingPrefixesWithinSplit==1 and .minimumClassificationErrors==[1,1] and .laterFrameErrors==[0,0]' "$out/ancestry.json" > /dev/null
cp "$out/data.bin" "$out/nonfinite.bin"
printf '\000\000\300\177' | dd of="$out/nonfinite.bin" bs=1 seek=$((32+3*21168)) conv=notrunc status=none
if "$summary" "$out/nonfinite.bin" > "$out/nonfinite.json" 2> "$out/nonfinite.log"; then echo 'Nonfinite feedback accepted.' >&2; exit 1; fi
rg -Fq 'nonfinite observation feedback' "$out/nonfinite.log"
head -c 100 "$out/data.bin" > "$out/truncated.bin"
if "$summary" "$out/truncated.bin" > "$out/bad.json" 2> "$out/bad.log"; then echo 'Truncated prefix dataset accepted.' >&2; exit 1; fi
if "$summary" "$out/data.bin" --bad > "$out/bad-option.json" 2> "$out/bad-option.log"; then echo 'Unknown prefix option accepted.' >&2; exit 1; fi
echo 'Prefix audit compares exact recurrent input histories, masks drive feedback and rejects malformed data.'
