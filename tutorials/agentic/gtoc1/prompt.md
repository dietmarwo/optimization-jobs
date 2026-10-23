Use a checkout of optimization-jobs with sibling checkouts of fcmaes-rust, LP-IP-craft, SQP-craft and fast-cma-es. Read tutorials/agentic/README.md and SETUP.md, then the gtoc1 chapter. Inspect the available binaries, node capacity and worker discovery; build missing workers using the documented setup.

Screen different planet orders for the GTOC1 impulsive MGA model. Show a portfolio of promising routes and explain what still needs to be checked before considering a low-thrust mission.

First execute the two-route plumbing pilot. Use the route-card helper to derive bounds and a neutral schedule for each body order. Give each route the same BiteOpt retry budget; record requested and actual evaluations and re-evaluate the retained schedule. Treat positive MGA score only as screening evidence.

Start with the chapter's pilot budgets, seed 42 and at most two CPU slots. Use the supplied run.py driver with --chapter gtoc1 in a new output directory. Inspect the actual result records and generated figures. Report failures and empty fronts honestly; do not change tests or tolerances to obtain a pass. Return the findings, a brief explanation of the claims, and links to report.json and the relevant plots/replay. Record source revisions and binary hashes. This is a pilot, not a publication-quality campaign.
