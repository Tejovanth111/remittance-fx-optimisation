"""Compare orientation-normalized BIS rates with RPW interbank quotes."""

from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_bis_fx_benchmark_cc1.csv"
ORIENTATION_FILE = PROJECT_ROOT / "reports" / "rpw_bis_quote_orientation.csv"
OUTPUT_FILE = PROJECT_ROOT / "reports" / "normalized_bis_validation.csv"
MATCH_CLASSES = ["direct_match", "inverse_match"]
PERCENTILES = [0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
TOLERANCES = [0.5, 1, 2, 5, 10]


def difference_statistics(values: pd.Series) -> dict[str, float | int]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    quantiles = values.quantile(PERCENTILES)
    return {
        "count": int(values.count()),
        "mean": values.mean(),
        "median": values.median(),
        "std": values.std(),
        "min": values.min(),
        "25%": quantiles.loc[0.25],
        "50%": quantiles.loc[0.50],
        "75%": quantiles.loc[0.75],
        "90%": quantiles.loc[0.90],
        "95%": quantiles.loc[0.95],
        "99%": quantiles.loc[0.99],
        "max": values.max(),
    }


def tolerance_summary(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, group in [("all_validated", data), *[(name, data.loc[data["quote_orientation"].eq(name)]) for name in MATCH_CLASSES]]:
        for threshold in TOLERANCES:
            rows.append(
                {
                    "sample": label,
                    "threshold_pct": threshold,
                    "observations_within_pct": int(group["difference_pct"].le(threshold).sum()),
                    "percentage_within_pct": group["difference_pct"].le(threshold).mean() * 100,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    benchmark = pd.read_csv(BENCHMARK_FILE, low_memory=False)
    orientation = pd.read_csv(ORIENTATION_FILE, low_memory=False)

    if benchmark["id"].duplicated().any() or orientation["id"].duplicated().any():
        raise ValueError("Observation IDs must be unique in both input files")

    selected = orientation.loc[orientation["quote_orientation"].isin(MATCH_CLASSES)].copy()
    benchmark_fields = [
        "id",
        "firm",
        "corridor",
        "cc1_fx_margin",
    ]
    selected = selected.merge(
        benchmark[benchmark_fields],
        on="id",
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not selected["_merge"].eq("both").all():
        raise ValueError("Some direct/inverse orientation IDs are missing from the benchmark file")
    selected = selected.drop(columns="_merge")

    # The orientation report already calculated both rates. Select the one
    # indicated by its classification; do not write to the stored benchmark.
    selected["normalized_bis_rate"] = np.where(
        selected["quote_orientation"].eq("direct_match"),
        selected["bis_direct"],
        selected["bis_inverse"],
    )
    selected["inter_lcu_bank_fx"] = pd.to_numeric(
        selected["inter_lcu_bank_fx"], errors="coerce"
    )
    selected["difference"] = selected["normalized_bis_rate"] - selected["inter_lcu_bank_fx"]
    selected["absolute_difference"] = selected["difference"].abs()
    denominator_valid = selected["inter_lcu_bank_fx"].notna() & selected[
        "inter_lcu_bank_fx"
    ].ne(0)
    selected["difference_pct"] = np.nan
    selected.loc[denominator_valid, "difference_pct"] = (
        selected.loc[denominator_valid, "absolute_difference"]
        / selected.loc[denominator_valid, "inter_lcu_bank_fx"].abs()
        * 100
    )

    output_columns = [
        "id",
        "date",
        "source_code",
        "destination_code",
        "source_currency",
        "destination_currency",
        "inter_lcu_bank_fx",
        "normalized_bis_rate",
        "difference",
        "absolute_difference",
        "difference_pct",
        "quote_orientation",
        "cc1_fx_margin",
    ]
    result = selected.copy()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result[output_columns].to_csv(OUTPUT_FILE, index=False)

    # 1–2. Observation totals and orientation counts.
    orientation_counts = result["quote_orientation"].value_counts().reindex(MATCH_CLASSES, fill_value=0)
    print("1. TOTAL OBSERVATIONS VALIDATED:", len(result))
    print("2. DIRECT VS INVERSE COUNTS:")
    print(orientation_counts.to_string())

    # 3. Overall descriptive statistics.
    print("\n3. DIFFERENCE_PCT DESCRIPTIVE STATISTICS")
    overall_stats = pd.DataFrame([difference_statistics(result["difference_pct"])])
    print(overall_stats.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # 4–5. Overall and class-specific percentages within the requested bands.
    tolerance_results = tolerance_summary(result)
    print("\n4. PERCENTAGE WITHIN ABSOLUTE DIFFERENCE THRESHOLDS")
    print(
        tolerance_results.loc[tolerance_results["sample"].eq("all_validated")]
        .to_string(index=False, float_format=lambda value: f"{value:.2f}")
    )
    print("\n5. RESULTS SEPARATELY FOR DIRECT_MATCH AND INVERSE_MATCH")
    for label in MATCH_CLASSES:
        group = result.loc[result["quote_orientation"].eq(label)]
        print(f"\n{label}: {len(group)} observations")
        print(
            pd.DataFrame([difference_statistics(group["difference_pct"])])
            .to_string(index=False, float_format=lambda value: f"{value:.4f}")
        )
    print("\nClass-specific tolerance percentages:")
    print(
        tolerance_results.loc[~tolerance_results["sample"].eq("all_validated")]
        .to_string(index=False, float_format=lambda value: f"{value:.2f}")
    )

    # 6. Largest differences.
    top_columns = [
        "id",
        "date",
        "corridor",
        "firm",
        "source_currency",
        "destination_currency",
        "inter_lcu_bank_fx",
        "normalized_bis_rate",
        "difference_pct",
        "quote_orientation",
    ]
    largest_differences = result.nlargest(20, "difference_pct")[top_columns]
    print("\n6. TOP 20 LARGEST DIFFERENCE_PCT OBSERVATIONS")
    print(largest_differences.to_string(index=False, float_format=lambda value: f"{value:.6f}"))

    # 7. Corridor summaries for corridors with at least 20 validated records.
    corridor_summary = (
        result.groupby("corridor")
        .agg(
            observations=("id", "size"),
            median_difference_pct=("difference_pct", "median"),
            mean_difference_pct=("difference_pct", "mean"),
            p95_difference_pct=("difference_pct", lambda values: values.quantile(0.95)),
        )
        .reset_index()
    )
    corridor_summary = corridor_summary.loc[corridor_summary["observations"].ge(20)].sort_values(
        "median_difference_pct", ascending=False
    )
    print("\n7. CORRIDORS WITH AT LEAST 20 VALIDATED OBSERVATIONS")
    print(corridor_summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # 8. Currency summaries, using the same descriptive measures by currency.
    for key, title in [
        ("source_currency", "SOURCE CURRENCY"),
        ("destination_currency", "DESTINATION CURRENCY"),
    ]:
        currency_summary = (
            result.groupby(key)
            .agg(
                observations=("id", "size"),
                median_difference_pct=("difference_pct", "median"),
                mean_difference_pct=("difference_pct", "mean"),
                p95_difference_pct=("difference_pct", lambda values: values.quantile(0.95)),
            )
            .reset_index()
            .sort_values("observations", ascending=False)
        )
        print(f"\n8. AGGREGATE BY {title}")
        print(currency_summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # 9. The requested date/corridor examples. Other orientation classes are
    # inspected only to explain exclusion; they are not added to the output.
    checks = [
        ("GBR", "IND", "2016-05-10"),
        ("CHL", "PER", "2019-09-16"),
        ("THA", "IDN", "2017-04-24"),
    ]
    print("\n9. EXPLICIT VALIDATION EXAMPLES")
    for source, destination, date in checks:
        audit_case = orientation.loc[
            orientation["source_code"].eq(source)
            & orientation["destination_code"].eq(destination)
            & orientation["date"].eq(date)
        ]
        included_case = result.loc[
            result["source_code"].eq(source)
            & result["destination_code"].eq(destination)
            & result["date"].eq(date)
        ]
        print(f"\n{source}→{destination} {date}")
        case_counts = audit_case["quote_orientation"].value_counts().to_dict()
        print("Orientation classifications:", case_counts)
        if included_case.empty:
            if case_counts and set(case_counts) == {"neither_match"}:
                print("Excluded because these observations were classified neither_match.")
            else:
                print("Excluded: no direct_match or inverse_match observations for this exact date/corridor.")
        else:
            print(
                included_case[
                    [
                        "id",
                        "inter_lcu_bank_fx",
                        "normalized_bis_rate",
                        "difference_pct",
                        "quote_orientation",
                    ]
                ].to_string(index=False, float_format=lambda value: f"{value:.6f}")
            )

    # The row-level output should contain only the two selected classes.
    read_back = pd.read_csv(OUTPUT_FILE)
    if len(read_back) != len(result) or not set(read_back["quote_orientation"]).issubset(MATCH_CLASSES):
        raise ValueError("Normalized validation output failed its read-back checks")
    print(f"\nSaved {len(result)} validated rows to: {OUTPUT_FILE}")
    print("Read-back shape:", read_back.shape)


if __name__ == "__main__":
    main()
