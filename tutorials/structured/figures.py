"""Decision-oriented figures from retained tutorial summaries."""

from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render(chapter, d, path):
    fig, ax = plt.subplots(figsize=(7, 4.4))
    if chapter == "LP1":
        c = d["cases"][0]
        ax.bar(
            np.arange(3) - 0.18, c["lp"]["candidate"], width=0.36, label="LP fractions"
        )
        ax.bar(np.arange(3) + 0.18, c["mip"]["candidate"], width=0.36, label="Binary")
        ax.set(xticks=range(3), xticklabels=["A", "B", "C"], ylabel="Selected fraction")
        ax.legend()
    elif chapter == "LP2":
        data = d["daily"][-1]["dispatch"]
        ax.step(range(len(data["grid"])), data["grid"], where="mid", label="Grid kW")
        ax.step(
            range(len(data["energy"])), data["energy"], where="mid", label="Stored kWh"
        )
        ax.plot(d["load"], label="Demand kW")
        ax.set(xlabel="Interval")
        ax.legend()
    elif chapter == "LP3":
        a = np.array(d["cases"][0]["solution"])
        ax.imshow(np.zeros_like(a), cmap="Greys", vmin=0, vmax=1)
        for i in range(9):
            for j in range(9):
                ax.text(
                    j,
                    i,
                    str(a[i, j]),
                    ha="center",
                    va="center",
                    color="black" if d["cases"][0]["puzzle"][i][j] else "tab:blue",
                )
        for boundary in np.arange(-0.5, 9, 1):
            width = 1.7 if (boundary + 0.5) % 3 == 0 else 0.4
            ax.axhline(boundary, color="grey", lw=width)
            ax.axvline(boundary, color="grey", lw=width)
        ax.set(xticks=[], yticks=[], xlim=(-0.5, 8.5), ylim=(8.5, -0.5))
    elif chapter == "LP4":
        A = np.array(d["coverage_matrix"])
        x = np.array(d["mip"]["candidate"])
        ax.bar(range(7), A @ x, label="Coverage")
        ax.plot(d["demand"], "o-", label="Demand")
        ax.set(
            xticks=range(7),
            xticklabels=["M", "T", "W", "Th", "F", "Sa", "Su"],
            ylabel="People",
        )
        ax.legend()
    elif chapter == "LP5":
        flow = np.array(d["base"]["candidate"]).reshape(3, 4)
        im = ax.imshow(flow, cmap="Blues")
        fig.colorbar(im, ax=ax, label="Flow")
        ax.set(xlabel="Market", ylabel="Plant")
        for i in range(3):
            for j in range(4):
                ax.text(j, i, f"{flow[i, j]:.0f}", ha="center", va="center")
    elif chapter == "LP6":
        ax.bar(
            ["Weak LP", "Strong LP", "Integer"],
            [
                d["cases"][0]["lp"]["evaluation"]["objective"],
                d["cases"][1]["lp"]["evaluation"]["objective"],
                d["reference"][0],
            ],
        )
        ax.set(ylabel="Minimum cost")
    elif chapter == "LP7":
        h = d["history"]
        ax.plot(
            [len(x["columns"]) for x in h],
            [x["result"]["evaluation"]["objective"] for x in h],
            "o-",
        )
        ax.axhline(
            d["integer"]["evaluation"]["objective"],
            color="grey",
            ls="--",
            label="Integer optimum",
        )
        ax.set(xlabel="Patterns in restricted master", ylabel="Rolls")
        ax.legend()
    elif chapter == "LP8":
        ax.bar(
            ["Stochastic plan", "Mean plan", "Perfect information"],
            [
                d["result"]["evaluation"]["objective"],
                d["mean_plan_profit"],
                d["wait_and_see"],
            ],
        )
        ax.set(ylabel="Expected profit")
    elif chapter == "LP9":
        x = [r["time_limit"] for r in d["records"]]
        ax.plot(
            x,
            [
                r["candidate"]["objective"] if r.get("candidate") else np.nan
                for r in d["records"]
            ],
            "o-",
            label="Incumbent",
        )
        if any(r.get("best_bound") is not None for r in d["records"]):
            ax.plot(
                x,
                [r.get("best_bound") for r in d["records"]],
                "o-",
                label="Native upper bound",
            )
        ax.axhline(
            d["independent_upper_bound"]["objective_upper"],
            ls="--",
            label="Independent packing bound",
        )
        ax.set(xlabel="Declared solve seconds", ylabel="Published weight")
        ax.legend()
    elif chapter == "LP10":
        values = [r["evaluation"]["objective"] for r in d["records"]]
        ax.bar(["Relaxation", "Integer timetable"], values)
        ax.set(ylabel="Passenger minutes of delay")
    elif chapter == "SQP1":
        t = np.linspace(0, 5, 100)
        r = min(
            (r for r in d["records"] if (r["independent"] or {}).get("feasible")),
            key=lambda r: r["independent"]["objective"],
        )
        a, b, c = r["native"]["candidate"]
        ax.plot(t, a * np.exp(-b * t) + c, label="Fit")
        a = np.array(d["training"])
        h = np.array(d["holdout"])
        ax.scatter(a[:, 0], a[:, 1], label="Training")
        ax.scatter(h[:, 0], h[:, 1], marker="x", label="Holdout")
        ax.set(xlabel="Time units", ylabel="Response")
        ax.legend()
    elif chapter == "SQP2":
        x = np.linspace(-1.5, 1.5, 300)
        ax.plot(x, (x * x - 1) ** 2 + 0.2 * x, label="Reduced objective")
        r = d["records"]
        end = np.array([v["physical"][0] for v in r])
        ax.scatter(
            end, (end * end - 1) ** 2 + 0.2 * end, s=18, label="All final points"
        )
        ax.set(xlabel="Physical coordinate", ylabel="Objective")
        ax.legend()
    elif chapter == "SQP3":
        for r in d["records"]:
            ax.plot(r["x"], r["y"], "o-", ms=3, label=f"{r['links']} links")
        ax.set(xlabel="Horizontal position", ylabel="Height")
        ax.legend()
    elif chapter == "SQP4":
        r = d["brachistochrone"]
        ax.plot(
            [v["intervals"] for v in r],
            [v["independent"]["objective"] - v["cycloid_time"] for v in r],
            "o-",
        )
        ax.set(xlabel="Collocation intervals", ylabel="Time error versus cycloid (s)")
    elif chapter == "SQP5":
        ax.plot(np.linalg.norm(d["throttles"], axis=1), "o-")
        ax.axhline(0.02, color="grey", ls="--", label="Declared throttle floor")
        ax.set(xlabel="Segment", ylabel="Throttle norm")
        ax.legend()
    elif chapter == "SQP6":
        ax.plot(d["times"], d["observations"], "o", label="Synthetic B observations")

        for i, r in enumerate(d["records"]):
            A, k1, k2 = r["native"]["candidate"]
            t = np.array(d["times"])
            y = A * k1 / (k2 - k1) * (np.exp(-k1 * t) - np.exp(-k2 * t))
            ax.plot(t, y, label=f"Fit {i + 1}")
        ax.set(xlabel="Time", ylabel="B concentration")
        ax.legend()
    elif chapter == "X1":
        ax.bar(
            ["Linear P/Q", "Batch P/Q", "Concave P/Q"],
            [
                d["LP"]["evaluation"]["objective"],
                d["MIP"]["evaluation"]["objective"],
                -d["SQP"]["independent"]["objective"],
            ],
        )
        ax.set(ylabel="Profit (different models)")
    elif chapter == "X2":
        ax.plot(d["dc_ac_replay"]["voltage"], "o-", label="DC dispatch, AC replay")
        ax.plot(d["ac"]["native"]["candidate"][:5], "o-", label="AC-OPF")
        ax.axhline(0.9, color="grey", ls="--")
        ax.set(xlabel="Bus", ylabel="Voltage magnitude (pu)")
        ax.legend()
    elif chapter == "X3":
        values = [v["result"]["evaluation"]["objective"] for v in d["bounds"]] + [
            d["continuous_mass_kg"],
            d["catalogue_rounding"]["mass_kg"],
            d["published_mass_kg"],
        ]
        ax.bar(
            ["Nominal\nbound", "Moved\nbound", "Continuous", "Rounded", "Published"],
            values,
        )
        ax.set(ylabel="Mass kg (scope differs by stage)")
    elif chapter == "X4":
        # Only independently checked sphere points; the gap to the reference
        # shows differences that bars of the full energy would hide.
        gaps = [r["check"]["objective"] - d["reference"] for r in d["arms"]]
        ax.bar([r["arm"] for r in d["arms"]], gaps)
        ax.set(ylabel=f"Energy above reference {d['reference']:.6f}")
    ax.set_title(chapter + " — retained numerical result")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    # No creation date, so that a rerun gives the same SVG bytes.
    fig.savefig(Path(path).with_suffix(".svg"), metadata={"Date": None})
    plt.close(fig)
