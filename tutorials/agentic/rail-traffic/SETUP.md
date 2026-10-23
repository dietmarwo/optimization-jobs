# Run the rail-traffic tutorial

The reader-facing tutorial uses prompts. These commands prepare a Linux shell agent and reproduce the experiments without needing a paid model API. An agent can also use a configured MCP server over the same prepared node, as explained in the shared job guide.

Use checkouts of optimization-jobs and LP-IP-craft, current stable Rust (minimum 1.88 for the job layer), and Python 3.10+ with the series requirements. The two repositories should be siblings. This chapter needs no other solver, no railway API and no real traffic data.

```sh
git clone https://github.com/dietmarwo/optimization-jobs.git
git clone https://github.com/dietmarwo/LP-IP-craft.git
cd optimization-jobs
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r tutorials/agentic/requirements.txt
python3 tutorials/agentic/run.py build --chapter rail-traffic \
  --sources .. --bin-dir ../rail-bin --build-dir ../rail-target
python3 tutorials/agentic/run.py run --chapter rail-traffic \
  --sources .. --bin-dir ../rail-bin --output ../rail-results --cores 2
```

For a prompt session, give the agent the two checkout paths, `rail-bin`, a new output directory and [prompt.md](prompt.md). A generic chat window without shell/MCP access can discuss the exercise but cannot execute these jobs. The optimizer itself does not call a language model. Two CPU slots allow the cold and warm starts to execute independently with one inner thread each; this tiny model is not a parallel-speed benchmark.

Retained outputs include `rail-summary.json`, `rail-oracles.json`, `rail-scenario.json`, three PNG figures, worker discovery, model/name-map JSON, submitted job specs, raw results, the overall report and checksums. The node retains worker journals. The output directory must be new or empty. Results and claimed evidence are not replaced by the agent's prose.

For demand follow-ups, copy `scenario.json`, edit the indicated passenger count, and supply that copy with `--rail-scenario /absolute/path/scenario-copy.json`. Keep the default fixture unchanged. Repeat in a fresh result directory. The driver always runs the five displayed policies, the relaxation and stress experiments. It does not use `--budget-scale` or an optimizer random seed for this deterministic rail model.

The input validator limits this teaching exercise to 2..8 trains, positive integer passenger counts, integer input minutes and a horizon of at most 240 minutes. It rejects unknown fields and duplicate IDs. The displayed and regression-tested fixture has six trains. All comparisons need feasible timetable alternatives within the horizon; malformed inputs or a failed numerical check stop the run and retain its evidence. Feasible outcomes must meet the documented numerical-optimum checks; a budget-limited candidate is not silently labelled an optimum.

## Tests

```sh
python3 tutorials/agentic/test_contract.py
python3 tutorials/agentic/rail-traffic/test_rail.py
```

The added CI entry runs these tests and the real rail campaign with locked dependencies. It retains the existing separate Clippy/test steps and plain Rust diagnostic output. Native solver code, dependency pins and lockfiles are unchanged by this chapter.

## Model details

Let `s_i` be a train's entry time, `p_i` its planned time, `r_i` its readiness, `d_i` its occupancy and `c` the clearance. Minimize `sum(passengers_i * (s_i - p_i))`. Bounds are `L_i = max(p_i, r_i)` and `U_i = horizon - d_i`.

For each pair `i < j`, binary `z_ij = 1` means i passes before j:

```text
s_i + d_i + c <= s_j + M_ij * (1 - z_ij)
s_j + d_j + c <= s_i + M_ji * z_ij
M_ij = max(0, U_i + d_i + c - L_j)
```

The second M uses the reversed indices. A maximum-delay cap adds `s_i <= p_i + cap`. Queue preservation adds the first precedence inequality without a binary variable for adjacent trains in each direction's planned queue. A continuous relaxation replaces every binary kind by continuous [0,1].

The independent checker reads entry times and source train data, not these rows or order bits. The exhaustive oracle enumerates total orders and constructs earliest schedules using integer arithmetic. All weights are strictly positive, so later starts cannot improve the objective for a fixed order. Caps and queue precedence cannot make a later schedule feasible when its earliest schedule fails. This justifies the oracle for this model, including continuous time variables; it is not an independent validation of real railway physics.
