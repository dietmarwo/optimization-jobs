#!/usr/bin/env python3
"""Render standalone figures from the collected simulator summaries."""

import argparse
import json
from pathlib import Path
import sys
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def f3_bars(arms):
    """(height or None, label) per F3 design; None means no comparison."""
    rows = []
    for a in arms:
        value = a["relative_energy_grid_change"]
        if value is None:
            rows.append((None, "no coarse/fine\ncomparison"))
        elif a["supported_at_requested_fidelity"]:
            rows.append((value, "supported"))
        else:
            rows.append((value, "not supported"))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for chapter in ["C1", "C2", "C3", "C4", "F1", "F2", "F3"]:
        path = args.results / chapter / "summary.json"
        if not path.is_file():
            print(f"{chapter}: no summary, skipped", file=sys.stderr)
            continue
        r = json.loads(path.read_text())
        if r.get("passed") is not True:
            print(f"{chapter}: checks did not pass, skipped", file=sys.stderr)
            continue
        fig, ax = plt.subplots(figsize=(8, 4.6), layout="constrained")
        arms = r["arms"]
        if chapter == "C1":
            labels = [
                f"{a['model']}\n{a.get('policy', '')} {a['route']}\nseed {a['seed']}"
                for a in arms
            ]
            ax.bar(range(len(arms)), [a["holdout_loss"] for a in arms], color="#277da8")
            ax.set_xticks(range(len(arms)), labels, rotation=40, ha="right")
            ax.set_ylabel("Held-out moment loss")
        elif chapter == "C2":
            ax.bar(
                [a["strategy"] for a in arms],
                [a["independent_loss"] for a in arms],
                color="#277da8",
            )
            ax.set_yscale("log")
            ax.set_ylabel("Independent ODE loss (log scale)")
        elif chapter == "C3":
            rows = [v for v in r["validation"] if v["origin"] == "pareto"]
            for i, v in enumerate(rows):
                a, b = v["training"]["objectives"], v["validation"]["objectives"]
                ax.plot(
                    [a[0], b[0]],
                    [a[1], b[1]],
                    "o-",
                    label=f"Extreme {i + 1}: train → holdout",
                )
            ax.set_xlabel("Oscillation quality loss (objective 1 of 3)")
            ax.set_ylabel("Molecule cost (objective 2 of 3)")
            ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0))
        elif chapter == "C4":
            x = np.arange(len(arms))
            ax.bar(
                x,
                [a["heldout_law_max_cdf_distance"] for a in arms],
                color="#277da8",
                label="Observed CDF distance",
            )
            ax.plot(
                x,
                [a["dkw_bound"] for a in arms],
                "s--",
                color="#bc4749",
                label="Frozen per-kernel family bound",
            )
            ax.set_xticks(x, [a["kernel"] for a in arms])
            ax.set_ylabel("Maximum held-out CDF distance")
            ax.legend()
        elif chapter == "F1":
            x = np.arange(len(arms))
            ax.bar(
                x - 0.18,
                [a["replay_objective"] for a in arms],
                0.36,
                label="Training wind, fresh replay",
            )
            ax.bar(
                x + 0.18,
                [a["heldout_wind_objective"] for a in arms],
                0.36,
                label="Withheld wind 1.15 m/s",
            )
            ax.set_xticks(x, [a["method"] for a in arms])
            ax.set_ylabel("Maximum receptor concentration / 1e-8 kg m⁻³")
            ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0))
        elif chapter == "F2":
            labels = [a["method"] for a in arms]
            ax.bar(
                labels,
                [a["inversion"][0]["noiseless"]["rank"] for a in arms],
                color="#277da8",
            )
            ax.axhline(
                3, color="#bc4749", linestyle="--", label="Three unknown source rates"
            )
            ax.set_ylim(0, 3.6)
            ax.set_ylabel("Rank of selected-sensor response matrix")
            ax.legend()
            for i, a in enumerate(arms):
                ax.text(
                    i,
                    0.15,
                    f"Coverage {a['coverage']:g}\n{len(a['sensors'])} sensor{'s' if len(a['sensors']) != 1 else ''}",
                    ha="center",
                    color="white",
                )
        else:
            # A design without a coarse/fine comparison has no bar height; it
            # is labeled, never drawn as zero change.
            x = np.arange(len(arms))
            for i, (value, label) in enumerate(f3_bars(arms)):
                if value is None:
                    ax.text(i, 0.01, label, ha="center")
                    continue
                ax.bar(i, value, color="#277da8" if label == "supported" else "#bc4749")
                ax.text(i, value, label, ha="center", va="bottom")
            ax.set_xticks(
                x, [f"{a['method']}\nspeed {a['training']['speed']:.3g}" for a in arms]
            )
            ax.axhline(
                0.1, color="#555555", linestyle="--", label="Frozen 10% fidelity gate"
            )
            ax.set_ylabel("Relative coarse/fine energy change")
            ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0))
        ax.set_title(f"{chapter} · {r['preset']} preset · numerical evidence")
        ax.spines[["top", "right"]].set_visible(False)
        fig.savefig(args.output / (chapter + ".svg"))
        fig.savefig(args.output / (chapter + ".png"), dpi=150)
        plt.close(fig)


if __name__ == "__main__":
    main()
