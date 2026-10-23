# Let the agent propose routes and let physics score them

[Series](../README.md) · [Copyable prompt](prompt.md) · [Original model](https://github.com/dietmarwo/fcmaes-rust/tree/main/tutorials/gtoc1-route-search)

## Ask the agent

> Screen different planet orders for the GTOC1 impulsive MGA model. Show a portfolio of promising routes and explain what still needs to be checked before considering a low-thrust mission.

For a complete runnable instruction, paste [prompt.md](prompt.md) into an agent with a Linux shell, a Rust toolchain and checkouts of the five repositories, or use a prepared node with these workers. The maintained model is already implemented; the user supplies goals and interprets decisions.

## What the agent executes

First execute the two-route plumbing pilot. Use the route-card helper to derive bounds and a neutral schedule for each body order. Give each route the same BiteOpt retry budget; record requested and actual evaluations and re-evaluate the retained schedule. Treat positive MGA score only as screening evidence.

## Inspect the result

A route portfolio, direct schedule variables, per-route work counts, baseline/search/recheck records, and an explicit MGA-only claim boundary.

The reference driver preserves every submitted specification, schema-validated results, worker discovery, hashes and work counters. It produces `report.json`; inspect individual result records rather than inferring success from lifecycle `completed`.

## Example executed result

At the same 256-evaluation search budget per route, the Earth–Venus–Earth–Jupiter–asteroid fixture reached an MGA screening score of 672103.51; Earth–Earth–Venus–Jupiter–asteroid reached 614331.68. Both retained schedules re-evaluated consistently. These are two fixed fixtures, not AI-discovered routes or low-thrust-feasible missions.

Source: [retained pilot summary](../validation/pilot-summary.json); see [validation](../VALIDATION.md) for scope and exact checks.

## Continue the conversation

> Propose three additional distinct grammar-valid planet orders. Submit one fixed-route job per proposal with route-card-derived bounds. Compare them with three preselected random grammar-valid routes at the same numerical budgets. Label this exploratory and record the proposal policy; it is not the published 100-route controlled comparison.

## Equivalence and limits

The worker reuses original MGA physics, direction rules and history-blind direct bounds. The generic job retry protocol is BiteOpt here; it is not the original coordinated DE-CMA-ES campaign and its scores must not be presented as a reproduction of that campaign. The first two routes are fixed test fixtures, not AI-generated discoveries.

See [validation](../VALIDATION.md) for the executed campaign and model-trial status.
