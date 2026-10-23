# Continue the rail traffic experiment

## Demand sensitivity

> The passenger counts are estimates. Make two named copies of the original scenario: in one, double RB202's load from 90 to 180; in the other, halve ICE101's from 420 to 210. Change nothing else. Before running, explain which trade-off could change without predicting unsupported numbers. Run each with `--rail-scenario` into a fresh output directory. Compare FCFS, weighted, 10-minute-cap, 8-minute-cap and queue-preserving plans. Retain both runs, all individual train delays and all failures. Do not select the most favorable scenario as the headline.

## Missing constraints

> Treat the passing-capacity assumption as unverified. Explain exactly which two trains swap order in the apparently improved plan and what infrastructure would be needed. Use the existing queue-preserving experiment to show the consequence of forbidding overtaking. List the additional data needed to model platforms, junction conflicts, train-dependent running/clearance times and connections. Do not pretend that supplying a station name provides these constraints.

## A pilot proposal for an AI lead

> Propose an offline replay study alongside the existing dispatching workflow. Specify the decision owner, existing system interface, baseline, forecast timestamps, objective agreed with operations, independent feasibility checker, held-out disruption cases, runtime limits, and how to capture operator reasons for rejecting a recommendation. Separate prediction quality from optimization quality. Compare the same model with an established solver before making performance claims. Produce a one-page experiment proposal; do not connect to live traffic systems.

## German opening prompt

> Erstelle eine nachvollziehbare Entscheidungsvorlage für die Disposition anhand des synthetischen Sechs-Züge-Beispiels in `scenario.json`. Führe die Experimente aus `prompt.md` mit dem vorhandenen LP/IP-Worker aus. Vergleiche die Bedienung nach Ankunftszeit mit der Minimierung gewichteter Verspätung, Obergrenzen von 10 und 8 Minuten sowie dem Erhalt der Zugreihenfolge auf beiden Zufahrten. Zeige für jeden Zug Einfahrzeit und Verspätung, prüfe alle Modellbedingungen unabhängig und untersuche zusätzliche Eingangsverspätungen. Erkläre insbesondere, ob der Vorteil verschwindet, sobald Überholen ausgeschlossen wird. Verwende ausschließlich die Beispieldaten. Es geht um eine Offline-Lerneinheit und keine betriebliche Anweisung. Antworte auf Deutsch und liefere die Diagramme und Pruefnachweise mit.
