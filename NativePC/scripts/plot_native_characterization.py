from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path.home() / "BTP_CXL_Study"
DATA = ROOT / "processed_data"
OUT = ROOT / "visualizations"
OUT.mkdir(exist_ok=True)

df = pd.read_csv(DATA / "run_level_metrics.csv")

ORDER = [
    "bert", "ann", "dlrm", "llama_cpp",
    "kmeans", "pointer_chase", "stream"
]

LABELS = {
    "bert": "BERT",
    "ann": "ANN",
    "dlrm": "DLRM",
    "llama_cpp": "Llama.cpp",
    "kmeans": "K-means",
    "pointer_chase": "Pointer Chase",
    "stream": "STREAM",
}

df["workload"] = pd.Categorical(
    df["workload"],
    categories=ORDER,
    ordered=True
)

summary = df.groupby("workload", observed=True).agg({
    "ipc": ["mean", "std"],
    "cache_misses_per_million_inst": ["mean", "std"],
    "l2_demand_read_misses_per_million_inst": ["mean", "std"],
    "l3_load_misses_per_million_inst": ["mean", "std"],
    "offcore_outstanding_fraction": ["mean", "std"],
    "dtlb_load_walks_per_million_inst": ["mean", "std"],
    "dtlb_store_walks_per_million_inst": ["mean", "std"],
})

summary.to_csv(OUT / "native_workload_summary.csv")


def finish(ax, title):
    ax.set_title(title, fontsize=15)
    ax.grid(True, which="both", alpha=0.2)
    ax.tick_params(labelsize=10)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(
        OUT / name,
        dpi=300,
        bbox_inches="tight"
    )
    plt.close(fig)


# ------------------------------------------------------------
# FIGURE 1
# IPC vs L3 misses
# ------------------------------------------------------------

fig, ax = plt.subplots(figsize=(9, 6))

for w in ORDER:
    g = df[df["workload"] == w]

    x = g["l3_load_misses_per_million_inst"]
    y = g["ipc"]

    ax.scatter(x, y, s=45, alpha=0.75)

    ax.errorbar(
        x.mean(),
        y.mean(),
        xerr=x.std(),
        yerr=y.std(),
        fmt="none",
        capsize=4,
        linewidth=1.5
    )

    ax.annotate(
        LABELS[w],
        (x.mean(), y.mean()),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=9
    )

ax.set_xscale("log")
ax.set_xlabel("L3 load misses / million instructions")
ax.set_ylabel("Instructions per cycle (IPC)")
finish(ax, "Native workload compute vs LLC-miss behavior")

save(fig, "fig1_ipc_vs_l3_misses.png")


# ------------------------------------------------------------
# FIGURE 2
# Cache pressure vs offcore activity
# ------------------------------------------------------------

fig, ax = plt.subplots(figsize=(9, 6))

for w in ORDER:
    g = df[df["workload"] == w]

    x = g["cache_misses_per_million_inst"]
    y = g["offcore_outstanding_fraction"]

    ax.scatter(x, y, s=45, alpha=0.75)

    ax.errorbar(
        x.mean(),
        y.mean(),
        xerr=x.std(),
        yerr=y.std(),
        fmt="none",
        capsize=4,
        linewidth=1.5
    )

    ax.annotate(
        LABELS[w],
        (x.mean(), y.mean()),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=9
    )

ax.set_xscale("log")
ax.set_xlabel("Cache misses / million instructions")
ax.set_ylabel("Offcore outstanding-data-read cycle fraction")
finish(ax, "Cache pressure vs outstanding-memory activity")

save(fig, "fig2_cache_vs_offcore.png")


# ------------------------------------------------------------
# FIGURE 3
# L2 vs L3 misses
# ------------------------------------------------------------

fig, ax = plt.subplots(figsize=(9, 6))

for w in ORDER:
    g = df[df["workload"] == w]

    x = g["l2_demand_read_misses_per_million_inst"]
    y = g["l3_load_misses_per_million_inst"]

    ax.scatter(x, y, s=45, alpha=0.75)

    ax.annotate(
        LABELS[w],
        (x.mean(), y.mean()),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=9
    )

ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlabel("L2 demand-read misses / million instructions")
ax.set_ylabel("L3 load misses / million instructions")
finish(ax, "Depth of memory-hierarchy pressure")

save(fig, "fig3_l2_vs_l3_misses.png")


# ------------------------------------------------------------
# FIGURE 4
# Memory vs translation pressure
# ------------------------------------------------------------

fig, ax = plt.subplots(figsize=(9, 6))

for w in ORDER:
    g = df[df["workload"] == w]

    x = g["l3_load_misses_per_million_inst"]
    y = g["dtlb_load_walks_per_million_inst"]

    ax.scatter(x, y, s=45, alpha=0.75)

    ax.annotate(
        LABELS[w],
        (x.mean(), y.mean()),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=9
    )

ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlabel("L3 load misses / million instructions")
ax.set_ylabel("DTLB load walks / million instructions")
finish(ax, "Memory pressure vs address-translation pressure")

save(fig, "fig4_memory_vs_translation.png")


# ------------------------------------------------------------
# FIGURE 5
# TLB load vs store
# ------------------------------------------------------------

fig, ax = plt.subplots(figsize=(9, 6))

for w in ORDER:
    g = df[df["workload"] == w]

    x = g["dtlb_load_walks_per_million_inst"]
    y = g["dtlb_store_walks_per_million_inst"]

    ax.scatter(x, y, s=45, alpha=0.75)

    ax.annotate(
        LABELS[w],
        (x.mean(), y.mean()),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=9
    )

ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlabel("DTLB load walks / million instructions")
ax.set_ylabel("DTLB store walks / million instructions")
finish(ax, "Native address-translation behavior")

save(fig, "fig5_dtlb_behavior.png")


# ------------------------------------------------------------
# FIGURE 6
# Direct workload characterization bars
# ------------------------------------------------------------

metrics = [
    ("ipc", "IPC"),
    ("cache_misses_per_million_inst", "Cache misses / MInst"),
    ("l3_load_misses_per_million_inst", "L3 misses / MInst"),
    ("offcore_outstanding_fraction", "Offcore activity"),
    ("dtlb_load_walks_per_million_inst", "DTLB load walks / MInst"),
]

for col, ylabel in metrics:

    fig, ax = plt.subplots(figsize=(10, 5))

    means = []
    stds = []

    for w in ORDER:
        g = df[df["workload"] == w][col]
        means.append(g.mean())
        stds.append(g.std())

    x = range(len(ORDER))

    ax.bar(
        x,
        means,
        yerr=stds,
        capsize=4
    )

    ax.set_xticks(list(x))
    ax.set_xticklabels(
        [LABELS[w] for w in ORDER],
        rotation=25,
        ha="right"
    )

    ax.set_ylabel(ylabel)
    finish(ax, f"Native {ylabel}")

    # Memory-pressure quantities span large ranges.
    if "MInst" in ylabel:
        ax.set_yscale("log")

    save(
        fig,
        "bar_" + col.replace("/", "_") + ".png"
    )


print("\nGenerated files:")
for p in sorted(OUT.glob("*.png")):
    print(p.name)
