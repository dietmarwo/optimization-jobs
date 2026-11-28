## 1. Write a short problem card

Establish these facts from the user's code and data before choosing. Ask only
for what you cannot infer and what would change the choice.

- **Variables:** how many; continuous, integer or binary, categorical, or
  structured (permutations, routes, graphs); finite bounds?
- **Model structure:** are the objective and constraints linear, smooth with
  available derivatives, or a black box (nonsmooth, noisy, multimodal, a
  simulation that can fail)?
- **Wanted output:** how many objectives, and does the user want one
  solution, a Pareto front or many diverse good solutions over behavior
  descriptors?
- **Cost:** how long one evaluation takes, the evaluation, wall-time and core
  budget, and whether evaluations can run in parallel.
- **Where the model lives:** Python code, Rust code, a data file (an LP/MIP),
  or an external program.
- **How it must run:** a call inside the user's program, or a durable,
  budgeted job that an agent submits, watches, cancels and reads later.
- **Evidence:** a good feasible point, a local optimum with an independent
  KKT check, or a bound and gap.
