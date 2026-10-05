"""Build descriptive corridor and pricing opportunity summaries for RPW CC1."""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ECONOMICS_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_cc1_economics.csv"
FX_SENSITIVITY_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_cc1_fx_sensitivity.csv"
FEE_SENSITIVITY_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_cc1_fee_sensitivity.csv"
RAW_RPW_FILE = PROJECT_ROOT / "data" / "raw" / "rpw_dataset_2011_2025_q1.xlsx"
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_corridor_opportunity.csv"

ECONOMICS_COLUMNS = [
    "id",
    "period",
    "corridor",
    "firm",
    "source_code",
    "source_name",
    "destination_code",
    "destination_name",
    "cc1_denomination_amount",
    "fee_pct",
    "cc1_fx_margin",
    "cc1_total_cost_pct",
]

FX_SCENARIOS = {
    "FX reduction 0.50pp": "fx_0_50pp",
    "FX reduction 1.00pp": "fx_1_00pp",
}
FEE_SCENARIOS = {
    "Fee reduction 10%": "fee_10pct",
    "Fee reduction 20%": "fee_20pct",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_hashes() -> dict[Path, str]:
    """Capture hashes to verify this script leaves all source files unchanged."""
    return {
        path: sha256_file(path)
        for path in [ECONOMICS_FILE, FX_SENSITIVITY_FILE, FEE_SENSITIVITY_FILE, RAW_RPW_FILE]
    }


def describe_corridor_distributions(corridors: pd.DataFrame) -> None:
    print("CORRIDOR DISTRIBUTIONS (all surveyed observations; not transaction volumes)")
    for column in [
        "observation_count",
        "avg_total_cost_pct",
        "avg_fx_margin_pct",
        "avg_fee_pct",
    ]:
        values = pd.to_numeric(corridors[column], errors="coerce").dropna()
        print(f"\n{column}")
        print(
            values.describe(percentiles=[0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
            .round(3)
            .to_string()
        )

    ordered = corridors.sort_values("observation_count", ascending=False)
    total_observations = corridors["observation_count"].sum()
    print("\nSURVEY OBSERVATION CONCENTRATION (not customer transaction volume)")
    for number in [1, 5, 10, 20]:
        share = ordered.head(number)["observation_count"].sum() / total_observations * 100
        print(f"Top {number} corridors: {share:.2f}% of RPW observations")


def add_component_shares(economics: pd.DataFrame, corridors: pd.DataFrame) -> pd.DataFrame:
    fee = pd.to_numeric(economics["fee_pct"], errors="coerce")
    fx_margin = pd.to_numeric(economics["cc1_fx_margin"], errors="coerce")
    reconstructed_cost = fee + fx_margin
    valid = fee.notna() & fx_margin.notna() & fee.ge(0) & fx_margin.ge(0) & reconstructed_cost.gt(0)
    share_data = economics.loc[valid, ["corridor"]].copy()
    share_data["fee_component_sum"] = fee.loc[valid]
    share_data["fx_component_sum"] = fx_margin.loc[valid]
    share_data["reconstructed_cost_sum"] = reconstructed_cost.loc[valid]
    share_data["component_share_observation_count"] = 1
    component_totals = share_data.groupby("corridor", dropna=False).agg(
        fee_component_sum=("fee_component_sum", "sum"),
        fx_component_sum=("fx_component_sum", "sum"),
        reconstructed_cost_sum=("reconstructed_cost_sum", "sum"),
        component_share_observation_count=("component_share_observation_count", "sum"),
    )
    corridors = corridors.merge(
        component_totals,
        left_on="corridor",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    corridors["fee_share_of_reconstructed_cost"] = (
        corridors["fee_component_sum"] / corridors["reconstructed_cost_sum"] * 100
    )
    corridors["fx_share_of_reconstructed_cost"] = (
        corridors["fx_component_sum"] / corridors["reconstructed_cost_sum"] * 100
    )
    return corridors.drop(
        columns=["fee_component_sum", "fx_component_sum", "reconstructed_cost_sum"]
    )


def add_scenario_summary(
    corridors: pd.DataFrame,
    path: Path,
    scenarios: dict[str, str],
    kind: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "id",
        "corridor",
        "scenario_name",
        "cc1_total_cost_pct",
        "scenario_total_cost_pct",
        "scenario_saving_pp",
        "scenario_implied_saving_usd",
        "scenario_fee_pct",
        "scenario_fx_margin",
        "fee_pct",
        "cc1_fx_margin",
        "fx_reduction_pp",
        "fee_reduction_pct",
    ]
    data = pd.read_csv(path, usecols=columns, low_memory=False)
    expected_scenarios = set(scenarios)
    if kind == "fx":
        all_scenarios = {f"FX reduction {value:.2f}pp" for value in [0, 0.25, 0.5, 0.75, 1]}
    else:
        all_scenarios = {f"Fee reduction {value}%" for value in [0, 5, 10, 15, 20]}
    if set(data["scenario_name"].unique()) != all_scenarios:
        raise ValueError(f"Unexpected scenario names in {path.name}")
    if len(data) != 197_999 * 5:
        raise ValueError(f"Unexpected row count in {path.name}: {len(data):,}")

    per_scenario_rows = data.groupby("scenario_name").size()
    per_scenario_ids = data.groupby("scenario_name")["id"].nunique()
    if not per_scenario_rows.eq(197_999).all() or not per_scenario_ids.eq(197_999).all():
        raise ValueError(f"Source observations are missing or duplicated in {path.name}")

    valid = data["scenario_total_cost_pct"].notna()
    if not data.loc[valid, [
        "cc1_total_cost_pct",
        "scenario_saving_pp",
        "scenario_implied_saving_usd",
        "scenario_fee_pct",
        "scenario_fx_margin",
    ]].notna().all(axis=None):
        raise ValueError(f"Valid scenario rows contain missing outputs in {path.name}")
    if data.loc[~valid, [
        "scenario_saving_pp",
        "scenario_implied_saving_usd",
        "scenario_fee_pct",
        "scenario_fx_margin",
    ]].notna().any(axis=None):
        raise ValueError(f"Invalid scenario rows were filled in {path.name}")

    if kind == "fx":
        calculated_fee = data["fee_pct"]
        calculated_fx = data["cc1_fx_margin"] - data["fx_reduction_pp"]
    else:
        calculated_fee = data["fee_pct"] * (1 - data["fee_reduction_pct"] / 100)
        calculated_fx = data["cc1_fx_margin"]
    formula_checks = {
        "scenario_fee_pct": calculated_fee,
        "scenario_fx_margin": calculated_fx,
        "scenario_total_cost_pct": calculated_fee + calculated_fx,
        "scenario_saving_pp": data["cc1_total_cost_pct"] - (calculated_fee + calculated_fx),
        "scenario_implied_saving_usd": (
            200 * (data["cc1_total_cost_pct"] - (calculated_fee + calculated_fx)) / 100
        ),
    }
    for column, expected in formula_checks.items():
        matches = np.isclose(
            data.loc[valid, column].to_numpy(),
            expected.loc[valid].to_numpy(),
            rtol=1e-10,
            atol=1e-10,
        )
        if not matches.all():
            raise ValueError(f"Scenario formula mismatch in {column} from {path.name}")

    selected = data.loc[data["scenario_name"].isin(expected_scenarios)].copy()
    summary_rows = []
    for scenario_name, prefix in scenarios.items():
        scenario = selected.loc[
            selected["scenario_name"].eq(scenario_name)
            & selected["scenario_total_cost_pct"].notna()
        ]
        aggregate = scenario.groupby("corridor", dropna=False).agg(
            scenario_valid_observation_count=("id", "size"),
            mean_baseline_observed_total_cost_pct=("cc1_total_cost_pct", "mean"),
            mean_scenario_total_cost_pct=("scenario_total_cost_pct", "mean"),
            mean_saving_pp=("scenario_saving_pp", "mean"),
            median_saving_pp=("scenario_saving_pp", "median"),
            mean_implied_saving_usd=("scenario_implied_saving_usd", "mean"),
            median_implied_saving_usd=("scenario_implied_saving_usd", "median"),
        ).add_prefix(f"{prefix}_")
        corridors = corridors.merge(
            aggregate,
            left_on="corridor",
            right_index=True,
            how="left",
            validate="one_to_one",
        )
        summary_rows.append(
            {
                "scenario": scenario_name,
                "valid_observations": len(scenario),
                "mean_baseline_cost": scenario["cc1_total_cost_pct"].mean(),
                "mean_scenario_cost": scenario["scenario_total_cost_pct"].mean(),
                "mean_saving_pp": scenario["scenario_saving_pp"].mean(),
                "median_saving_pp": scenario["scenario_saving_pp"].median(),
                "mean_implied_saving_usd": scenario["scenario_implied_saving_usd"].mean(),
                "median_implied_saving_usd": scenario["scenario_implied_saving_usd"].median(),
            }
        )

    return corridors, pd.DataFrame(summary_rows)


def add_prioritisation_indicators(corridors: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    # The 100-observation screen follows the existing SQL corridor analysis.
    # It is a descriptive screen, not a statistical guarantee.
    count = corridors["observation_count"]
    corridors["sample_reliability_band"] = np.select(
        [count.lt(50), count.lt(100)],
        ["exploratory (<50)", "review (50-99)"],
        default="priority review (100+)",
    )
    reliable = count.ge(100)
    thresholds = {}
    for column, label, rank_column, flag_column in [
        (
            "median_total_cost_pct",
            "75th percentile of corridor median observed total cost (100+ observations) [median_total_cost_pct_q75]",
            "observed_cost_rank_100plus",
            "observed_cost_top_quartile_100plus",
        ),
        (
            "median_fx_margin_pct",
            "75th percentile of corridor median FX margin (100+ observations) [median_fx_margin_pct_q75]",
            "fx_margin_rank_100plus",
            "fx_margin_top_quartile_100plus",
        ),
        (
            "median_fee_pct",
            "75th percentile of corridor median fee (100+ observations) [median_fee_pct_q75]",
            "fee_rank_100plus",
            "fee_top_quartile_100plus",
        ),
    ]:
        values = corridors.loc[reliable, column]
        threshold = values.quantile(0.75)
        thresholds[label] = float(threshold)
        corridors[rank_column] = np.nan
        corridors.loc[reliable, rank_column] = values.rank(method="min", ascending=False)
        corridors[flag_column] = pd.Series(pd.NA, index=corridors.index, dtype="boolean")
        valid_metric = reliable & corridors[column].notna()
        corridors.loc[valid_metric, flag_column] = corridors.loc[valid_metric, column].ge(threshold)
    return corridors, thresholds


def main() -> None:
    hashes_before = input_hashes()
    economics = pd.read_csv(ECONOMICS_FILE, usecols=ECONOMICS_COLUMNS, low_memory=False)
    if len(economics) != 197_999:
        raise ValueError(f"Expected 197,999 CC1 economics rows; found {len(economics):,}")
    if economics["id"].duplicated().any():
        raise ValueError("CC1 economics input contains duplicate IDs")

    # Aggregate each surveyed corridor. The denomination average is the RPW
    # survey's standardized amount, not an observed customer transaction size.
    corridors = economics.groupby("corridor", dropna=False, as_index=False).agg(
        source_code=("source_code", "first"),
        source_name=("source_name", "first"),
        destination_code=("destination_code", "first"),
        destination_name=("destination_name", "first"),
        observation_count=("id", "size"),
        provider_count=("firm", "nunique"),
        period_count=("period", "nunique"),
        total_cost_observation_count=("cc1_total_cost_pct", "count"),
        avg_total_cost_pct=("cc1_total_cost_pct", "mean"),
        median_total_cost_pct=("cc1_total_cost_pct", "median"),
        min_total_cost_pct=("cc1_total_cost_pct", "min"),
        max_total_cost_pct=("cc1_total_cost_pct", "max"),
        fx_margin_observation_count=("cc1_fx_margin", "count"),
        avg_fx_margin_pct=("cc1_fx_margin", "mean"),
        median_fx_margin_pct=("cc1_fx_margin", "median"),
        fee_observation_count=("fee_pct", "count"),
        avg_fee_pct=("fee_pct", "mean"),
        median_fee_pct=("fee_pct", "median"),
        denomination_observation_count=("cc1_denomination_amount", "count"),
        avg_transfer_amount_usd=("cc1_denomination_amount", "mean"),
    )
    corridors = add_component_shares(economics, corridors)

    fx_scenario_summary = None
    fee_scenario_summary = None
    corridors, fx_scenario_summary = add_scenario_summary(
        corridors, FX_SENSITIVITY_FILE, FX_SCENARIOS, "fx"
    )
    corridors, fee_scenario_summary = add_scenario_summary(
        corridors, FEE_SENSITIVITY_FILE, FEE_SCENARIOS, "fee"
    )

    corridors, thresholds = add_prioritisation_indicators(corridors)
    describe_corridor_distributions(corridors)
    print("\nPRIORITISATION THRESHOLDS (75th percentile within corridors with 100+ observations)")
    for label, value in thresholds.items():
        print(f"{label}: {value:.4f}")
    print("\nFX SCENARIO SUMMARY (modelled; not observed outcomes)")
    print(fx_scenario_summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\nFEE SCENARIO SUMMARY (modelled; not observed outcomes)")
    print(fee_scenario_summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # Independent views avoid combining activity, cost, and components into an
    # unexplained score. Survey observation counts are not transaction volumes.
    reliable = corridors.loc[corridors["observation_count"].ge(100)]
    print("\nEXAMPLE CORRIDORS: HIGHEST MEDIAN OBSERVED TOTAL COST (100+ observations)")
    print(
        reliable.sort_values("median_total_cost_pct", ascending=False)[
            ["corridor", "observation_count", "median_total_cost_pct", "median_fee_pct", "median_fx_margin_pct"]
        ].head(10).to_string(index=False, float_format=lambda value: f"{value:.3f}")
    )

    output_columns = [
        "corridor",
        "source_code",
        "source_name",
        "destination_code",
        "destination_name",
        "observation_count",
        "provider_count",
        "period_count",
        "total_cost_observation_count",
        "avg_total_cost_pct",
        "median_total_cost_pct",
        "avg_fx_margin_pct",
        "median_fx_margin_pct",
        "fx_margin_observation_count",
        "avg_fee_pct",
        "median_fee_pct",
        "fee_observation_count",
        "avg_transfer_amount_usd",
        "denomination_observation_count",
        "min_total_cost_pct",
        "max_total_cost_pct",
        "component_share_observation_count",
        "fee_share_of_reconstructed_cost",
        "fx_share_of_reconstructed_cost",
        "sample_reliability_band",
        "observed_cost_rank_100plus",
        "fx_margin_rank_100plus",
        "fee_rank_100plus",
        "observed_cost_top_quartile_100plus",
        "fx_margin_top_quartile_100plus",
        "fee_top_quartile_100plus",
    ]
    for prefix in [*FX_SCENARIOS.values(), *FEE_SCENARIOS.values()]:
        output_columns.extend(
            [
                f"{prefix}_scenario_valid_observation_count",
                f"{prefix}_mean_baseline_observed_total_cost_pct",
                f"{prefix}_mean_scenario_total_cost_pct",
                f"{prefix}_mean_saving_pp",
                f"{prefix}_median_saving_pp",
                f"{prefix}_mean_implied_saving_usd",
                f"{prefix}_median_implied_saving_usd",
            ]
        )
    output = corridors[output_columns].sort_values("corridor", na_position="last").reset_index(drop=True)
    output.to_csv(OUTPUT_FILE, index=False)

    # Validate output uniqueness, source aggregation, ranges, and that input
    # hashes did not change during processing.
    checked = pd.read_csv(OUTPUT_FILE, low_memory=False)
    expected_corridors = economics["corridor"].nunique(dropna=False)
    if len(checked) != expected_corridors:
        raise ValueError("Output row count does not equal the source corridor count")
    if checked["corridor"].duplicated().any():
        raise ValueError("Output contains duplicate corridor rows")
    if checked["corridor"].nunique(dropna=False) != expected_corridors:
        raise ValueError("Output corridor keys do not match the source corridor keys")

    # Weighted corridor means must reproduce the corresponding economics-level means.
    aggregate_checks = [
        ("avg_total_cost_pct", "total_cost_observation_count", "cc1_total_cost_pct"),
        ("avg_fx_margin_pct", "fx_margin_observation_count", "cc1_fx_margin"),
        ("avg_fee_pct", "fee_observation_count", "fee_pct"),
        ("avg_transfer_amount_usd", "denomination_observation_count", "cc1_denomination_amount"),
    ]
    for mean_column, count_column, source_column in aggregate_checks:
        weighted_mean = (checked[mean_column] * checked[count_column]).sum() / checked[count_column].sum()
        source_mean = pd.to_numeric(economics[source_column], errors="coerce").mean()
        if not np.isclose(weighted_mean, source_mean, rtol=1e-10, atol=1e-10):
            raise ValueError(f"Corridor weighted {mean_column} does not match the source aggregate")

    numeric_columns = checked.select_dtypes(include=["number"]).columns
    infinite_values = int(np.isinf(checked[numeric_columns].to_numpy(dtype=float)).sum())
    if infinite_values:
        raise ValueError(f"Output has {infinite_values} infinite numeric values")
    hashes_after = input_hashes()
    unchanged = all(hashes_before[path] == hashes_after[path] for path in hashes_before)
    if not unchanged:
        raise ValueError("One or more source files changed during corridor analysis")

    print("\nVALIDATION")
    print("Output shape:", checked.shape)
    print("Expected / actual corridor count:", expected_corridors, checked["corridor"].nunique(dropna=False))
    print("Duplicate corridor rows:", int(checked["corridor"].duplicated().sum()))
    print("Missing corridor values:", int(checked["corridor"].isna().sum()))
    print("Numeric infinite values:", infinite_values)
    print("Weighted corridor means match economics aggregates: True")
    print("Raw, economics, and existing sensitivity inputs unchanged: True")
    print("Output CSV:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
