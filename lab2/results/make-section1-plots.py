#!/usr/bin/env python3
"""Section 1 figures for the EE542 Lab 2 report.

Reads section1-all-runs.csv and emits two PNGs alongside it.
Run:  python3 make-section1-plots.py
"""
import csv
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter

HERE = os.path.dirname(os.path.abspath(__file__))

# Validated categorical palette (light mode), slots 1 and 2.
SURFACE = "#fcfcfb"
INK     = "#0b0b0b"
INK2    = "#52514e"
GRID    = "#e4e3df"
TCP     = "#2a78d6"   # slot 1, blue
UDP     = "#eb6834"   # slot 2, orange

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "font.size": 10,
    "text.color": INK, "axes.labelcolor": INK2, "axes.edgecolor": GRID,
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
})


def load():
    """Mean TCP/UDP per case, valid runs only, both directions pooled."""
    path = os.path.join(HERE, "section1-all-runs.csv")
    acc = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            if r["valid"] != "yes":
                continue
            d = acc.setdefault(r["case"], {"tcp": [], "udp": []})
            for k, col in (("tcp", "tcp_mbps"), ("udp", "udp_mbps")):
                if r[col]:
                    d[k].append(float(r[col]))
    return {c: {k: sum(v) / len(v) for k, v in d.items() if v} for c, d in acc.items()}


def fig_main(cases):
    """Dumbbell on a log axis: the gap between the two series IS the story."""
    rows = [
        ("Baseline\nno impairment",      95.6,                 94.2),
        ("Case 1\n10 ms, 1% loss",       cases["1"]["tcp"],    cases["1"]["udp"]),
        ("Case 2\n200 ms, 20% loss",     cases["2"]["tcp"],    cases["2"]["udp"]),
        ("Case 3\n200 ms, 80 Mbit cap",  cases["3"]["tcp"],    cases["3"]["udp"]),
    ]
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    ys = range(len(rows))

    for y, (_, tcp, udp) in zip(ys, rows):
        lo, hi = min(tcp, udp), max(tcp, udp)
        ax.plot([lo, hi], [y, y], color=GRID, lw=2, zorder=1,
                solid_capstyle="round")
        ax.plot(udp, y, "o", ms=11, color=UDP, zorder=3,
                markeredgecolor=SURFACE, markeredgewidth=2)
        ax.plot(tcp, y, "o", ms=11, color=TCP, zorder=3,
                markeredgecolor=SURFACE, markeredgewidth=2)
        ax.annotate(f"{tcp:,.2f}".rstrip("0").rstrip("."), (tcp, y),
                    textcoords="offset points", xytext=(0, -19),
                    ha="center", fontsize=9, color=INK2)
        ax.annotate(f"{udp:.1f}", (udp, y), textcoords="offset points",
                    xytext=(0, 12), ha="center", fontsize=9, color=INK2)

    ax.set_xscale("log")
    ax.set_xlim(0.09, 320)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.invert_yaxis()
    ax.set_yticks(list(ys))
    ax.set_yticklabels([r[0] for r in rows], fontsize=9.5)
    ticks = [0.1, 1, 10, 100]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_minor_locator(FixedLocator([]))
    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"{v:g}" if v >= 1 else f"{v}"))
    ax.set_xlabel("Throughput, Mbit/s  (log scale)", fontsize=9.5)
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)

    # Callout on the pair the Critical Thinking question is about.
    ax.annotate("", xy=(cases["2"]["tcp"], 2.42), xytext=(cases["3"]["tcp"], 2.42),
                arrowprops=dict(arrowstyle="<->", color=INK2, lw=1.1))
    ratio = cases["3"]["tcp"] / cases["2"]["tcp"]
    ax.text(3.5, 2.62, f"{ratio:.0f}x  TCP difference\nUDP differs by 0.1 Mbit/s",
            ha="center", va="top", fontsize=9, color=INK2)

    ax.set_title("UDP is unaffected by impairment; TCP collapses",
                 fontsize=13, color=INK, pad=34, loc="left", fontweight="bold")
    ax.text(0, 1.035, "MTU 1500, mean of valid runs, both directions pooled",
            transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
    ax.legend(handles=[
        plt.Line2D([], [], marker="o", ls="", ms=9, color=TCP, label="TCP"),
        plt.Line2D([], [], marker="o", ls="", ms=9, color=UDP, label="UDP"),
    ], loc="upper left", frameon=False, fontsize=9.5,
       handletextpad=0.4, borderaxespad=0.8)

    fig.tight_layout()
    out = os.path.join(HERE, "section1-tcp-vs-udp.png")
    fig.savefig(out, dpi=200)
    print("wrote", out)


def fig_burst():
    """The TBF burst fix. One series per panel, so the titles carry identity."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.0, 3.9))
    labels = ["burst 9015\n(handout)", "burst 64000\n(ours)"]

    for ax, vals, title, unit, fmt in (
        (a1, [67.2, 95.6], "Baseline TCP throughput", "Mbit/s", "{:.1f}"),
        (a2, [1592, 0],    "TCP retransmissions in 10 s", "count", "{:,.0f}"),
    ):
        bars = ax.bar([0, 1], vals, width=0.5, color=[GRID, TCP], zorder=2)
        bars[0].set_color("#b9b8b2")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_ylabel(unit, fontsize=9)
        ax.set_title(title, fontsize=11, color=INK, loc="left", pad=10)
        ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
        ax.set_axisbelow(True)
        ax.set_ylim(0, max(vals) * 1.22)
        for x, v in zip([0, 1], vals):
            ax.annotate(fmt.format(v), (x, v), textcoords="offset points",
                        xytext=(0, 6), ha="center", fontsize=10, color=INK)

    fig.suptitle("TBF burst too small: the queue collapses to ~6 packets",
                 fontsize=12.5, color=INK, x=0.012, ha="left", fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    out = os.path.join(HERE, "section1-burst-fix.png")
    fig.savefig(out, dpi=200)
    print("wrote", out)


if __name__ == "__main__":
    c = load()
    for k in sorted(c):
        print(f"  case {k}: TCP {c[k]['tcp']:.2f}  UDP {c[k]['udp']:.1f} Mbit/s")
    fig_main(c)
    fig_burst()
