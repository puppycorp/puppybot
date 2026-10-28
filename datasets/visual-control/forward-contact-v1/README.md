# Forward-contact sampling pilot

The first ten student/oracle trajectories completed physically and passed the
native audits, including exact replay of 600 student commands. However, they
contained zero fitting frames of forward-motion contact. They failed the
predeclared minimum of 200 such frames and were not merged into the accepted
training dataset. Recordings and failed coverage results remain under
`build/flex/sim/forward-contact-v1/`.

Further development probes found a fitting-layout starting pose that reproduces
the stall: layout 5 at `[0, 0.04, 0.14]` produces 56 forward-contact frames in
60 actions. Equivalent probes in layouts 1 and 3 produce none. This informed
the separate `forward-contact-v2` collection; validation geometry was not
borrowed for fitting.

Changing only the hidden validation room's floor red channel across five values
did not change the stall. All five native audits passed, but none found the
brick. See `floor-probe-result-v2.json` in the build directory. This was a
development diagnostic, not a canonical benchmark result.

On the original stalled checkpoint, flipping only the contact input changes the
action logits slightly but does not change the selected action in the inspected
contact frames. Contact therefore has an effect; it is insufficient to trigger
recovery in this history. The exact replay and counterfactual logits are retained
in `feedback-sensitivity/result.json`. No network architecture change was made
as part of these probes.
