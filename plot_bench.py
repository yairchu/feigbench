#!/usr/bin/env python3
"""Generate exportable cost/score charts from an existing benchmark run."""
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from run_bench import SCORING_VERSION, is_control

EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
VENDOR_COLORS = {"anthropic": "#cb6d43", "google": "#397bca", "openai": "#169987",
                 "meta": "#806bb2", "meta-llama": "#806bb2", "x-ai": "#b44876",
                 "deepseek": "#537b38", "mistralai": "#b18a24", "qwen": "#526099"}
VENDOR_NAMES = {"anthropic": "Anthropic", "google": "Google", "openai": "OpenAI",
                "meta": "Meta", "meta-llama": "Meta", "x-ai": "xAI", "qwen": "Qwen"}
MODEL_NAMES = {
    "claude-haiku-5.5": "Claude Haiku 5.5",
    "claude-sonnet-5.5": "Claude Sonnet 5.5",
    "claude-opus-5.5": "Claude Opus 5.5",
    "claude-fable-5.1": "Claude Fable 5.1",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
    "gemini-3.8-flash": "Gemini 3.8 Flash",
    "gemini-4-argon": "Gemini 4 Argon",
    "muse-spark-1.3": "Muse Spark 1.3",
    "muse-wonder": "Muse Wonder",
    "gpt-6-luna": "GPT-6 Luna",
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6-astra": "GPT-6 Astra",
    "qwen3.8-max-0902": "Qwen3.8 Max",
    "grok-4.6": "Grok 4.6",
}


def model_styles(models):
    """Share one color and circle marker across each vendor's models."""
    grouped = defaultdict(list)
    for model in sorted(set(models)):
        grouped[model.split("/")[0]].append(model)
    styles = {}
    for vendor, names in grouped.items():
        fallback = ("#537b38", "#b18a24", "#526099", "#93654b")
        color = VENDOR_COLORS.get(vendor, fallback[int(hashlib.sha256(vendor.encode()).hexdigest()[:8], 16) % len(fallback)])
        for model in names:
            styles[model] = dict(color=color, marker="o")
    return styles


def place_labels(fig, ax, annotations, points):
    """Choose nearby label positions that avoid other labels and data markers."""
    from matplotlib.text import Text
    from matplotlib.transforms import Bbox
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    occupied = []
    markers = [Bbox.from_bounds(x - 9, y - 9, 18, 18) for x, y in ax.transData.transform(points)]

    def area(box):
        return max(0, box.width) * max(0, box.height) if box is not None else 0

    for annotation in annotations:
        preferred = annotation.get_position()
        candidates = [preferred, (0, 20), (0, -26), (35, 12), (-35, 12), (40, -20),
                      (-40, -20), (0, 38), (0, -42), (65, 8), (-65, 8), (40, 32), (-40, 32)]
        choices = []
        for dx, dy in candidates:
            annotation.set_position((dx, dy))
            annotation.update_positions(renderer)
            box = Text.get_window_extent(annotation, renderer).padded(4)
            overlap = sum(area(Bbox.intersection(box, other)) for other in occupied)
            marker_overlap = sum(area(Bbox.intersection(box, marker)) for marker in markers)
            outside = area(box) - area(Bbox.intersection(box, ax.bbox))
            penalty = 100 * overlap + 10 * marker_overlap + 100 * outside + dx * dx + dy * dy
            choices.append((penalty, (dx, dy), box))
        _, position, box = min(choices, key=lambda choice: choice[0])
        annotation.set_position(position)
        occupied.append(box)


def model_summary(rows):
    """Weight texts equally, including failed calls as zero-score attempts.

    Unknown costs remain unknown, rather than treating missing usage as free.
    """
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if not is_control(row["text"]):
            groups[(row["model"], row.get("effort", "default"))][row["text"]].append(row)
    result = []
    for (model, effort), texts in sorted(groups.items()):
        calls = [r for rs in texts.values() for r in rs]
        costs = [r["cost_usd"] for r in calls]
        known = all(isinstance(c, (int, float)) and math.isfinite(c) and c >= 0 for c in costs)
        averages = {key: sum(sum(r[key] for r in rs) / len(rs) for rs in texts.values()) / len(texts)
                    for key in ("soft_score", "speaker_conf", "context_conf")}
        result.append(dict(model=model, effort=effort, scoring_version=SCORING_VERSION,
                           texts=len(texts), calls=len(calls), **averages,
                           mean_cost_usd=sum(sum(r["cost_usd"] for r in rs) / len(rs)
                                             for rs in texts.values()) / len(texts) if known else None,
                           total_cost_usd=sum(costs) if known else None,
                           errors=sum(bool(r["error"]) or not r["parsed"] for r in calls)))
    return result


