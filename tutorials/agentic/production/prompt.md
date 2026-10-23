Use a checkout of optimization-jobs with sibling checkouts of fcmaes-rust, LP-IP-craft, SQP-craft and fast-cma-es. Read tutorials/agentic/README.md and SETUP.md, then the production chapter. Inspect the available binaries, node capacity and worker discovery; build missing workers using the documented setup.

Find production-line operating policies balancing throughput, lead time, work in progress and operating cost. Include staffing and buffer capacity, and tell me how reliable the shortlist is.

Use MODE on the original NeXosim model and a small MAP-Elites pilot. Freeze the training simulation seed at 42; choose three policies using training throughput, then re-evaluate those exact policies with simulation seed 314159. Keep simulator execution serial inside each candidate and let the job layer own candidate concurrency.

Start with the chapter's pilot budgets, seed 42 and at most two CPU slots. Use the supplied run.py driver with --chapter production in a new output directory. Inspect the actual result records and generated figures. Report failures and empty fronts honestly; do not change tests or tolerances to obtain a pass. Return the findings, a brief explanation of the claims, and links to report.json and the relevant plots/replay. Record source revisions and binary hashes. This is a pilot, not a publication-quality campaign.
