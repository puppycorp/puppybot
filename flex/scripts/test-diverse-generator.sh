#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
out="${1:?A new output directory is required}"
mkdir "$out"
out="$(cd "$out" && pwd)"
generator="${PUPPYBOT_DIVERSE_GENERATOR:-$project/build/flex/control/diverse-generator}"
verify="${PUPPYBOT_DIVERSE_VALIDATOR:-$project/build/flex/control/diverse-scene-tests}"
"$generator" "$out/fit" 26 30 fit > "$out/fit.log"
"$generator" "$out/fit-repeat" 26 30 fit > "$out/fit-repeat.log"
"$generator" "$out/validation" 126 130 validation > "$out/validation.log"
"$generator" "$out/validation-repeat" 126 130 validation > "$out/validation-repeat.log"
"$generator" "$out/development" 180 188 development > "$out/development.log"
"$generator" "$out/wide-development" 218 226 wide-development --wide-heading > "$out/wide-development.log"
"$verify" "$out/fit" 26 30 fit > "$out/verify-fit.log"
"$verify" "$out/validation" 126 130 validation > "$out/verify-validation.log"
"$verify" "$out/development" 180 188 validation > "$out/verify-development.log"
"$verify" "$out/wide-development" 218 226 validation --wide-heading > "$out/verify-wide-development.log"
jq -s -e 'length==8 and all(.[];.wideHeading==true) and ([.[].startPose[2]]|unique|length)==8 and any(.startPose[2]>1.57) and any(.startPose[2]< -1.57)' "$out/wide-development/"{218,219,220,221,222,223,224,225}/layout.json > /dev/null
for group in fit validation;do
    (cd "$out/$group" && find -L . -type f -print0 | sort -z | xargs -0 sha256sum) > "$out/$group.sha256"
    (cd "$out/$group-repeat" && find -L . -type f -print0 | sort -z | xargs -0 sha256sum) > "$out/$group-repeat.sha256"
    cmp "$out/$group.sha256" "$out/$group-repeat.sha256"
done
jq -s -e 'length==8 and ([.[].layoutId]|unique|length)==8 and ([.[].rooms]|unique|length)==8 and ([.[].startPose]|unique|length)==8 and ([.[].obstacles]|unique|length)==8 and ([.[]|select(.fit)]|length)==4 and ([.[]|select(.fit|not)]|length)==4' "$out/fit/"{26,27,28,29}/layout.json "$out/validation/"{126,127,128,129}/layout.json > /dev/null
if "$generator" "$out/rejected-reserved" 10 12 fit > "$out/rejected-reserved.log" 2>&1;then echo 'Reserved IDs were accepted for fitting.' >&2;exit 1;fi
if "$generator" "$out/rejected-validation" 26 27 validation > "$out/rejected-validation.log" 2>&1;then echo 'Fitting IDs were accepted for validation.' >&2;exit 1;fi
if "$generator" "$out/rejected-fitting" 126 127 fit > "$out/rejected-fitting.log" 2>&1;then echo 'Validation IDs were accepted for fitting.' >&2;exit 1;fi
if "$generator" "$out/rejected-development-validation" 179 181 validation > "$out/rejected-development-validation.log" 2>&1;then echo 'Development IDs were accepted for validation.' >&2;exit 1;fi
if "$generator" "$out/rejected-development-range" 179 180 development > "$out/rejected-development-range.log" 2>&1;then echo 'A non-development ID was accepted for development.' >&2;exit 1;fi
if "$generator" "$out/rejected-wide-validation" 217 219 validation > "$out/rejected-wide-validation.log" 2>&1;then echo 'Wide-development IDs were accepted for validation.' >&2;exit 1;fi
if "$generator" "$out/rejected-wide-flag" 218 226 wide-development > "$out/rejected-wide-flag.log" 2>&1;then echo 'Wide-development IDs were accepted without wide headings.' >&2;exit 1;fi
if "$generator" "$out/rejected-old-wide" 180 181 development --wide-heading > "$out/rejected-old-wide.log" 2>&1;then echo 'Existing development IDs were accepted with wide headings.' >&2;exit 1;fi
[[ ! -e "$out/rejected-reserved" && ! -e "$out/rejected-validation" && ! -e "$out/rejected-fitting" && ! -e "$out/rejected-development-validation" && ! -e "$out/rejected-development-range" && ! -e "$out/rejected-wide-validation" && ! -e "$out/rejected-wide-flag" && ! -e "$out/rejected-old-wide" ]]
mkdir "$out/bad-geometry"
cp -aL "$out/fit/27" "$out/bad-geometry/27"
jq '.obstacles[0][0]+=.5' "$out/bad-geometry/27/layout.json" > "$out/altered-layout.json"
mv "$out/altered-layout.json" "$out/bad-geometry/27/layout.json"
if "$verify" "$out/bad-geometry" 27 28 fit > "$out/bad-geometry.log" 2>&1;then echo 'Changed obstacle metadata was accepted.' >&2;exit 1;fi
mkdir "$out/bad-target"
cp -aL "$out/fit/27" "$out/bad-target/27"
jq '.objects[0].position[0]=0' "$out/bad-target/27/0/case.json" > "$out/altered-case.json"
mv "$out/altered-case.json" "$out/bad-target/27/0/case.json"
if "$verify" "$out/bad-target" 27 28 fit > "$out/bad-target.log" 2>&1;then echo 'A target in the wrong room was accepted.' >&2;exit 1;fi
jq -n '{passed:true,runtime:"Flexscript",pythonRequired:false,trainingLayouts:4,validationLayouts:4,developmentLayouts:8,wideHeadingDevelopmentLayouts:8,cases:384,deterministic:true,disjointRoleRanges:true,physicalGeometryChecked:true,tamperedGeometryAndTargetsRejected:true,teacherReachabilityNotEstablished:true}' > "$out/result.json"
echo 'Diverse room generation and geometry contracts passed.'
