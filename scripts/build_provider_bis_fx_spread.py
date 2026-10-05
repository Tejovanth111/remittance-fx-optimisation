"""Build descriptive CC1 provider-rate versus normalized BIS spread analysis."""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_FILE = PROJECT_ROOT / "reports" / "normalized_bis_validation.csv"
BENCHMARK_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_bis_fx_benchmark_cc1.csv"
RPW_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_clean.csv"
PROTECTED_INPUTS = [
    VALIDATION_FILE,
    BENCHMARK_FILE,
    RPW_FILE,
    PROJECT_ROOT / "data" / "processed" / "bis_daily_fx.csv",
    PROJECT_ROOT / "data" / "processed" / "rpw_destination_currency_mapping.csv",
]
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_provider_bis_fx_spread.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def spread_statistics(values: pd.Series) -> dict[str, float | int]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    return {
        "observations": int(values.count()),
        "mean_spread": values.mean(),
        "median_spread": values.median(),
        "p25": values.quantile(0.25),
        "p75": values.quantile(0.75),
    }


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    input_hashes_before = {path: file_sha256(path) for path in PROTECTED_INPUTS}

    validation = pd.read_csv(VALIDATION_FILE, low_memory=False)
    benchmark_columns = [
        "id",
        "date",
        "corridor",
        "firm",
        "source_code",
        "destination_code",
        "cc1_lcu_amount",
        "cc1_lcu_code",
        "cc1_lcu_fee",
        "cc1_lcu_fx_rate",
        "cc1_fx_margin",
        "cc1_total_cost_pct",
        "inter_lcu_bank_fx",
    ]
    benchmark = pd.read_csv(
        BENCHMARK_FILE,
        usecols=benchmark_columns,
        dtype={"date": "string"},
        low_memory=False,
    )
    periods = pd.read_csv(
        RPW_FILE,
        usecols=["id", "period"],
        dtype={"period": "string"},
        low_memory=False,
    )

    if validation["id"].duplicated().any():
        raise ValueError("Normalized validation input contains duplicate IDs")
    if benchmark["id"].duplicated().any() or periods["id"].duplicated().any():
        raise ValueError("Benchmark and RPW period inputs must have unique IDs")
    if not validation["quote_orientation"].isin(["direct_match", "inverse_match"]).all():
        raise ValueError("Validation input contains observations outside direct/inverse match classes")
    if len(validation) != 48_097:
        raise ValueError(f"Expected 48,097 normalized observations; found {len(validation):,}")

    result = validation.merge(
        benchmark,
        on="id",
        how="left",
        validate="one_to_one",
        suffixes=("", "_benchmark"),
        indicator=True,
    )
    if not result["_merge"].eq("both").all():
        raise ValueError("Some normalized validation IDs are absent from the benchmark")
    result = result.drop(columns="_merge")

    period_subset = periods.loc[periods["id"].isin(result["id"])]
    if len(period_subset) != len(result):
        raise ValueError("RPW period IDs do not cover every normalized validation observation")
    result = result.merge(period_subset, on="id", how="left", validate="one_to_one")

    # Confirm that the ID join brought back the matching RPW observation keys.
    for column in ["date", "source_code", "destination_code"]:
        benchmark_column = f"{column}_benchmark"
        if benchmark_column in result.columns:
            mismatch = result[column].ne(result[benchmark_column])
            if mismatch.any():
                raise ValueError(f"Validation and benchmark {column} values differ for some IDs")
            result = result.drop(columns=benchmark_column)

    numeric_columns = [
        "normalized_bis_rate",
        "cc1_lcu_fx_rate",
        "inter_lcu_bank_fx",
        "cc1_fx_margin",
        "cc1_total_cost_pct",
    ]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    # Positive spread means the provider quote is below the normalized BIS
    # benchmark; negative spread means the provider quote is above it.
    result["provider_vs_bis_spread_pct"] = np.nan
    valid_bis = result["normalized_bis_rate"].notna() & result["normalized_bis_rate"].ne(0)
    result.loc[valid_bis, "provider_vs_bis_spread_pct"] = (
        (
            result.loc[valid_bis, "normalized_bis_rate"]
            - result.loc[valid_bis, "cc1_lcu_fx_rate"]
        )
        / result.loc[valid_bis, "normalized_bis_rate"]
        * 100
    )

    result["provider_rate_vs_rpw_interbank_pct"] = np.nan
    valid_interbank = result["inter_lcu_bank_fx"].notna() & result["inter_lcu_bank_fx"].ne(0)
    result.loc[valid_interbank, "provider_rate_vs_rpw_interbank_pct"] = (
        (
            result.loc[valid_interbank, "cc1_lcu_fx_rate"]
            - result.loc[valid_interbank, "inter_lcu_bank_fx"]
        )
        / result.loc[valid_interbank, "inter_lcu_bank_fx"].abs()
        * 100
    )

    output_columns = [
        "id",
        "date",
        "period",
        "corridor",
        "firm",
        "source_code",
        "destination_code",
        "source_currency",
        "destination_currency",
        "cc1_lcu_amount",
        "cc1_lcu_code",
        "cc1_lcu_fee",
        "cc1_lcu_fx_rate",
        "cc1_fx_margin",
        "cc1_total_cost_pct",
        "inter_lcu_bank_fx",
        "normalized_bis_rate",
        "quote_orientation",
        "provider_vs_bis_spread_pct",
        "provider_rate_vs_rpw_interbank_pct",
    ]
    output = result[output_columns].copy()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_FILE, index=False)

    print("1. TOTAL OBSERVATIONS:", len(output))
    print("2. QUOTE ORIENTATION COUNTS:")
    print(output["quote_orientation"].value_counts().reindex(["direct_match", "inverse_match"], fill_value=0).to_string())

    # 3. Overall spread distribution.
    spread = output["provider_vs_bis_spread_pct"]
    stats = spread_statistics(spread)
    stats["std"] = spread.std()
    stats["min"] = spread.min()
    stats["25%"] = spread.quantile(0.25)
    stats["50%"] = spread.quantile(0.50)
    stats["75%"] = spread.quantile(0.75)
    stats["90%"] = spread.quantile(0.90)
    stats["95%"] = spread.quantile(0.95)
    stats["99%"] = spread.quantile(0.99)
    stats["max"] = spread.max()
    print("\n3. PROVIDER_VS_BIS_SPREAD_PCT DESCRIPTIVE STATISTICS")
    print(pd.DataFrame([stats]).to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # 4. Spread sign groups use an explicitly descriptive 0.5% equal band.
    approximately_equal = spread.abs().le(0.5)
    spread_groups = pd.DataFrame(
        [
            ("provider_below_bis", spread.gt(0.5)),
            ("approximately_equal_abs_spread_le_0.5_pct", approximately_equal),
            ("provider_above_bis", spread.lt(-0.5)),
        ],
        columns=["category", "mask"],
    )
    sign_rows = [
        {
            "category": row.category,
            "observations": int(row.mask.sum()),
            "percentage": row.mask.mean() * 100,
        }
        for row in spread_groups.itertuples(index=False)
    ]
    print("\n4. PROVIDER RATE POSITION RELATIVE TO NORMALIZED BIS")
    print(pd.DataFrame(sign_rows).to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    print("Approximately equal uses ABS(spread) <= 0.5%; this is a descriptive threshold only.")

    # 5 and 11. Descriptive comparison with reported margin and total cost.
    print("\n5. PROVIDER_VS_BIS_SPREAD_PCT COMPARED WITH RPW CC1 FX MARGIN")
    margin_comparison = pd.DataFrame(
        [
            {
                "correlation": output["provider_vs_bis_spread_pct"].corr(output["cc1_fx_margin"]),
                "mean_spread": output["provider_vs_bis_spread_pct"].mean(),
                "median_spread": output["provider_vs_bis_spread_pct"].median(),
                "mean_rpw_fx_margin": output["cc1_fx_margin"].mean(),
                "median_rpw_fx_margin": output["cc1_fx_margin"].median(),
            }
        ]
    )
    print(margin_comparison.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\n11. CORRELATIONS (DESCRIPTIVE; NOT CAUSAL)")
    print(
        "spread vs total cost:",
        f"{output['provider_vs_bis_spread_pct'].corr(output['cc1_total_cost_pct']):.4f}",
    )
    print(
        "spread vs FX margin:",
        f"{output['provider_vs_bis_spread_pct'].corr(output['cc1_fx_margin']):.4f}",
    )

    # 6. Provider summaries with at least 100 validated observations.
    provider_summary = (
        output.groupby("firm")
        .agg(
            observations=("id", "size"),
            mean_spread=("provider_vs_bis_spread_pct", "mean"),
            median_spread=("provider_vs_bis_spread_pct", "median"),
            p25=("provider_vs_bis_spread_pct", lambda values: values.quantile(0.25)),
            p75=("provider_vs_bis_spread_pct", lambda values: values.quantile(0.75)),
            mean_rpw_fx_margin=("cc1_fx_margin", "mean"),
            mean_total_cost=("cc1_total_cost_pct", "mean"),
        )
        .reset_index()
    )
    provider_summary = provider_summary.loc[provider_summary["observations"].ge(100)].sort_values(
        "median_spread"
    )
    provider_summary.to_csv(REPORTS_DIR / "provider_bis_spread_by_provider.csv", index=False)
    print("\n6. PROVIDER ANALYSIS (AT LEAST 100 OBSERVATIONS), SORTED BY MEDIAN SPREAD")
    print(provider_summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("These are unadjusted observational comparisons, not rankings of provider quality.")

    # 7. Corridor summaries with at least 50 validated observations.
    corridor_summary = (
        output.groupby("corridor")
        .agg(
            observations=("id", "size"),
            mean_spread=("provider_vs_bis_spread_pct", "mean"),
            median_spread=("provider_vs_bis_spread_pct", "median"),
            p25=("provider_vs_bis_spread_pct", lambda values: values.quantile(0.25)),
            p75=("provider_vs_bis_spread_pct", lambda values: values.quantile(0.75)),
            mean_rpw_fx_margin=("cc1_fx_margin", "mean"),
            mean_total_cost=("cc1_total_cost_pct", "mean"),
        )
        .reset_index()
    )
    corridor_summary = corridor_summary.loc[corridor_summary["observations"].ge(50)].sort_values(
        "median_spread", ascending=False
    )
    corridor_summary.to_csv(REPORTS_DIR / "provider_bis_spread_by_corridor.csv", index=False)
    print("\n7. 15 CORRIDORS WITH HIGHEST MEDIAN SPREAD (AT LEAST 50 OBSERVATIONS)")
    print(corridor_summary.head(15).to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\n7. 15 CORRIDORS WITH LOWEST MEDIAN SPREAD (AT LEAST 50 OBSERVATIONS)")
    print(corridor_summary.tail(15).sort_values("median_spread").to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # 8. Provider-by-corridor summaries with at least 20 observations.
    provider_corridor = (
        output.groupby(["firm", "corridor"])
        .agg(
            observations=("id", "size"),
            median_spread=("provider_vs_bis_spread_pct", "median"),
            mean_spread=("provider_vs_bis_spread_pct", "mean"),
            median_rpw_fx_margin=("cc1_fx_margin", "median"),
            median_total_cost=("cc1_total_cost_pct", "median"),
        )
        .reset_index()
    )
    provider_corridor = provider_corridor.loc[provider_corridor["observations"].ge(20)]
    provider_corridor.to_csv(REPORTS_DIR / "provider_bis_spread_provider_corridor.csv", index=False)
    print("\n8. 20 LARGEST PROVIDER × CORRIDOR MEDIAN SPREADS (AT LEAST 20 OBSERVATIONS)")
    print(provider_corridor.nlargest(20, "median_spread").to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\n8. 20 SMALLEST PROVIDER × CORRIDOR MEDIAN SPREADS (AT LEAST 20 OBSERVATIONS)")
    print(provider_corridor.nsmallest(20, "median_spread").to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # 9. This is a CC1-only validation input; do not manufacture CC2 results.
    print("\n9. CC1 / CC2 COMPARISON")
    print("The supplied normalized benchmark is CC1-only; no CC2/$500 benchmark was created or compared.")

    # 10. Preserve and display the 20 largest absolute spreads.
    extreme_columns = [
        "id",
        "date",
        "corridor",
        "firm",
        "source_currency",
        "destination_currency",
        "cc1_lcu_fx_rate",
        "inter_lcu_bank_fx",
        "normalized_bis_rate",
        "provider_vs_bis_spread_pct",
        "cc1_fx_margin",
        "cc1_total_cost_pct",
    ]
    extremes = output.assign(
        absolute_provider_vs_bis_spread_pct=output["provider_vs_bis_spread_pct"].abs()
    ).nlargest(20, "absolute_provider_vs_bis_spread_pct")[extreme_columns]
    extremes.to_csv(REPORTS_DIR / "provider_bis_spread_extremes.csv", index=False)
    print("\n10. 20 LARGEST ABSOLUTE PROVIDER_VS_BIS_SPREAD_PCT OBSERVATIONS")
    print(extremes.to_string(index=False, float_format=lambda value: f"{value:.5f}"))

    # 12. GBR to IND exact-date validation.
    gbr_ind = output.loc[
        output["source_code"].eq("GBR")
        & output["destination_code"].eq("IND")
        & output["date"].eq("2016-05-10"),
        [
            "firm",
            "cc1_lcu_fx_rate",
            "inter_lcu_bank_fx",
            "normalized_bis_rate",
            "provider_vs_bis_spread_pct",
            "cc1_fx_margin",
            "cc1_total_cost_pct",
        ],
    ]
    print("\n12. GBR→IND 2016-05-10")
    if gbr_ind.empty:
        print("No normalized direct/inverse observations found")
    else:
        print(gbr_ind.to_string(index=False, float_format=lambda value: f"{value:.5f}"))

    # Validation and read-back.
    read_back = pd.read_csv(OUTPUT_FILE, low_memory=False)
    if len(output) != len(validation) or len(read_back) != 48_097:
        raise ValueError("Output row count does not match the 48,097 validated source observations")
    if output["id"].nunique() != len(output) or read_back["id"].nunique() != len(read_back):
        raise ValueError("Output contains duplicate observation IDs")
    if set(output["quote_orientation"]) != {"direct_match", "inverse_match"}:
        raise ValueError("Output contains a quote orientation outside the two included classes")

    input_hashes_after = {path: file_sha256(path) for path in PROTECTED_INPUTS}
    protected_inputs_unchanged = input_hashes_before == input_hashes_after
    if not protected_inputs_unchanged:
        raise ValueError("A protected source file changed during this script run")

    print("\nVALIDATION")
    print("Output rows:", len(read_back))
    print("Unique IDs:", read_back["id"].nunique())
    print("Source-file hashes unchanged:", protected_inputs_unchanged)
    print("No source observations deleted or altered: True (inputs remain read-only; output IDs match validation input)")
    print("Output date range:", read_back["date"].min(), "to", read_back["date"].max())
    print("Output corridor count:", read_back["corridor"].nunique())
    print("Output provider count:", read_back["firm"].nunique())
    print("Output CSV:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
