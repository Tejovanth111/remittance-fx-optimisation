"""Audit coverage and sample composition of the RPW + BIS CC1 benchmark."""

from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_bis_fx_benchmark_cc1.csv"
RPW_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_clean.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"

EXPECTED_ROWS = 197_999
EXPECTED_AVAILABLE = 60_074
EXPECTED_UNAVAILABLE = 137_925
EXPECTED_DATE_MIN = "2016-05-09"
EXPECTED_DATE_MAX = "2025-03-14"

EXPECTED_COLUMNS = [
    "id",
    "date",
    "source_code",
    "source_name",
    "destination_code",
    "destination_name",
    "firm",
    "cc1_lcu_code",
    "destination_currency",
    "cc1_lcu_amount",
    "cc1_lcu_fee",
    "cc1_lcu_fx_rate",
    "cc1_fx_margin",
    "cc1_total_cost_pct",
    "inter_lcu_bank_fx",
    "source_bis_rate_per_usd",
    "destination_bis_rate_per_usd",
    "source_bis_series_count",
    "destination_bis_series_count",
    "bis_corridor_rate",
    "benchmark_available",
    "benchmark_unavailable_reason",
    "bis_minus_rpw_interbank",
    "bis_vs_rpw_interbank_pct",
    "provider_vs_bis_spread_pct",
    "corridor",
    "currency_mapping_status",
    "currency_candidates",
]


