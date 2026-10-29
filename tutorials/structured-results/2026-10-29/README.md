# Recorded validation — 29 October 2026

All twenty smoke and twenty study presets completed their executable checks.
Twenty command applications, a dependent sealed-artifact checker and four
native worker jobs completed in a 25-job foreground experiment-craft campaign.
The two native comparison groups vary LP presolve and SQP backend only.

- [Validation summary](validation-summary.json)
- [Smoke report](smoke/report.json) and [environment](smoke/environment.json)
- [Study report](study/report.json) and [environment](study/environment.json)
- [Campaign report](campaign/report/report.md)
- [Comparison report](campaign/comparison/comparison.md)

Per-chapter summaries and PNG/SVG figures are under each owner's
`tutorials/<chapter>/results/{smoke,study}/`. These records contain actual
statuses, including time limits and unsuccessful individual attempts; a
passed chapter does not assert that every solver attempt converged.

The runtime campaign's state was on this host's `/dev/shm` tmpfs after
inconsistent registry/state snapshots were observed on its overlay filesystem.
The same sources passed there without editing authoritative runtime records.
The cause of the overlay observations is unresolved. This is local foreground
execution evidence, with no remote commissioning or durable/logout-survival
claim. Source-built workers and the original Rust FEM helper were used;
Python numerical calls used the pinned published native distributions.

Environment `tracked_diff_sha256` fields describe the then-tracked diff at
execution time; untracked tutorial sources are identified by the command
manifests and the delivery's patch/checksum manifest. They are not final patch
hashes. Timings on this shared host are diagnostic, not hardware benchmarks.

The broad experiment-craft suite has one environment error in an unchanged
file-ownership test (UID/GID 65534); the other 191 tests pass. New tutorial
adversarial tests all pass. External fresh-context model trials and remote
GitHub Actions execution were not performed.
