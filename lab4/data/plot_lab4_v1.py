#!/usr/bin/env python3
"""Figure 1 and Table 1 of the Lab 4 report, from bench/matrix.sh's CSV.

Two panels, one per corpus size, because the two differ by orders of magnitude
and a shared axis would flatten the small one into nothing.  Colour carries the
framework (two hues, validated for colour-vision deficiency); the node count is
carried by the tick label and a hatch, never by colour alone.
"""
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent
CSV = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "raw" / "matrix.csv"

BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, MUTED, RULE = "#0b0b0b", "#52514e", "#d8d7d2"
JOBS = ["wordcount", "charcount", "minmax"]
JOB_LABEL = {"wordcount": "wordcount", "charcount": "charcount",
             "minmax": "minmax\n(MR: both passes)"}
TIERS = [("small", "Small corpus (3.7 MB, 6 books)"),
         ("large", "Large corpus (1.1 GB, 10 blocks)")]
ARMS = [("mr", 1, BLUE, ""), ("mr", 2, BLUE, "///"),
        ("spark-yarn", 1, ORANGE, ""), ("spark-yarn", 2, ORANGE, "///")]

runs = defaultdict(list)
with CSV.open() as fh:
    for r in csv.DictReader(fh):
        if not r["yarn_ms"] or r["extra"] == "FAILED":
            continue
        runs[(r["tier"], r["framework"], int(r["nodes"]), r["job"])].append(
            int(r["yarn_ms"]) / 1000.0)


def stat(tier, fw, nodes, job):
    """Mean and half-range for one cell.

    MapReduce minmax is reported as the sum of both passes.  The job as run is
    a second pass over the wordcount job's output -- a small vocabulary file,
    not the corpus -- so its own elapsed time (28 s on 1.1 GB) answers a
    different question than Spark's minmax, which recomputes the word counts
    from the raw text.  Charging MapReduce for the pass it depends on is what
    makes the two columns comparable.
    """
    if fw == "mr" and job == "minmax":
        a = runs.get((tier, fw, nodes, "minmax"), [])
        b = runs.get((tier, fw, nodes, "wordcount"), [])
        if not a or not b:
            return None, None
        mean = statistics.mean(a) + statistics.mean(b)
        spread = ((max(a) - min(a)) + (max(b) - min(b))) / 2
        return mean, spread
    v = runs.get((tier, fw, nodes, job), [])
    if not v:
        return None, None
    return statistics.mean(v), (max(v) - min(v)) / 2 if len(v) > 1 else 0.0


plt.rcParams.update({"font.size": 8, "axes.edgecolor": RULE,
                     "axes.labelcolor": INK, "text.color": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED})
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.7))

for ax, (tier, title) in zip(axes, TIERS):
    width, positions, labels = 0.2, [], []
    for j, job in enumerate(JOBS):
        for k, (fw, nodes, colour, hatch) in enumerate(ARMS):
            mean, spread = stat(tier, fw, nodes, job)
            x = j + (k - 1.5) * (width + 0.02)
            if mean is None:
                ax.text(x, 0, "n/a", ha="center", va="bottom",
                        fontsize=6, color=MUTED, rotation=90)
                continue
            ax.bar(x, mean, width, color=colour, hatch=hatch,
                   edgecolor="white", linewidth=0.8, zorder=3)
            if spread:
                ax.errorbar(x, mean, yerr=spread, fmt="none", ecolor=MUTED,
                            elinewidth=0.8, capsize=2, zorder=4)
            positions.append(x)
            labels.append(f"{1 if nodes == 1 else 2}")
    ax.set_xticks(range(len(JOBS)), [JOB_LABEL[j] for j in JOBS])
    ax.set_title(title, fontsize=8, color=INK, pad=6)
    ax.set_ylabel("application elapsed (s)" if tier == "small" else "")
    ax.grid(axis="y", color=RULE, linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

handles = [Patch(facecolor=BLUE, label="MapReduce"),
           Patch(facecolor=ORANGE, label="Spark on YARN"),
           Patch(facecolor="white", edgecolor=MUTED, hatch="///",
                 label="two nodes (hatched)")]
fig.legend(handles=handles, frameon=False, fontsize=7, ncol=3,
           loc="upper center", bbox_to_anchor=(0.5, 1.06),
           columnspacing=1.6, handlelength=1.5)
fig.text(0.5, -0.02, "bars within a job: 1 node, 2 nodes, 1 node, 2 nodes",
         ha="center", fontsize=6.5, color=MUTED)
fig.tight_layout(rect=(0, 0, 1, 0.97))
out = HERE / "lab4_runtime_v1.pdf"
fig.savefig(out, bbox_inches="tight")
fig.savefig(out.with_suffix(".png"), dpi=200, bbox_inches="tight")
print("wrote", out)

# Table 1, as a LaTeX booktabs body
rows = []
for tier, _ in TIERS:
    for job in JOBS:
        cells = []
        for fw, nodes, _, _ in ARMS:
            mean, spread = stat(tier, fw, nodes, job)
            cells.append("n/a" if mean is None else f"{mean:.1f} $\\pm$ {spread:.1f}")
        rows.append(f"{tier} & {job} & " + " & ".join(cells) + r" \\")
# Emit the whole tabular, not just the rows: \input of a fragment inside an
# open tabular puts booktabs' \bottomrule in the wrong place ("Misplaced
# \noalign"), and the fix for that is not to \input a fragment at all.
table = [
    r"\begin{tabular}{llrrrr}", r"\toprule",
    r"& & \multicolumn{2}{c}{MapReduce} & \multicolumn{2}{c}{Spark on YARN} \\",
    r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}",
    r"Corpus & Job & 1 node & 2 nodes & 1 node & 2 nodes \\", r"\midrule",
    *rows, r"\bottomrule", r"\end{tabular}",
]
(HERE / "table1_v1.tex").write_text("\n".join(table) + "\n")
print("\n".join(rows))
