---
name: interpret-optimization-result
description: "Read optimization results, compare feasible candidates and report their termination, claims, evidence and resource accounting."
---

1. Read get_job. Once it is terminal, call get_result. For a specific task,
   request that task's full record. Inspect artifact_index for large outputs.
2. Report the reason the task stopped, its claim and the evidence separately.
   A cancellation or deadline can still leave completed records. State how much
   work is known if accounting is incomplete.
3. For LP or MIP, report the incumbent and any bound or gap. For SQP, read the
   reported feasibility and optimality residuals. For MODE, name the source
   of the front and the reference point used for hypervolume. For MAP-Elites,
   read the archive's occupancy, coverage and QD score.
4. Treat a best-found point as a candidate. A proof of optimality requires
   an appropriate certificate. Distinguish feasibility for the declared model
   from raw constraints that were modeled only as penalties.

See [results, claims and evidence](references/results.md) and
[common pitfalls](references/pitfalls.md).
