## 7. Resources on a large machine

CPU slots are accounting, not a speedup promise and not enforcement: the
runner admits jobs while `outer_workers * inner_threads <= cpu_slots <=
capacity`, but it does not pin threads, enforce a quota or reserve memory.
Plan the layout yourself:

1. **Measure the host.** `node doctor` (MCP `describe_node`) reports `host`:
   `usable_cpus` (affinity mask and cgroup quota), `physical_cores`,
   `numa_nodes`, `usable_memory_bytes`, and a warning when the node's
   capacity exceeds the usable CPUs. Size the capacity from `usable_cpus`, not
   from the machine's CPU count.
2. **Estimate memory per task.** Model data, the population or archive, and a
   simulator's working set, times the outer workers of all concurrent jobs
   (and of any direct library callers on the same host). Lower the outer
   width until it fits `usable_memory_bytes` with headroom. The runner has no
   memory admission.
3. **Give each level of parallelism one owner.** Outer tasks, inner threads,
   and pools inside the model (BLAS/OpenMP, Rayon, a simulator's threads,
   Python processes) multiply. Set the model's own pools (for example
   `OMP_NUM_THREADS=1`) when the job's threads already use the slots.
4. **Create useful parallel work, not duplicates.** Identical tasks (LP null
   starts, one SQP start repeated) repeat the same deterministic solve.

What each surface can use:

| Surface | Width | Consequence |
| --- | --- | --- |
| Common job envelope | `outer_workers * inner_threads <= cpu_slots <= 1024` | The node can hold many jobs; a job's outer workers help only when it has that many tasks |
| LP job (`lp-ip.solve/1`) | One model per job; `inner_threads` 1–8 (numerical kernels); component, packing and tree workers forced to 1 | Many models: many jobs (for example 64 one-slot jobs or 8 eight-slot jobs). One LP is not a 64-thread solve |
| LP library | `solve_batch` with 1–16 workers; `component_threads` defaults to 16 when `threads=1` | Set `component_threads=1` when the caller owns concurrency |
| SQP job (`sqp.solve/1`) | One task per start; `inner_threads` 1–8 | Many distinct starts with `inner_threads=1` is the first many-core layout; Clarabel is serial, active-set kernels parallelize only above size thresholds |
| SQP library | `batch::solve_many`: outer × inner at most 8 | Beyond 8, use jobs or separate processes |
| fcmaes population profiles | `inner_threads` parallelize the population (results do not depend on the width) | Useful when the objective is expensive and the population large enough |
| fcmaes serial BiteOpt/DE | `inner_threads=1` unless `batch` is set | Use outer retries; `batch` changes the feedback timing |
| `fcmaes.surrogate/1` | `concurrent * evaluation_threads <= inner_threads <= 8` per run | More slots mean more independent runs, not one larger surrogate |
| fast-cma-es | Retry processes, population evaluators, the simulator's pools | Count usable CPUs (`usable_cpus()` in its `examples/external_simulator.py`) and choose one owner |

Candidate layouts for 64 usable slots, to compare, not benchmarked
recommendations:

| Workload | Layout |
| --- | --- |
| Many independent scalar searches on a registered model | One job, `cpu_slots=64, outer_workers=64, inner_threads=1`, at least 64 retries |
| Expensive population objective | One run with `inner_threads=64`, or eight runs with eight each |
| Many LP/MIP models | 64 one-slot jobs, or eight eight-slot jobs |
| One NLP, many starts | One job with 64 distinct starts, `outer_workers=64, inner_threads=1` |
| Expensive surrogate searches | Eight runs × eight inner threads, each with its own history and budget |

For a performance comparison, fix the model, data, budgets, seeds and
acceptance rule. Report wall time, completed work, solution quality, peak
memory and how many tasks completed. CPU utilization alone is no result.
