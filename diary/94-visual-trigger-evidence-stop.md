# Visual trigger evidence failure: simulated stop path (3 Nov 2026)

The experimental hybrid visual-search client previously terminated before
sending a stop if it could not create or write the visual-stall trigger image.
A separate source transform now routes that specific failure to the normal
simulated stop path, preserves any existing or partial image, declines the
search transfer and, after a validated stop response, reports
`trigger_evidence_unavailable` with the episode still `unverified`.

The stop command normally writes its intent journal before sending. For this
failure branch only, the staged client skips that pre-send journal write so an
unavailable journal does not itself prevent the stop request. This intentionally
leaves an incomplete protocol record: the previous saved-run auditor rejects it
rather than treating it as a verified comparison. Other requests keep their
existing journal behavior. Response validation and response journaling still
precede a result; a later failure may leave no result despite a stop request.

Twenty-four CPU local-socket tests passed on the copied client and synthetic
peer, including an existing trigger file, a test-injected partial image write,
an injected closed intent-journal descriptor, and a peer that closes instead of
acknowledging the stop. The first three cases observed command 3 at the peer;
the last produced no acknowledged-result file. The tests also exercise the
existing normal and disabled paths. These injections do not prove behavior for
every disk failure, and a blocking image write can still delay the stop. The
prototype is simulator-only: no rendered episode, physical motion, successful
recovery, braking or delivery was demonstrated.

Artifact: `experiments/visual-search-stop-on-evidence-failure-v1/`. Earlier
source transforms and experiment outputs remain unchanged.
