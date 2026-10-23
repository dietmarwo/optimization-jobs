Use a checkout of optimization-jobs with sibling checkouts of fcmaes-rust, LP-IP-craft, SQP-craft and fast-cma-es. Read tutorials/agentic/README.md and SETUP.md, then the trebuchet chapter. Inspect the available binaries, node capacity and worker discovery; build missing workers using the documented setup.

Find a good design for a throw to 35 metres. Show the trade-off between landing error, input energy and pivot load, and show different trajectories rather than only one winner.

Run the scalar, MODE and MAP-Elites pilot. Recheck the scalar design with app.trebuchet.checked, inspect its release/landing validity, and generate the existing browser replay. Explain why a scalar penalty is not a constraint certificate.

Start with the chapter's pilot budgets, seed 42 and at most two CPU slots. Use the supplied run.py driver with --chapter trebuchet in a new output directory. Inspect the actual result records and generated figures. Report failures and empty fronts honestly; do not change tests or tolerances to obtain a pass. Return the findings, a brief explanation of the claims, and links to report.json and the relevant plots/replay. Record source revisions and binary hashes. This is a pilot, not a publication-quality campaign.
