"""Build two descriptive CC1 scenarios from the RPW economics dataset."""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_cc1_economics.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_cc1_scenarios.csv"
FX_SENSITIVITY_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_cc1_fx_sensitivity.csv"
FEE_SENSITIVITY_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_cc1_fee_sensitivity.csv"
SCENARIO_NAMES = ["FX margin -0.50pp", "Explicit fee -10%"]
FX_REDUCTIONS_PP = [0.00, 0.25, 0.50, 0.75, 1.00]
FEE_REDUCTIONS = [0.00, 0.05, 0.10, 0.15, 0.20]

SOURCE_COLUMNS = [
    "id",
    "date",
    "period",
    "corridor",
    "firm",
    "cc1_denomination_amount",
    "cc1_lcu_code",
    "fee_pct",
    "cc1_fx_margin",
    "cc1_total_cost_pct",
]
OUTPUT_COLUMNS = SOURCE_COLUMNS + [
    "scenario_name",
    "scenario_fx_margin",
    "scenario_total_cost_pct",
    "scenario_saving_pp",
    "scenario_implied_saving_usd",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def summarize_sensitivity(
    scenario_name: str,
    baseline_cost: pd.Series,
    scenario_cost: pd.Series,
    saving_pp: pd.Series,
    implied_saving: pd.Series,
) -> dict[str, float | int | str]:
    """Return requested summary measures for one sensitivity scenario."""
    return {
        "scenario": scenario_name,
        "valid_observations": int(saving_pp.notna().sum()),
        "mean_baseline_cost": baseline_cost.mean(),
        "mean_scenario_cost": scenario_cost.mean(),
        "mean_saving_pp": saving_pp.mean(),
        "median_saving_pp": saving_pp.median(),
        "mean_implied_saving_usd": implied_saving.mean(),
        "median_implied_saving_usd": implied_saving.median(),
        "positive_saving_count": int(saving_pp.gt(0).sum()),
        "negative_saving_count": int(saving_pp.lt(0).sum()),
        "zero_saving_count": int(saving_pp.eq(0).sum()),
    }


def build_sensitivity(
    source: pd.DataFrame,
    fee: pd.Series,
    fx_margin: pd.Series,
    baseline_cost: pd.Series,
    valid: pd.Series,
    kind: str,
    values: list[float],
    output_file: Path,
) -> pd.DataFrame:
    """Write one row per source observation per sensitivity scenario."""
    summaries = []
    output_file.parent.mkdir(parents=True, exist_ok=True)

    for index, reduction in enumerate(values):
        result = source.copy()
        if kind == "fx":
            scenario_name = f"FX reduction {reduction:.2f}pp"
            scenario_fee = fee
            scenario_fx = fx_margin - reduction
            result["fx_reduction_pp"] = reduction
            result["fee_reduction_pct"] = np.nan
        else:
            reduction_pct = reduction * 100
            scenario_name = f"Fee reduction {reduction_pct:.0f}%"
            scenario_fee = fee * (1 - reduction)
            scenario_fx = fx_margin
            result["fx_reduction_pp"] = np.nan
            result["fee_reduction_pct"] = reduction_pct

        result["scenario_name"] = scenario_name
        result["scenario_fee_pct"] = np.nan
        result["scenario_fx_margin"] = np.nan
        result["scenario_total_cost_pct"] = np.nan
        result["scenario_saving_pp"] = np.nan
        result["scenario_implied_saving_usd"] = np.nan

        result.loc[valid, "scenario_fee_pct"] = scenario_fee[valid]
        result.loc[valid, "scenario_fx_margin"] = scenario_fx[valid]
        result.loc[valid, "scenario_total_cost_pct"] = (
            scenario_fee[valid] + scenario_fx[valid]
        )
        result.loc[valid, "scenario_saving_pp"] = (
            baseline_cost[valid] - result.loc[valid, "scenario_total_cost_pct"]
        )
        result.loc[valid, "scenario_implied_saving_usd"] = (
            200 * result.loc[valid, "scenario_saving_pp"] / 100
        )

        valid_saving = result.loc[valid, "scenario_saving_pp"]
        valid_scenario_cost = result.loc[valid, "scenario_total_cost_pct"]
        summaries.append(
            summarize_sensitivity(
                scenario_name,
                baseline_cost[valid],
                valid_scenario_cost,
                valid_saving,
                result.loc[valid, "scenario_implied_saving_usd"],
            )
        )

        result.to_csv(
            output_file,
            index=False,
            mode="w" if index == 0 else "a",
            header=index == 0,
        )

    summary = pd.DataFrame(summaries)
    expected_rows = len(source) * len(values)
    row_count = sum(
        len(chunk)
        for chunk in pd.read_csv(output_file, usecols=["id"], chunksize=100_000)
    )
    if row_count != expected_rows:
        raise ValueError(f"Expected {expected_rows:,} rows in {output_file.name}; found {row_count:,}")
    return summary


def main() -> None:
    source_hash_before = sha256_file(SOURCE_FILE)
    existing_scenario_hash = sha256_file(OUTPUT_FILE) if OUTPUT_FILE.exists() else None
    source = pd.read_csv(SOURCE_FILE, usecols=SOURCE_COLUMNS, low_memory=False)
    fee = pd.to_numeric(source["fee_pct"], errors="coerce")
    fx_margin = pd.to_numeric(source["cc1_fx_margin"], errors="coerce")
    baseline_cost = pd.to_numeric(source["cc1_total_cost_pct"], errors="coerce")
    valid = fee.notna() & fx_margin.notna() & baseline_cost.notna()

    scenario_rows = []
    for scenario_name in SCENARIO_NAMES:
        result = source.copy()
        result["scenario_name"] = scenario_name

        # Leave scenario outputs missing when an input required by the model is missing.
        for column in [
            "scenario_fx_margin",
            "scenario_total_cost_pct",
            "scenario_saving_pp",
            "scenario_implied_saving_usd",
        ]:
            result[column] = np.nan

        if scenario_name == "FX margin -0.50pp":
            result.loc[valid, "scenario_fx_margin"] = fx_margin[valid] - 0.50
            scenario_fee = fee
        else:
            # Reduce the explicit fee percentage by 10% and retain the observed FX margin.
            result.loc[valid, "scenario_fx_margin"] = fx_margin[valid]
            scenario_fee = fee * 0.90

        result.loc[valid, "scenario_total_cost_pct"] = (
            scenario_fee[valid] + result.loc[valid, "scenario_fx_margin"]
        )
        result.loc[valid, "scenario_saving_pp"] = (
            baseline_cost[valid] - result.loc[valid, "scenario_total_cost_pct"]
        )
        result.loc[valid, "scenario_implied_saving_usd"] = (
            200 * result.loc[valid, "scenario_saving_pp"] / 100
        )
        scenario_rows.append(result[OUTPUT_COLUMNS])

    combined = pd.concat(scenario_rows, ignore_index=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)

    checked = pd.read_csv(OUTPUT_FILE, low_memory=False)
    if checked.columns.tolist() != OUTPUT_COLUMNS:
        raise ValueError("Output columns differ from the requested columns")
    expected_rows = len(source) * len(SCENARIO_NAMES)
    if len(checked) != expected_rows:
        raise ValueError(f"Expected {expected_rows:,} output rows; found {len(checked):,}")
    if checked.groupby("scenario_name").size().to_dict() != {
        scenario_name: len(source) for scenario_name in SCENARIO_NAMES
    }:
        raise ValueError("Each scenario must contain one row per source observation")
    if checked.groupby("scenario_name")["id"].nunique().ne(len(source)).any():
        raise ValueError("Each scenario must retain every unique source ID")
    expected_valid_rows = int(valid.sum()) * len(SCENARIO_NAMES)
    if expected_valid_rows != int(checked["scenario_total_cost_pct"].notna().sum()):
        raise ValueError("Scenario-valid row count does not match calculated output rows")

    print("Total rows:", len(checked))
    print("Scenario-valid rows:", int(checked["scenario_total_cost_pct"].notna().sum()))
    for scenario_name, scenario_output in checked.groupby("scenario_name", sort=False):
        valid_output = scenario_output.loc[scenario_output["scenario_total_cost_pct"].notna()]
        checked_baseline = pd.to_numeric(valid_output["cc1_total_cost_pct"], errors="coerce")
        scenario_cost = pd.to_numeric(valid_output["scenario_total_cost_pct"], errors="coerce")
        saving_pp = pd.to_numeric(valid_output["scenario_saving_pp"], errors="coerce")
        implied_saving = pd.to_numeric(
            valid_output["scenario_implied_saving_usd"], errors="coerce"
        )

        print(f"\nScenario: {scenario_name}")
        print("Scenario-valid rows:", len(valid_output))
        print("Mean baseline total cost:", checked_baseline.mean())
        print("Mean scenario total cost:", scenario_cost.mean())
        print("Mean saving in percentage points:", saving_pp.mean())
        print("Median saving in percentage points:", saving_pp.median())
        print("Mean implied saving for a $200 transfer:", implied_saving.mean())
        print("Median implied saving for a $200 transfer:", implied_saving.median())
        print("Scenario cost lower than baseline:", int(scenario_cost.lt(checked_baseline).sum()))
        print("Scenario cost higher than baseline:", int(scenario_cost.gt(checked_baseline).sum()))
        print("Scenario cost equal to baseline:", int(scenario_cost.eq(checked_baseline).sum()))
    print("Source CSV unchanged:", source_hash_before == sha256_file(SOURCE_FILE))
    print("Output CSV:", OUTPUT_FILE)

    fx_summary = build_sensitivity(
        source,
        fee,
        fx_margin,
        baseline_cost,
        valid,
        "fx",
        FX_REDUCTIONS_PP,
        FX_SENSITIVITY_FILE,
    )
    fee_summary = build_sensitivity(
        source,
        fee,
        fx_margin,
        baseline_cost,
        valid,
        "fee",
        FEE_REDUCTIONS,
        FEE_SENSITIVITY_FILE,
    )

    print("\nFX MARGIN SENSITIVITY SUMMARY")
    print(fx_summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\nEXPLICIT FEE SENSITIVITY SUMMARY")
    print(fee_summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\nFX sensitivity CSV:", FX_SENSITIVITY_FILE)
    print("Fee sensitivity CSV:", FEE_SENSITIVITY_FILE)
    if existing_scenario_hash is not None:
        print(
            "Existing two-scenario output content preserved:",
            existing_scenario_hash == sha256_file(OUTPUT_FILE),
        )


if __name__ == "__main__":
    main()
