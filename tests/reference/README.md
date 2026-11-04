# Rust controller reference

`rust-core/` is the former `puppybot/core` controller, retained solely for
independent differential tests of the Flexscript implementation in `src/core/`.
It is not an application or firmware build target. Do not develop a second
production implementation here.

`src/tests/core-reference/Cargo.toml` runs its original unit tests;
`src/tests/oracle/Cargo.toml` builds the comparison oracle. Both use this same
source. Run `src/scripts/test.sh` for the complete verification suite when its
compiler, GPU-library and host dependencies are available.

The old Rust runtime, CLI, firmware, collision tools and RobotDreams integration
tests are retired. Their source remains in Git history before this migration.
The `puppybot/core` symlink only preserves old reference paths.
