Recover the frozen rail timetable. Explain what each ordering binary means, how the horizon determines big-M, and why the relaxed timetable understates delay. Check the integer result by enumerating and replaying train orders.

Read this chapter's README and the shared setup/solver guide first. State variables, units, constraints and the independent check before executing the maintained implementation. Use the smoke preset initially, its declared work limits, one numerical worker and a new output directory. Do not change watched sources during execution.

Return the actual native statuses, feasible decision, available bounds or multipliers, independent checks, actual work, figure and complete artifact location. Preserve missing fields and failed attempts. A completed command or a matching reference value does not create a stronger solver claim.

Follow-up exercise: Compare the LP relaxation with the timetable. Explain the growth from 720 orders at six trains to 40,320 at eight; the maintained exhaustive fixture rejects larger inputs.
