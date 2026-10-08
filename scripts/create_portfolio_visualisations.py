"""Create portfolio-ready figures from the existing processed RPW outputs."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "remittance-fx-mpl-cache"))
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FIGURES_DIR = ROOT / "reports" / "figures"
ECONOMICS = ROOT / "data" / "processed" / "rpw_cc1_economics.csv"
CORRIDORS = ROOT / "data" / "processed" / "rpw_corridor_opportunity.csv"
FEE_SENSITIVITY = ROOT / "data" / "processed" / "rpw_cc1_fee_sensitivity.csv"
FX_SENSITIVITY = ROOT / "data" / "processed" / "rpw_cc1_fx_sensitivity.csv"
BIS_SPREAD = ROOT / "data" / "processed" / "rpw_provider_bis_fx_spread.csv"

HIGH_COST_CORRIDORS = [
    "TZAUGA", "ZAFAGO", "ZAFSWZ", "THACHN", "ZAFCHN",
    "THALAO", "GBRGMB", "JORSYR", "SWESOM", "NZLTON",
]
FEE_LEVELS = [5, 10, 15, 20]
FX_LEVELS = [0.25, 0.50, 0.75, 1.00]
OUTPUTS = [
    "01_overall_observed_total_cost_distribution.png",
    "02_top15_corridors_median_total_cost.png",
    "03_top15_corridors_observation_count.png",
    "04_corridor_median_fee_vs_fx_margin.png",
    "05_provider_pricing_variation_selected_corridors.png",
    "06_fee_reduction_sensitivity_200_usd.png",
    "07_fx_margin_reduction_sensitivity_200_usd.png",
    "08_provider_fx_spread_vs_normalized_bis.png",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def note(ax: plt.Axes, text: str) -> None:
    ax.text(
        0.01, -0.20, text, transform=ax.transAxes,
        ha="left", va="top", fontsize=8, color="#536273",
        wrap=True,
    )


def save(fig: plt.Figure, filename: str) -> None:
    fig.savefig(FIGURES_DIR / filename, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_total_cost_distribution(economics: pd.DataFrame) -> None:
    values = pd.to_numeric(economics["cc1_total_cost_pct"], errors="coerce").dropna()
    fig, (full_ax, zoom_ax) = plt.subplots(
        2, 1, figsize=(11, 7), gridspec_kw={"height_ratios": [1, 1.25]}
    )
    full_ax.hist(values, bins=100, color="#2C6E8F", edgecolor="white", linewidth=0.25)
    full_ax.set_title("Overall observed total-cost distribution", loc="left", weight="bold", pad=10)
    full_ax.set_xlabel("Observed total cost (% of transfer amount)")
    full_ax.set_ylabel("Surveyed pricing observations")
    full_ax.grid(axis="y", alpha=0.2)

    low, high = -10, 30
    zoom_values = values.loc[values.between(low, high)]
    zoom_ax.hist(zoom_values, bins=80, range=(low, high), color="#2C6E8F", edgecolor="white", linewidth=0.25)
    zoom_ax.set_title(f"Central display window ({low}% to {high}%)", loc="left", fontsize=10, weight="bold")
    zoom_ax.set_xlabel("Observed total cost (% of transfer amount)")
    zoom_ax.set_ylabel("Surveyed pricing observations")
    zoom_ax.grid(axis="y", alpha=0.2)
    outside = len(values) - len(zoom_values)
    note(zoom_ax, f"Source: rpw_cc1_economics.csv; {len(values):,} non-missing observations. Full-range panel includes all values. Zoom panel displays {len(zoom_values):,}; {outside:,} observations outside its display window are retained in the source and shown only in the full-range panel.")
    fig.tight_layout(h_pad=1.7)
    save(fig, OUTPUTS[0])


def plot_corridor_cost(corridors: pd.DataFrame) -> None:
    eligible = corridors.loc[corridors["observation_count"].ge(100)].copy()
    top = eligible.sort_values("median_total_cost_pct", ascending=False).head(15).sort_values("median_total_cost_pct")
    fig, ax = plt.subplots(figsize=(11, 7))
    bars = ax.barh(top["corridor"], top["median_total_cost_pct"], color="#2C6E8F")
    ax.set_title("15 highest-median-cost corridors", loc="left", weight="bold", pad=10)
    ax.set_xlabel("Median observed total cost (% of transfer amount)")
    ax.set_ylabel("Corridor")
    ax.grid(axis="x", alpha=0.2)
    xmax = max(0, float(top["median_total_cost_pct"].max()))
    ax.set_xlim(min(0, float(top["median_total_cost_pct"].min()) * 1.25), xmax * 1.25 if xmax else 1)
    for bar, count in zip(bars, top["observation_count"]):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height()/2, f"  n={int(count):,}", va="center", fontsize=8)
    note(ax, "Source: rpw_corridor_opportunity.csv. Restricted to corridors with at least 100 surveyed pricing observations; n is observation count, not transaction volume.")
    fig.tight_layout()
    save(fig, OUTPUTS[1])


def plot_corridor_counts(corridors: pd.DataFrame) -> None:
    top = corridors.sort_values("observation_count", ascending=False).head(15).sort_values("observation_count")
    fig, ax = plt.subplots(figsize=(11, 7))
    bars = ax.barh(top["corridor"], top["observation_count"], color="#58A68F")
    ax.set_title("15 corridors with the most surveyed pricing observations", loc="left", weight="bold", pad=10)
    ax.set_xlabel("Surveyed pricing observations (count)")
    ax.set_ylabel("Corridor")
    ax.grid(axis="x", alpha=0.2)
    for bar, median in zip(bars, top["median_total_cost_pct"]):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height()/2, f"  median {median:.2f}%", va="center", fontsize=8)
    note(ax, "Source: rpw_corridor_opportunity.csv. Observation counts describe surveyed prices, not transaction volumes or market share; labels give median observed total cost.")
    fig.tight_layout()
    save(fig, OUTPUTS[2])


def plot_fee_fx(corridors: pd.DataFrame) -> None:
    data = corridors.dropna(subset=["median_fee_pct", "median_fx_margin_pct"])
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(data["median_fee_pct"], data["median_fx_margin_pct"], s=25, alpha=0.55, color="#2C6E8F", edgecolors="none")
    ax.axhline(0, color="#7B8794", linewidth=0.8)
    ax.axvline(0, color="#7B8794", linewidth=0.8)
    ax.set_title("Corridor fee and FX-margin components", loc="left", weight="bold", pad=10)
    ax.set_xlabel("Corridor median explicit fee (% of transfer amount)")
    ax.set_ylabel("Corridor median FX margin (%)")
    ax.grid(alpha=0.18)
    note(ax, "Source: rpw_corridor_opportunity.csv. One point per corridor; axes show median explicit fee and median FX margin. Full observed corridor range is displayed.")
    fig.tight_layout()
    save(fig, OUTPUTS[3])


def plot_provider_variation(economics: pd.DataFrame) -> None:
    data = economics.loc[economics["corridor"].isin(HIGH_COST_CORRIDORS), ["corridor", "firm", "cc1_total_cost_pct"]].copy()
    data["cc1_total_cost_pct"] = pd.to_numeric(data["cc1_total_cost_pct"], errors="coerce")
    data = data.dropna(subset=["firm", "cc1_total_cost_pct"])
    provider = data.groupby(["corridor", "firm"], as_index=False).agg(
        observation_count=("cc1_total_cost_pct", "size"),
        median_total_cost_pct=("cc1_total_cost_pct", "median"),
    )
    provider = provider.loc[provider["observation_count"].ge(10)]
    grouped = [provider.loc[provider["corridor"].eq(c), "median_total_cost_pct"].to_numpy() for c in HIGH_COST_CORRIDORS]
    labels = [f"{c}\n({int((provider.corridor == c).sum())} providers)" for c in HIGH_COST_CORRIDORS]
    fig, ax = plt.subplots(figsize=(13, 7))
    bp = ax.boxplot(grouped, tick_labels=labels, patch_artist=True, showfliers=True, whis=(0, 100), widths=0.62)
    for box in bp["boxes"]:
        box.set(facecolor="#B7D9D0", edgecolor="#2C6E8F")
    for part in ["whiskers", "caps", "medians"]:
        for item in bp[part]:
            item.set(color="#2C6E8F", linewidth=1.1)
    rng = np.random.default_rng(2026)
    for index, vals in enumerate(grouped, start=1):
        if len(vals):
            ax.scatter(rng.normal(index, 0.045, len(vals)), vals, s=17, alpha=0.65, color="#264653", zorder=3)
    ax.set_title("Descriptive provider pricing variation in selected corridors", loc="left", weight="bold", pad=10)
    ax.set_xlabel("Selected corridor (number of included providers)")
    ax.set_ylabel("Provider median observed total cost (% of transfer amount)")
    ax.grid(axis="y", alpha=0.2)
    note(ax, "Source: rpw_cc1_economics.csv. Each dot is one provider's median observed total cost; providers need at least 10 observations within that corridor. Box summaries describe variation and do not rank providers.")
    fig.tight_layout()
    save(fig, OUTPUTS[4])


def scenario_summary(path: Path, kind: str, levels: list[float]) -> pd.DataFrame:
    value_col = "fee_reduction_pct" if kind == "fee" else "fx_reduction_pp"
    needed = [value_col, "scenario_implied_saving_usd"]
    data = pd.read_csv(path, usecols=needed, low_memory=False)
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce")
    data["scenario_implied_saving_usd"] = pd.to_numeric(data["scenario_implied_saving_usd"], errors="coerce")
    data = data.loc[data[value_col].isin(levels)].dropna(subset=["scenario_implied_saving_usd"])
    summary = data.groupby(value_col)["scenario_implied_saving_usd"].agg(["mean", "median", "count"])
    return summary.reindex(levels)


def plot_sensitivity(summary: pd.DataFrame, levels: list[float], kind: str) -> None:
    positions = np.arange(len(levels))
    labels = [f"{v:.0f}%" for v in levels] if kind == "fee" else [f"{v:.2f} pp" for v in levels]
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(positions, summary["mean"], marker="o", linewidth=2.3, color="#2C6E8F", label="Mean implied saving")
    ax.plot(positions, summary["median"], marker="o", linewidth=1.8, color="#58A68F", label="Median implied saving")
    ax.set_xticks(positions, labels)
    if kind == "fee":
        title = "Explicit-fee reduction sensitivity"
        xlabel = "Modelled reduction in explicit fee (%)"
        note_text = "Source: rpw_cc1_fee_sensitivity.csv. Sensitivity analysis, not a forecast. Scenario output translates modelled fee changes to implied saving on a standardized $200 transfer."
    else:
        title = "FX-margin reduction sensitivity"
        xlabel = "Modelled FX-margin reduction (percentage points)"
        note_text = "Source: rpw_cc1_fx_sensitivity.csv. Sensitivity analysis, not a forecast. Scenario output translates modelled FX-margin changes to implied saving on a standardized $200 transfer."
    ax.set_title(title, loc="left", weight="bold", pad=10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Modelled implied saving (USD per $200 transfer)")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2)
    note(ax, note_text + " Means and medians are across valid scenario observations.")
    fig.tight_layout()
    save(fig, OUTPUTS[5] if kind == "fee" else OUTPUTS[6])


def plot_bis_spread(bis: pd.DataFrame) -> None:
    x = pd.to_numeric(bis["provider_vs_bis_spread_pct"], errors="coerce")
    y = pd.to_numeric(bis["cc1_fx_margin"], errors="coerce")
    valid = x.notna() & y.notna()
    fig, ax = plt.subplots(figsize=(10, 7))
    hb = ax.hexbin(x[valid], y[valid], gridsize=65, mincnt=1, bins="log", cmap="viridis", linewidths=0)
    fig.colorbar(hb, ax=ax, label="Observations per hexagon (log scale)")
    ax.axhline(0, color="white", linewidth=0.8, alpha=0.8)
    ax.axvline(0, color="white", linewidth=0.8, alpha=0.8)
    ax.set_title("Provider FX spread versus normalized BIS benchmark", loc="left", weight="bold", pad=10)
    ax.set_xlabel("Provider-vs-BIS spread (%)")
    ax.set_ylabel("RPW FX margin (%)")
    ax.grid(alpha=0.12)
    note(ax, "Source: rpw_provider_bis_fx_spread.csv; matched direct/inverse quote-orientation observations only. Benchmark comparison, not provider profit, markup, or FX revenue. Axes show the full range; hexagons encode observation density.")
    fig.tight_layout()
    save(fig, OUTPUTS[7])


def main() -> None:
    sources = [ECONOMICS, CORRIDORS, FEE_SENSITIVITY, FX_SENSITIVITY, BIS_SPREAD]
    source_hashes = {path: sha256(path) for path in sources}
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 15,
        "axes.labelsize": 10,
        "figure.dpi": 120,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })

    economics = pd.read_csv(ECONOMICS, low_memory=False)
    corridors = pd.read_csv(CORRIDORS, low_memory=False)
    plot_total_cost_distribution(economics)
    plot_corridor_cost(corridors)
    plot_corridor_counts(corridors)
    plot_fee_fx(corridors)
    plot_provider_variation(economics)
    plot_sensitivity(scenario_summary(FEE_SENSITIVITY, "fee", FEE_LEVELS), FEE_LEVELS, "fee")
    plot_sensitivity(scenario_summary(FX_SENSITIVITY, "fx", FX_LEVELS), FX_LEVELS, "fx")
    bis = pd.read_csv(BIS_SPREAD, usecols=["cc1_fx_margin", "provider_vs_bis_spread_pct"], low_memory=False)
    plot_bis_spread(bis)

    missing = [name for name in OUTPUTS if not (FIGURES_DIR / name).is_file()]
    changed = [str(path.relative_to(ROOT)) for path, digest in source_hashes.items() if sha256(path) != digest]
    if missing:
        raise RuntimeError(f"Expected figures missing: {missing}")
    if changed:
        raise RuntimeError(f"Source dataset hashes changed: {changed}")
    print("Validated figures:")
    for name in OUTPUTS:
        print(f"- {name}")
    print("Source datasets unchanged:", len(source_hashes))
    print("Figure directory:", FIGURES_DIR.relative_to(ROOT))


if __name__ == "__main__":
    main()
