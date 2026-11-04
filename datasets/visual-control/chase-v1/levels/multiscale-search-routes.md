# Exploratory multiscale closed routes

This offline diagnostic evaluates saved virtual-search poses at fixed windows of
100, 150, 200 and 250 action intervals. A window qualifies if its position ends
within 0.75 m of its start, traveled path is at least 2 m, and displacement is
at most 20% of traveled path. These settings were fixed before running the
motivating saved case. Heading is intentionally not part of the criterion; a
deliberate return can qualify. The output gives per-window counts, marked
interval unions and one example, separately for recorded wheel odometry and
simulator-truth poses. Truth is used offline and is not an actor input.

The prior treatment L5 seed 7800001 does **not** qualify in either pose stream
at these settings. Its first search nevertheless records 300 observations,
with 17.928 m path and 0.641 m net displacement in simulator truth, and
18.107 m path and 0.936 m displacement in wheel odometry. These are measured
between post-action states; they differ slightly from metrics including the
initial spawn pose. The complementary first-search path and displacement
metric shows the long route without assigning a verdict. A zero multiscale
count does not establish that the route was efficient or non-looping.

Straight and partial-turn synthetic routes, a closed-circle positive control,
phase breaks and invalid poses are covered by the CPU fixture. These examples
do not establish sensitivity, specificity, a safe recovery trigger, causal
failure, physical sensing, or robot task performance.
