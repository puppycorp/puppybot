# Experimental policy-stream witness

The standalone `policy-stream-witness.py` proxies one 84×84/128-memory policy
stream. It hashes each complete request and response and writes those hashes,
not the full tensors, to an exclusive new journal. The companion auditor joins
its records to one actor-attestation journal, checks the declared model files,
and rejects incomplete frames, ordering, footers, or an unsuccessful supplied
supervisor status. It does not replace the existing actor-image audit.

This is a CPU-stub-tested diagnostic component, **not integrated** into the
active policy launcher. The current proxy accepts at most 512 frames and the
join accepts one game, so a 32-game persistent policy run requires additional
framing and tests. The proxy timeout is per I/O operation. An outer tested
subreaper and process-group supervisor with an absolute wall deadline is
required before unattended use: the proxy handles its direct child, not all
possible escaped descendants. No physical or simulator success is implied.

The auditor accepts a caller-supplied status and registration, checks their
shape and hashes, and labels both honestly: the status is **not bound to this
run**, and registration timing is **not independently established**. A
same-user owner could fabricate either journal or metadata. Matching hashes do
not prove the kernel executed the recorded binary, the policy consumed the
forwarded data, the model generated its response, or which GPU libraries were
loaded. Source hashes alone do not prove code was running. Camera/contact
origin remains unverified as well.

The held-out runner and selection qualifier remain hard-disabled. They must
not accept this diagnostic status as qualification. Future work would need a
reviewed real launcher binding process identities and actual invocation to a
pre-run registration, tested descendant supervision, genuine policy-stream
exercise, multi-game framing and actor/camera evidence. Earlier selection
results cannot be retroactively attested.
