# Teacher-plan CPU watchdog

`supervise-heading-teacher-freeze.py` is a disabled, standalone wrapper around
the existing teacher-plan `freeze()` function. It is intended to run in a
dedicated single-threaded process with no existing children. It does not run
teacher episodes or use the GPU.

The wrapper requires the monitored student completion receipt, at least 38 GiB
free, and unused plan, teacher, teacher-monitor and watchdog output paths. The
original registration code acquires its shared lock and performs the substantive
selection and source checks. The watchdog allows up to 10,800 seconds for those
checks, retains their logs and partial outputs, and uses the existing subreaper
to terminate descendants on timeout or interruption. Its result preserves the
raw child status; a timeout or external signal takes precedence in the wrapper
exit code. It verifies the plan's saved metadata and the small source and student
receipt hashes after a clean child exit. These checks are consistency evidence,
not an independent execution attestation or evidence of teacher performance.

Outputs are written under `heading-teacher-freeze-cpu-monitor-v1`. An incomplete
or interrupted invocation can leave that directory or a plan behind. Preserve
those artifacts for inspection; the watchdog refuses an automatic retry or
overwrite. A missing result is not success. Its CLI remains disabled pending
review and scheduling.
