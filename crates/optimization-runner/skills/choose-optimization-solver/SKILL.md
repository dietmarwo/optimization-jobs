---
name: choose-optimization-solver
description: "Choose an optimization solver and worker profile from the objective, constraints, derivatives and required result."
---

1. Write the problem card: variables, objective, constraints, available
   derivatives, work budget and what the answer must establish.
2. Match the card to a solver. Choose LP-IP-craft for a sparse linear model,
   SQP-craft for a smooth constrained model with derivatives, MODE for a
   Pareto front, or MAP-Elites for diverse high-quality solutions. Use a
   registered scalar fcmaes model for a boxed black-box objective.
3. Call describe_node and describe_worker. Check that the selected profile and
   the model are installed and use the returned payload schema and examples.
4. Choose budgets and decide what evidence you will need before you run.

Read [the problem card](references/problem-card.md) and
[solver selection](references/solver-selection.md) for the complete criteria.