def coverage_table(data: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Summarize total, benchmarkable, and unavailable rows by one group."""
    summary = (
        data.groupby(group_column, dropna=False)
        .agg(
            total_observations=("id", "size"),
            benchmarkable_observations=("benchmark_available", "sum"),
        )
        .reset_index()
    )
    summary["unavailable_observations"] = (
        summary["total_observations"] - summary["benchmarkable_observations"]
    )
    summary["benchmark_availability_pct"] = (
        summary["benchmarkable_observations"] / summary["total_observations"] * 100
    )
    return summary.sort_values(
        ["total_observations", group_column],
        ascending=[False, True],
        na_position="last",
    ).reset_index(drop=True)


def describe_metric(values: pd.Series) -> dict[str, float | int]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    return {
        "count": int(values.count()),
        "mean": values.mean(),
        "median": values.median(),
        "standard_deviation": values.std(),
        "25th_percentile": values.quantile(0.25),
        "75th_percentile": values.quantile(0.75),
    }


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(BENCHMARK_FILE, low_memory=False)
    benchmark_columns = data.columns.tolist()

    # The benchmark intentionally has 28 columns and does not include RPW's
    # period field. Attach only that field by ID for the requested time table.
    periods = pd.read_csv(RPW_FILE, usecols=["id", "period"], dtype={"period": "string"})
    if periods["id"].duplicated().any():
        raise ValueError("RPW period lookup contains duplicate IDs")
    if len(periods) != len(data) or set(periods["id"]) != set(data["id"]):
        raise ValueError("RPW period lookup IDs do not match benchmark observation IDs")
    data = data.merge(periods, on="id", how="left", validate="one_to_one")

    data["benchmark_available"] = data["benchmark_available"].astype(bool)
    data["cc1_fx_margin"] = pd.to_numeric(data["cc1_fx_margin"], errors="coerce")
    data["cc1_total_cost_pct"] = pd.to_numeric(data["cc1_total_cost_pct"], errors="coerce")
    available_mask = data["benchmark_available"]
    available_count = int(available_mask.sum())
    unavailable_count = int((~available_mask).sum())

    # 1. Overall coverage.
    overall = pd.DataFrame(
        [
            {
                "total_rpw_observations": len(data),
                "benchmark_available_observations": available_count,
                "benchmark_unavailable_observations": unavailable_count,
                "benchmark_availability_pct": available_count / len(data) * 100,
            }
        ]
    )
    overall.to_csv(REPORTS_DIR / "benchmark_overall_coverage.csv", index=False)
    print("1. OVERALL COVERAGE")
    print(overall.to_string(index=False))

    # 2. Coverage by source currency.
    source_coverage = coverage_table(data, "cc1_lcu_code")
    source_coverage.to_csv(REPORTS_DIR / "benchmark_coverage_by_source_currency.csv", index=False)
    print("\n2. COVERAGE BY SOURCE CURRENCY")
    print(source_coverage.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    # 3. Coverage by mapped destination currency. Ambiguous/unmapped currencies
    # are intentionally excluded from this currency-specific table.
    mapped_destinations = data.loc[
        data["currency_mapping_status"].eq("mapped") & data["destination_currency"].notna()
    ]
    destination_coverage = coverage_table(mapped_destinations, "destination_currency")
    destination_coverage.to_csv(
        REPORTS_DIR / "benchmark_coverage_by_destination_currency.csv", index=False
    )
    print("\n3. COVERAGE BY MAPPED DESTINATION CURRENCY")
    print(destination_coverage.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    # 4. Corridor coverage, including the requested high-count and low-rate views.
    corridor_coverage = coverage_table(data, "corridor")
    corridor_coverage.to_csv(REPORTS_DIR / "benchmark_coverage_by_corridor.csv", index=False)
    top_corridors = corridor_coverage.sort_values(
        ["benchmarkable_observations", "total_observations", "corridor"],
        ascending=[False, False, True],
    ).head(20)
    low_corridors = (
        corridor_coverage.loc[corridor_coverage["total_observations"].ge(50)]
        .sort_values(
            ["benchmark_availability_pct", "total_observations", "corridor"],
            ascending=[True, False, True],
        )
        .head(20)
    )
    top_corridors.to_csv(REPORTS_DIR / "benchmark_top20_corridors_by_count.csv", index=False)
    low_corridors.to_csv(REPORTS_DIR / "benchmark_low20_corridors_min50.csv", index=False)
    print("\n4. TOP 20 CORRIDORS BY BENCHMARKABLE OBSERVATIONS")
    print(top_corridors.to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    print("\n4. LOWEST 20 CORRIDORS BY AVAILABILITY (AT LEAST 50 OBSERVATIONS)")
    print(low_corridors.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    # 5. Use RPW's actual period field. It is not interchangeable with the
    # calendar quarter derived from date for every observation.
    period_sort = data["period"].str.extract(r"^(\d{4})_(\d)Q$")
    if period_sort.isna().any(axis=None):
        raise ValueError("Unexpected RPW period label; expected YYYY_nQ")
    data["_period_year"] = period_sort[0].astype(int)
    data["_period_quarter"] = period_sort[1].astype(int)
    period_coverage = (
        data.groupby("period", as_index=False)
        .agg(
            total_observations=("id", "size"),
            benchmarkable_observations=("benchmark_available", "sum"),
        )
    )
    period_coverage["benchmark_availability_pct"] = (
        period_coverage["benchmarkable_observations"]
        / period_coverage["total_observations"]
        * 100
    )
    order = (
        data[["period", "_period_year", "_period_quarter"]]
        .drop_duplicates()
        .sort_values(["_period_year", "_period_quarter"])["period"]
    )
    period_coverage["period"] = pd.Categorical(
        period_coverage["period"], categories=order.tolist(), ordered=True
    )
    period_coverage = period_coverage.sort_values("period").reset_index(drop=True)
    period_coverage["period"] = period_coverage["period"].astype(str)
    period_coverage.to_csv(REPORTS_DIR / "benchmark_coverage_by_period.csv", index=False)
    print("\n5. COVERAGE BY RPW PERIOD")
    print(period_coverage.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    # 6. Provider table for providers meeting the minimum sample size.
    provider_coverage = coverage_table(data, "firm")
    eligible_providers = provider_coverage.loc[
        provider_coverage["total_observations"].ge(100)
    ].copy()
    top_providers = eligible_providers.sort_values(
        ["benchmarkable_observations", "total_observations", "firm"],
        ascending=[False, False, True],
    ).head(20)
    eligible_providers.to_csv(REPORTS_DIR / "benchmark_coverage_by_provider_min100.csv", index=False)
    top_providers.to_csv(REPORTS_DIR / "benchmark_top20_providers_by_count.csv", index=False)
    print("\n6. TOP 20 PROVIDERS BY BENCHMARKABLE OBSERVATIONS (AT LEAST 100 TOTAL)")
    print(top_providers.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    # 7. Unavailable reasons, with percentages using both unavailable and total
    # observations as denominators for easy interpretation.
    unavailable_reasons = (
        data.loc[~available_mask, "benchmark_unavailable_reason"]
        .value_counts(dropna=False)
        .rename_axis("benchmark_unavailable_reason")
        .rename("count")
        .reset_index()
    )
    unavailable_reasons["pct_of_unavailable"] = (
        unavailable_reasons["count"] / unavailable_count * 100
    )
    unavailable_reasons["pct_of_all_observations"] = (
        unavailable_reasons["count"] / len(data) * 100
    )
    unavailable_reasons.to_csv(REPORTS_DIR / "benchmark_unavailable_reasons.csv", index=False)
    print("\n7. UNAVAILABLE REASONS")
    print(unavailable_reasons.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    # 8. Descriptive comparison only; no hypothesis testing is performed.
    comparison_rows = []
    differences = []
    for metric in ["cc1_total_cost_pct", "cc1_fx_margin"]:
        benchmark_stats = describe_metric(data.loc[available_mask, metric])
        full_stats = describe_metric(data[metric])
        comparison_rows.extend(
            [
                {"metric": metric, "sample": "benchmark_available", **benchmark_stats},
                {"metric": metric, "sample": "full_sample", **full_stats},
            ]
        )
        differences.append(
            {
                "metric": metric,
                "mean_difference_benchmarked_minus_full": (
                    benchmark_stats["mean"] - full_stats["mean"]
                ),
                "median_difference_benchmarked_minus_full": (
                    benchmark_stats["median"] - full_stats["median"]
                ),
            }
        )
    comparison = pd.DataFrame(comparison_rows)
    differences = pd.DataFrame(differences)
    comparison.to_csv(REPORTS_DIR / "benchmark_vs_full_sample_metrics.csv", index=False)
    differences.to_csv(REPORTS_DIR / "benchmark_vs_full_sample_differences.csv", index=False)
    print("\n8. BENCHMARKED VS FULL SAMPLE: DESCRIPTIVE STATISTICS")
    print(comparison.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\nMean and median differences (benchmarked minus full sample):")
    print(differences.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # 9. Corridor-level benchmark coverage.
    full_corridors = data["corridor"].nunique()
    benchmarked_corridors = data.loc[available_mask, "corridor"].nunique()
    corridor_summary = pd.DataFrame(
        [
            {
                "unique_corridors_full_sample": full_corridors,
                "unique_corridors_with_benchmark": benchmarked_corridors,
                "pct_corridors_with_benchmark": benchmarked_corridors / full_corridors * 100,
            }
        ]
    )
    corridor_summary.to_csv(REPORTS_DIR / "benchmark_corridor_coverage_summary.csv", index=False)
    print("\n9. BENCHMARKED CORRIDOR COVERAGE")
    print(corridor_summary.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    # 10. Extremes and largest absolute provider-vs-BIS spread observations.
    benchmarked = data.loc[available_mask].copy()
    spread = pd.to_numeric(benchmarked["provider_vs_bis_spread_pct"], errors="coerce")
    extremes = pd.DataFrame(
        [
            {
                "metric": "bis_corridor_rate",
                "minimum": benchmarked["bis_corridor_rate"].min(),
                "maximum": benchmarked["bis_corridor_rate"].max(),
            },
            {
                "metric": "provider_vs_bis_spread_pct",
                "minimum": spread.min(),
                "maximum": spread.max(),
            },
        ]
    )
    extreme_columns = [
        "date",
        "source_name",
        "destination_name",
        "firm",
        "corridor",
        "cc1_lcu_code",
        "destination_currency",
        "cc1_lcu_fx_rate",
        "bis_corridor_rate",
        "provider_vs_bis_spread_pct",
        "cc1_fx_margin",
        "cc1_total_cost_pct",
    ]
    largest_spreads = benchmarked.assign(
        _absolute_spread=spread.abs()
    ).sort_values("_absolute_spread", ascending=False)[extreme_columns].head(10)
    extremes.to_csv(REPORTS_DIR / "benchmark_extreme_values.csv", index=False)
    largest_spreads.to_csv(REPORTS_DIR / "benchmark_top10_absolute_provider_spreads.csv", index=False)
    print("\n10. EXTREME VALUES WITHIN BENCHMARK-AVAILABLE OBSERVATIONS")
    print(extremes.to_string(index=False, float_format=lambda value: f"{value:.6f}"))
    print("\n10. TOP 10 LARGEST ABSOLUTE PROVIDER-VS-BIS SPREADS")
    print(largest_spreads.to_string(index=False, float_format=lambda value: f"{value:.6f}"))

    # 11. Invariants for the benchmark dataset.
    actual_min = data["date"].min()
    actual_max = data["date"].max()
    checks = {
        "row count": len(data) == EXPECTED_ROWS,
        "zero duplicate IDs": data["id"].duplicated().sum() == 0,
        "28 benchmark columns": len(benchmark_columns) == 28,
        "expected benchmark column names/order": benchmark_columns == EXPECTED_COLUMNS,
        "date range": actual_min == EXPECTED_DATE_MIN and actual_max == EXPECTED_DATE_MAX,
        "benchmark-available count": available_count == EXPECTED_AVAILABLE,
        "benchmark-unavailable count": unavailable_count == EXPECTED_UNAVAILABLE,
    }
    validation = pd.DataFrame(
        [{"check": label, "passed": passed} for label, passed in checks.items()]
    )
    validation.to_csv(REPORTS_DIR / "benchmark_validation_checks.csv", index=False)
    print("\n11. VALIDATION")
    print(f"Rows: {len(data):,} (expected {EXPECTED_ROWS:,})")
    print(f"Duplicate IDs: {data['id'].duplicated().sum()}")
    print(f"Columns in benchmark file: {len(benchmark_columns)}")
    print(f"Date range: {actual_min} to {actual_max}")
    print(f"Benchmark available: {available_count:,} (expected {EXPECTED_AVAILABLE:,})")
    print(f"Benchmark unavailable: {unavailable_count:,} (expected {EXPECTED_UNAVAILABLE:,})")
    print(validation.to_string(index=False))
    if not all(checks.values()):
        failed = [label for label, passed in checks.items() if not passed]
        raise ValueError("Benchmark validation failed: " + ", ".join(failed))

    print(f"\nDiagnostic tables saved under: {REPORTS_DIR}")


if __name__ == "__main__":
    main()
