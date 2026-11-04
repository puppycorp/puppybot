# Parent-route retention: matched data feasibility (4 Nov 2026)

The two L5 failures in [entry 127](127-l5-camera-frame-comparison.md)
suggest a diagnostic comparison of teacher and parent action labels on the
same parent-driven histories. This is a proposal, not a trained model or a
claim that those two histories generalize. They share the same layout and
start, were already inspected as selection cases, and would become fitting
data if used. They must not then serve as independent evaluation.

In the current collector, `collect --policy ... --explore-teacher` records
the teacher's action label while executing the policy's separate action.
The actual action appears in the corresponding post-step decision journal;
the dataset image and feedback row precede that action. A retained older
student-driven shard confirmed the teacher label differed from the executed
action on 132 of 300 rows. Its next-row action feedback and carry-cue
transitions were checked against the prior journal/state. This is evidence
about that shard, not proof for an uncollected new shard. `--self-imitate`
instead labels from executed actions and masks cycles by delivery; it does
not retain the original teacher labels needed for a paired comparison.

A feasible controlled pilot would collect the parent on the two selected
scenes plus separate adjacent validation episodes, audit exact pre-action
image, feedback, carry cue, tick, executed action and map alignment, and
build two otherwise identical aggregates. For the added completed-delivery
prefixes, one aggregate would retain teacher action labels and the other
would substitute the audited parent actions. All other bytes, validation
histories, masks, optimizer settings, initialization, training order,
augmentation and fixed checkpoint rule must match. This tests label
substitution within that design, not the isolated effect of the five prior
teacher prefixes. Nonzero label differences must be verified, not assumed.

The existing aggregate has 1,029 episodes; two more require capacity for
1,031 and updated auxiliary-loss mask boundaries. The current private
trainer's 1,030 cap and fixed mask slots cannot be used unchanged. A new
private build and complete split, byte, order and loss-mask audits are
needed before training. The two aggregates are about 6.1 GiB logical each;
Btrfs sharing and resulting exclusive size are not guaranteed, so the
current low-disk limits remain necessary.

Independent evaluation scenes are not yet established. Prior development
used IDs 180–187 and 218–225, and other ancestry must be inventoried before
declaring any family disjoint. The prospective held-out IDs 226–289 remain
reserved: their ingestion guard is not wired into the active training and
selection paths, so do not generate or use that catalog in this workflow.
Exact-file disjointness alone cannot rule out similar geometry or missing
ancestry. No collection, aggregate, GPU training or new selection has been
launched for this proposal.

The current diverse generator permits development IDs 180–187 and
wide-development IDs 218–225, both previously used. A possible new selection
role would require a separately reviewed generator extension; IDs 290–353 and
seeds `1800000000 + 100*level + i` are only a proposal. A read-only scan of
4,892 result/report records under 23 named roots found no overlap with those
160 proposed seeds, but skipped symlink directories and held-out-labelled
paths and cannot establish complete model ancestry or geometric disjointness.
It does not authorize generation or make the proposed selection independent.
Among that scan's regular layout records, only 40 were discoverable and none
used IDs 290–353; the skipped links make this weak absence evidence. Raw
environment hashes are also insufficient for geometry comparison because the
binary header embeds the layout ID. A future audit needs explicitly resolved
catalog targets and canonical room, doorway and obstacle geometry as well as
model-ancestry and seed checks. The current fresh-selection runner requires
`fit == true`, so it cannot safely consume a new selection role unchanged.