def parse_dimensions(value):
    """Accept a positive width and height, as pixels or a ratio."""
    try:
        width, height = map(int, value.lower().replace(":", "x").split("x"))
        if width <= 0 or height <= 0:
            raise ValueError
        return width, height
    except ValueError:
        raise argparse.ArgumentTypeError("Use positive WIDTHxHEIGHT or WIDTH:HEIGHT values.") from None


def plot_results(run_dir, rows, *, aspect_ratio=None, size=None):
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
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    background, ink, muted = "#f5f3ed", "#152d35", "#61747b"
    styles = model_styles(p["model"] for p in points)
    width, height = size or aspect_ratio or (14, 8)
    portrait = width / height < 1.2
    figure_width = 10 if portrait else 14
    dpi = width / figure_width if size else 180
    fig, ax = plt.subplots(figsize=(figure_width, figure_width * height / width), dpi=dpi)
    fig.patch.set_facecolor(background)
    ax.set_facecolor(background)
    fig.subplots_adjust(**(dict(left=.11, right=.95, top=.68, bottom=.25) if portrait
                           else dict(left=.08, right=.78, top=.78, bottom=.23)))
    fig.text(.10, .93, "FEIGBENCH 1.0", fontsize=11, weight="bold", color=muted)
    fig.text(.10, .865, "Performance / Effort", fontsize=27, weight="bold", color=ink)
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
    legend_handles, legend_labels = [], []
    for vendor in sorted({m.split("/")[0] for m in styles}):
        example = next(m for m in styles if m.split("/")[0] == vendor)
        legend_handles.append(Line2D([], [], linestyle="none", markersize=7, **styles[example]))
        legend_labels.append(VENDOR_NAMES.get(vendor, vendor))
    legend_handles += [Line2D([], [], color=muted, linewidth=1.5),
                       Line2D([], [], color=muted, linewidth=1.2, linestyle="--")]
    legend_labels += ["Effort within a model", "Models at medium effort"]
    effort_levels = sorted({p["effort"] for p in points}, key=lambda e: EFFORT_ORDER.index(e) if e in EFFORT_ORDER else -1)
    effort_sizes = {effort: 45 + index * 35 for index, effort in enumerate(effort_levels)}
    hollow_efforts = {"high"}
    if len(effort_levels) > 1:
        hollow_efforts.add(effort_levels[0])
    for effort in effort_levels:
        legend_handles.append(Line2D([], [], linestyle="none", marker="o", color=muted,
                                     markersize=math.sqrt(effort_sizes[effort]),
                                     markerfacecolor=background if effort in hollow_efforts else muted))
        legend_labels.append(effort.capitalize())
    legend = fig.legend(legend_handles, legend_labels, loc="upper left",
                        bbox_to_anchor=(.10, .82) if portrait else (.795, .79),
                        ncol=3 if portrait else 1,
                        frameon=False, fontsize=10, labelspacing=.8, handlelength=2.2,
                        title="Vendor / connections", title_fontsize=10)
    for text in legend.get_texts():
        text.set_color(ink)
    series = defaultdict(list)
    cohorts = defaultdict(set)
    for row in rows:
        if not is_control(row["text"]):
            cohorts[(row["model"], row.get("effort", "default"))].add((row["text"], row["run"]))
    for p in points:
        if p["effort"] in EFFORT_ORDER:
            series[p["model"]].append(p)
    vendor_efforts = defaultdict(list)
    for p in points:
        if p["effort"] == "medium":
            vendor_efforts[(p["model"].split("/")[0], p["effort"])].append(p)
    for (_, effort), ps in vendor_efforts.items():
        ps.sort(key=lambda p: p["mean_cost_usd"])
        for left, right in zip(ps, ps[1:]):
            if cohorts[(left["model"], effort)] == cohorts[(right["model"], effort)]:
                ax.plot([left["mean_cost_usd"], right["mean_cost_usd"]],
                        [left["soft_score"], right["soft_score"]],
                        color=styles[left["model"]]["color"], linestyle=(0, (4, 4)),
                        linewidth=1.1, alpha=.4, zorder=1)
    multiple = any(len(ps) > 1 for ps in series.values())
    if multiple:
        for model, ps in sorted(series.items()):
            ps.sort(key=lambda p: EFFORT_ORDER.index(p["effort"]))
            # Do not connect settings evaluated on different texts or run counts.
            comparable = all(cohorts[(model, p["effort"])] == cohorts[(model, ps[0]["effort"])] for p in ps)
            if len(ps) > 1 and comparable:
                ax.plot([p["mean_cost_usd"] for p in ps], [p["soft_score"] for p in ps],
                        color=styles[model]["color"], alpha=.65,
                        linewidth=1.8, label=model.split("/")[-1])
            elif not comparable:
                print(f"Not connecting {model}: effort settings have different evaluation cohorts.")
    annotations = []
    label_points = {model: max((p for p in points if p["model"] == model),
                              key=lambda p: EFFORT_ORDER.index(p["effort"]) if p["effort"] in EFFORT_ORDER else -1)
                    for model in styles}
    for p in points:
        color, marker = styles[p["model"]]["color"], styles[p["model"]]["marker"]
        x, y = p["mean_cost_usd"], p["soft_score"]
        hollow = p["effort"] in hollow_efforts
        ax.scatter(x, y, s=effort_sizes[p["effort"]], facecolor=background if hollow else color,
                   marker=marker, edgecolor=color, linewidth=1.5, zorder=3)
        if p is not label_points[p["model"]]:
            continue
        model_name = p["model"].split("/")[-1]
        label = MODEL_NAMES.get(model_name, model_name.removeprefix("claude-").replace("-", " "))
        annotations.append(ax.annotate(label, (x, y), xytext=(0, 20),
                    textcoords="offset points", ha="center", fontsize=9, color=ink,
                    bbox=dict(boxstyle="round,pad=.15", fc=background, ec="none", alpha=.94),
                    arrowprops=dict(arrowstyle="-", color=color, lw=.6, alpha=.6),
                    linespacing=1.5))
    place_labels(fig, ax, annotations, [(p["mean_cost_usd"], p["soft_score"]) for p in points])
    text_counts = sorted({p['texts'] for p in points})
    call_counts = sorted({p['calls'] for p in points})
    counts = (f"{len({p['model'] for p in points})} models · {len(points)} settings · "
              f"{'/'.join(map(str, text_counts))} texts per setting · {'/'.join(map(str, call_counts))} calls per setting")
    fig.text(.10, .14 if portrait else .115,
             "SCORE = ½ speaker confidence + ½ matching-context confidence", fontsize=10,
             color=ink, weight="bold")
    fig.text(.10, .105 if portrait else .078,
             "Candidate lists normalized above 100%. Equal weight per text. S6 control excluded.",
             fontsize=9, color=muted)
    fig.text(.10, .075 if portrait else .047, counts, fontsize=8, color=muted)
    fig.text(.10, .045 if portrait else .018, f"Run {directory.name} · {SCORING_VERSION} · self-reported confidence · recorded API cost", fontsize=8, color=muted)
    for extension in ("png", "svg"):
        fig.savefig(directory / f"cost_score.{extension}", dpi=dpi, facecolor=background)
    plt.close(fig)
    print(f"Charts: {directory}/cost_score.png and cost_score.svg")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    dimensions = parser.add_mutually_exclusive_group()
    dimensions.add_argument("--aspect-ratio", type=parse_dimensions, metavar="W:H",
                            help="target canvas ratio, e.g. 4:5")
    dimensions.add_argument("--size", type=parse_dimensions, metavar="WIDTHxHEIGHT",
                            help="exact PNG dimensions, e.g. 1080x1350; SVG uses the same ratio")
    args = parser.parse_args()
    from run_bench import run_targets, score, effective_records, read_attempts
    targets, _ = run_targets(args.run_dir)
    records = effective_records(read_attempts(args.run_dir))
    plot_results(args.run_dir, [score(r, targets) for r in records],
                 aspect_ratio=args.aspect_ratio, size=args.size)


if __name__ == "__main__":
    main()
