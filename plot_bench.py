#!/usr/bin/env python3
"""Generate exportable cost/score charts from an existing benchmark run."""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

CONTROL = "S6_leadership_only_control"
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def model_summary(rows):
    """Weight texts equally, including failed calls as zero-score attempts.

    Unknown costs remain unknown, rather than treating missing usage as free.
    """
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["text"] != CONTROL:
            groups[(row["model"], row.get("effort", "default"))][row["text"]].append(row)
    result = []
    for (model, effort), texts in sorted(groups.items()):
        calls = [r for rs in texts.values() for r in rs]
        costs = [r["cost_usd"] for r in calls]
        known = all(isinstance(c, (int, float)) and math.isfinite(c) and c >= 0 for c in costs)
        averages = {key: sum(sum(r[key] for r in rs) / len(rs) for rs in texts.values()) / len(texts)
                    for key in ("soft_score", "speaker_conf", "context_conf")}
        result.append(dict(model=model, effort=effort, texts=len(texts), calls=len(calls), **averages,
                           mean_cost_usd=sum(sum(r["cost_usd"] for r in rs) / len(rs)
                                             for rs in texts.values()) / len(texts) if known else None,
                           total_cost_usd=sum(costs) if known else None,
                           errors=sum(bool(r["error"]) or not r["parsed"] for r in calls)))
    return result


def plot_results(run_dir, rows):
    directory = Path(run_dir)
    points = model_summary(rows)
    if not points:
        print("No non-control texts to plot.")
        return
    with (directory / "model_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(points[0]))
        writer.writeheader()
        writer.writerows(points)
    points = [p for p in points if p["mean_cost_usd"] is not None]
    if not points:
        print("No complete recorded costs; wrote model_summary.csv without a scatter plot.")
        return

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    background, ink, muted = "#f5f3ed", "#152d35", "#61747b"
    colors = {"anthropic": "#cb6d43", "google": "#397bca", "openai": "#169987"}
    fig, ax = plt.subplots(figsize=(11, 7.4))
    fig.patch.set_facecolor(background)
    ax.set_facecolor(background)
    fig.subplots_adjust(left=.10, right=.96, top=.78, bottom=.23)
    fig.text(.10, .93, "FEIGBENCH", fontsize=11, weight="bold", color=muted)
    fig.text(.10, .865, "Recognition, at what cost?", fontsize=27, weight="bold", color=ink)
    fig.text(.10, .815, "Disguised interviews · soft identification score · higher and further left is better",
             fontsize=11, color=muted)
    positive = all(p["mean_cost_usd"] > 0 for p in points)
    if positive:
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
        ax.xaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:.4f}"))
    ax.set_ylim(0, 100)
    low, high = min(p["mean_cost_usd"] for p in points), max(p["mean_cost_usd"] for p in points)
    ax.set_xlim(low / 1.6 if positive else -.05 * (high or 1), high * 1.6 if high else .001)
    ax.grid(axis="y", color="#d9dfdc", linewidth=.8)
    ax.grid(axis="x", color="#e4e7e1", linewidth=.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c0cbc8")
    ax.tick_params(colors=muted, labelsize=10, length=0, pad=8)
    ax.set_xlabel("Average cost per request (USD" + (", logarithmic scale)" if positive else ")"),
                  color=ink, fontsize=11, labelpad=14)
    ax.set_ylabel("Soft score / 100", color=ink, fontsize=11, labelpad=12)
    series = defaultdict(list)
    cohorts = defaultdict(set)
    for row in rows:
        if row["text"] != CONTROL:
            cohorts[(row["model"], row.get("effort", "default"))].add((row["text"], row["run"]))
    for p in points:
        if p["effort"] in EFFORT_ORDER:
            series[p["model"]].append(p)
    multiple = any(len(ps) > 1 for ps in series.values())
    if multiple:
        fig.subplots_adjust(top=.71)
        for model, ps in sorted(series.items()):
            ps.sort(key=lambda p: EFFORT_ORDER.index(p["effort"]))
            # Do not connect settings evaluated on different texts or run counts.
            comparable = all(cohorts[(model, p["effort"])] == cohorts[(model, ps[0]["effort"])] for p in ps)
            if len(ps) > 1 and comparable:
                ax.plot([p["mean_cost_usd"] for p in ps], [p["soft_score"] for p in ps],
                        color=colors.get(model.split("/")[0], "#806bb2"), alpha=.65,
                        linewidth=1.8, label=model.split("/")[-1])
            elif not comparable:
                print(f"Not connecting {model}: effort settings have different evaluation cohorts.")
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, loc="lower left", bbox_to_anchor=(0, 1.03),
                      frameon=False, ncol=3, fontsize=9, labelcolor=ink)
    for p in points:
        color = colors.get(p["model"].split("/")[0], "#806bb2")
        x, y = p["mean_cost_usd"], p["soft_score"]
        ax.scatter(x, y, s=650, color=color, alpha=.10, linewidth=0)
        ax.scatter(x, y, s=135, color=color, edgecolor="white", linewidth=2, zorder=3)
        label = p["model"].split("/")[-1].replace("-", " ")
        connected = multiple and len(series.get(p["model"], [])) > 1 and p["effort"] != "default"
        if connected:
            label = p["effort"]
            offset = {"low": (0, -24), "medium": (0, 18), "high": (0, 18)}.get(p["effort"], (0, 18))
        else:
            label += f" ({p['effort']})" if p["effort"] != "default" else ""
            label += f"\n{y:.1f} pts · ${x:.5f}"
            offset = (0, 19)
        ax.annotate(label, (x, y), xytext=offset,
                    textcoords="offset points", ha="center", fontsize=10, color=ink,
                    linespacing=1.5)
    text_counts = sorted({p['texts'] for p in points})
    call_counts = sorted({p['calls'] for p in points})
    counts = (f"{len({p['model'] for p in points})} models · {len(points)} settings · "
              f"{'/'.join(map(str, text_counts))} texts per setting · {'/'.join(map(str, call_counts))} calls per setting")
    fig.text(.10, .115, "SCORE = ½ speaker confidence + ½ matching-context confidence", fontsize=10,
             color=ink, weight="bold")
    fig.text(.10, .078, "Contexts summed, capped at 100%. Equal weight per text. S6 control excluded.",
             fontsize=9, color=muted)
    fig.text(.10, .047, counts, fontsize=8, color=muted)
    fig.text(.10, .018, f"Run {directory.name} · self-reported confidence · recorded API cost", fontsize=8, color=muted)
    for extension in ("png", "svg"):
        fig.savefig(directory / f"cost_score.{extension}", dpi=180, facecolor=background)
    plt.close(fig)
    print(f"Charts: {directory}/cost_score.png and cost_score.svg")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    args = parser.parse_args()
    from run_bench import load_targets, score
    targets = load_targets()
    records = [json.loads(line) for line in (Path(args.run_dir) / "raw.jsonl").read_text().splitlines() if line.strip()]
    plot_results(args.run_dir, [score(r, targets) for r in records])


if __name__ == "__main__":
    main()
