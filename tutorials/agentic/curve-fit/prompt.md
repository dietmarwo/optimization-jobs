Use a checkout of optimization-jobs with sibling checkouts of fcmaes-rust, LP-IP-craft, SQP-craft and fast-cma-es. Read tutorials/agentic/README.md and SETUP.md, then the curve-fit chapter. Inspect the available binaries, node capacity and worker discovery; build missing workers using the documented setup.

Fit the supplied exponential-decay examples using the fcmaes and SQP application workers. Plot the fits and explain what each solver actually verified.

Use both checked-in CSVs and the corresponding original job specifications. Independently recompute squared residual loss. For SQP also check the anchor equality and inspect KKT evidence. Explain that the two examples have different data and constraints and therefore are not a solver speed or accuracy comparison.

Start with the chapter's pilot budgets, seed 42 and at most two CPU slots. Use the supplied run.py driver with --chapter curve-fit in a new output directory. Inspect the actual result records and generated figures. Report failures and empty fronts honestly; do not change tests or tolerances to obtain a pass. Return the findings, a brief explanation of the claims, and links to report.json and the relevant plots/replay. Record source revisions and binary hashes. This is a pilot, not a publication-quality campaign.
