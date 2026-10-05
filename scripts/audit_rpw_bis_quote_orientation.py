"""Diagnose whether RPW interbank quotes are closer to direct or inverse BIS rates."""

from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_bis_fx_benchmark_cc1.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"
OUTPUT_FILE = REPORTS_DIR / "rpw_bis_quote_orientation.csv"
TOLERANCE_PCT = 1.0
AMBIGUOUS_TIE_TOLERANCE_PP = 1e-12


def crosstab_with_row_percentages(data: pd.DataFrame, key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    counts = pd.crosstab(data[key], data["quote_orientation"], dropna=False)
    for label in ["direct_match", "inverse_match", "neither_match", "ambiguous"]:
        if label not in counts.columns:
            counts[label] = 0
    counts = counts[["direct_match", "inverse_match", "neither_match", "ambiguous"]]
    percentages = counts.div(counts.sum(axis=1).replace(0, np.nan), axis=0) * 100
    return counts, percentages


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    benchmark = pd.read_csv(BENCHMARK_FILE, low_memory=False)
    data = benchmark.loc[benchmark["benchmark_available"].eq(True)].copy()
    data["source_currency"] = data["cc1_lcu_code"]

    for column in [
        "source_bis_rate_per_usd",
        "destination_bis_rate_per_usd",
        "inter_lcu_bank_fx",
        "cc1_fx_margin",
    ]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    # Recompute both orientations from the recorded BIS components. The stored
    # bis_corridor_rate is not changed or used to assign the classification.
    data["bis_direct"] = (
        data["destination_bis_rate_per_usd"] / data["source_bis_rate_per_usd"]
    )
    data["bis_inverse"] = (
        data["source_bis_rate_per_usd"] / data["destination_bis_rate_per_usd"]
    )
    interbank_valid = data["inter_lcu_bank_fx"].notna() & data["inter_lcu_bank_fx"].ne(0)
    data["direct_difference_pct"] = np.nan
    data["inverse_difference_pct"] = np.nan
    data.loc[interbank_valid, "direct_difference_pct"] = (
        (data.loc[interbank_valid, "bis_direct"] - data.loc[interbank_valid, "inter_lcu_bank_fx"]).abs()
        / data.loc[interbank_valid, "inter_lcu_bank_fx"].abs()
        * 100
    )
    data.loc[interbank_valid, "inverse_difference_pct"] = (
        (data.loc[interbank_valid, "bis_inverse"] - data.loc[interbank_valid, "inter_lcu_bank_fx"]).abs()
        / data.loc[interbank_valid, "inter_lcu_bank_fx"].abs()
        * 100
    )

    direct_within_tolerance = data["direct_difference_pct"].le(TOLERANCE_PCT)
    inverse_within_tolerance = data["inverse_difference_pct"].le(TOLERANCE_PCT)
    both_within_tolerance = direct_within_tolerance & inverse_within_tolerance
    tied = np.isclose(
        data["direct_difference_pct"].fillna(np.inf),
        data["inverse_difference_pct"].fillna(-np.inf),
        rtol=0,
        atol=AMBIGUOUS_TIE_TOLERANCE_PP,
    )

    data["quote_orientation"] = "neither_match"
    data.loc[
        direct_within_tolerance
        & data["direct_difference_pct"].lt(data["inverse_difference_pct"]),
        "quote_orientation",
    ] = "direct_match"
    data.loc[
        inverse_within_tolerance
        & data["inverse_difference_pct"].lt(data["direct_difference_pct"]),
        "quote_orientation",
    ] = "inverse_match"
    data.loc[both_within_tolerance & tied, "quote_orientation"] = "ambiguous"

    output_columns = [
        "id",
        "date",
        "source_code",
        "destination_code",
        "cc1_lcu_code",
        "destination_currency",
        "source_bis_rate_per_usd",
        "destination_bis_rate_per_usd",
        "bis_direct",
        "bis_inverse",
        "inter_lcu_bank_fx",
        "direct_difference_pct",
        "inverse_difference_pct",
        "quote_orientation",
    ]
    result = data[output_columns].rename(columns={"cc1_lcu_code": "source_currency"})
    result.to_csv(OUTPUT_FILE, index=False)

    # 1. Overall counts and percentages.
    orientation_order = ["direct_match", "inverse_match", "neither_match", "ambiguous"]
    counts = result["quote_orientation"].value_counts().reindex(orientation_order, fill_value=0)
    summary = pd.DataFrame(
        {
            "quote_orientation": orientation_order,
            "count": [int(counts[label]) for label in orientation_order],
            "percentage": [counts[label] / len(result) * 100 for label in orientation_order],
        }
    )
    print("1. QUOTE ORIENTATION COUNTS (1% diagnostic threshold)")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.2f}"))

    # 2–4. Cross-tabs by source currency, destination currency, and corridor.
    for title, key, filename in [
        ("2. CROSS-TAB BY SOURCE CURRENCY", "source_currency", "rpw_bis_orientation_by_source_currency.csv"),
        (
            "3. CROSS-TAB BY DESTINATION CURRENCY",
            "destination_currency",
            "rpw_bis_orientation_by_destination_currency.csv",
        ),
        ("4. CROSS-TAB BY CORRIDOR", "corridor", "rpw_bis_orientation_by_corridor.csv"),
    ]:
        # The output CSV omits names/corridor for compactness; join these keys
        # back from the in-memory benchmark rows in their original order.
        keyed = data[[key, "quote_orientation"]].copy()
        count_table, pct_table = crosstab_with_row_percentages(keyed, key)
        count_table.to_csv(REPORTS_DIR / filename)
        pct_table.to_csv(REPORTS_DIR / filename.replace(".csv", "_row_pct.csv"))
        print(f"\n{title} — counts")
        print(count_table.to_string())
        if key != "corridor":
            print(f"{title} — row percentages")
            print(pct_table.to_string(float_format=lambda value: f"{value:.1f}"))

    # Corridor-level orientation consistency and requested rankings.
    corridor_counts = pd.crosstab(data["corridor"], data["quote_orientation"])
    for label in orientation_order:
        if label not in corridor_counts.columns:
            corridor_counts[label] = 0
    corridor_counts = corridor_counts[orientation_order]
    corridor_counts["observations"] = corridor_counts.sum(axis=1)
    corridor_counts["matched_direct_or_inverse"] = (
        corridor_counts["direct_match"] + corridor_counts["inverse_match"]
    )
    corridor_counts["observed_match_orientations"] = (
        corridor_counts[["direct_match", "inverse_match"]].gt(0).sum(axis=1)
    )
    corridor_counts["orientation_consistency"] = np.select(
        [
            corridor_counts["observed_match_orientations"].eq(2),
            corridor_counts["direct_match"].gt(0),
            corridor_counts["inverse_match"].gt(0),
        ],
        ["both_direct_and_inverse_matches", "direct_matches_only", "inverse_matches_only"],
        default="no_direct_or_inverse_matches",
    )
    corridor_counts = corridor_counts.reset_index()
    inverse_corridors = corridor_counts.loc[corridor_counts["inverse_match"].gt(0)].sort_values(
        ["inverse_match", "observations", "corridor"], ascending=[False, False, True]
    ).head(20)
    neither_corridors = corridor_counts.sort_values(
        ["neither_match", "observations", "corridor"], ascending=[False, False, True]
    ).head(20)
    inverse_corridors.to_csv(REPORTS_DIR / "rpw_bis_top20_inverse_match_corridors.csv", index=False)
    neither_corridors.to_csv(REPORTS_DIR / "rpw_bis_top20_neither_match_corridors.csv", index=False)

    print("\n4. 20 CORRIDORS WITH THE MOST INVERSE MATCHES")
    print(inverse_corridors.to_string(index=False))
    print("\n5. 20 CORRIDORS WITH THE MOST NEITHER_MATCH OBSERVATIONS")
    print(neither_corridors.to_string(index=False))
    print("\nCORRIDOR ORIENTATION CONSISTENCY")
    print(corridor_counts["orientation_consistency"].value_counts().to_string())
    mixed_corridors = corridor_counts.loc[
        corridor_counts["orientation_consistency"].eq("both_direct_and_inverse_matches")
    ]
    print("Corridors with both direct and inverse matches:", len(mixed_corridors))
    if not mixed_corridors.empty:
        print(mixed_corridors.to_string(index=False))

    # 6. Descriptive RPW margin comparison by orientation class.
    margin_summary = (
        data.groupby("quote_orientation", dropna=False)
        .agg(
            observations=("id", "size"),
            margin_count=("cc1_fx_margin", "count"),
            mean_cc1_fx_margin=("cc1_fx_margin", "mean"),
            median_cc1_fx_margin=("cc1_fx_margin", "median"),
            margin_std=("cc1_fx_margin", "std"),
            positive_margin_pct=(
                "cc1_fx_margin",
                lambda values: values.gt(0).sum() / values.count() * 100 if values.count() else np.nan,
            ),
            negative_margin_pct=(
                "cc1_fx_margin",
                lambda values: values.lt(0).sum() / values.count() * 100 if values.count() else np.nan,
            ),
        )
        .reindex(orientation_order)
        .reset_index()
    )
    margin_summary.to_csv(REPORTS_DIR / "rpw_bis_quote_orientation_by_margin.csv", index=False)
    print("\n6. RPW CC1 FX MARGIN BY QUOTE ORIENTATION")
    print(margin_summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    # 7. Exact-date/corridor validation observations.
    validations = [
        ("CHL", "PER", "2019-09-16"),
        ("THA", "IDN", "2017-04-24"),
        ("GBR", "IND", "2016-05-10"),
    ]
    validation_columns = [
        "id",
        "firm",
        "inter_lcu_bank_fx",
        "bis_direct",
        "bis_inverse",
        "direct_difference_pct",
        "inverse_difference_pct",
        "quote_orientation",
    ]
    print("\n7. SPECIFIC VALIDATION CASES")
    for source, destination, date in validations:
        selection = data.loc[
            data["source_code"].eq(source)
            & data["destination_code"].eq(destination)
            & data["date"].eq(date),
            validation_columns,
        ]
        print(f"\n{source} to {destination}, {date} ({len(selection)} observations)")
        if selection.empty:
            print("No benchmark-available observations found")
        else:
            print(selection.to_string(index=False, float_format=lambda value: f"{value:.6f}"))

    print(f"\nDiagnostic row-level CSV: {OUTPUT_FILE}")
    print("Classification tolerance: 1.00% (diagnostic threshold only)")
    print("Ambiguous ties use an absolute difference tolerance of 1e-12 percentage points.")


if __name__ == "__main__":
    main()
