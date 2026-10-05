"""Build an exact-date RPW CC1 corridor benchmark from BIS USD rates."""

from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RPW_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_clean.csv"
MAPPING_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_destination_currency_mapping.csv"
BIS_FILE = PROJECT_ROOT / "data" / "processed" / "bis_daily_fx.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_bis_fx_benchmark_cc1.csv"

RPW_COLUMNS = [
    "id",
    "date",
    "source_code",
    "source_name",
    "destination_code",
    "destination_name",
    "firm",
    "cc1_lcu_code",
    "cc1_lcu_amount",
    "cc1_lcu_fee",
    "cc1_lcu_fx_rate",
    "cc1_fx_margin",
    "cc1_total_cost_pct",
    "inter_lcu_bank_fx",
    "corridor",
]


def build_bis_rate_lookup(bis: pd.DataFrame) -> pd.DataFrame:
    """Return one date/currency row, retaining only unambiguous daily rates."""
    rates = bis.copy()
    rates["rate_per_usd"] = pd.to_numeric(rates["rate_per_usd"], errors="coerce")
    lookup = (
        rates.groupby(["date", "currency"], as_index=False)
        .agg(
            bis_series_count=("rate_per_usd", "size"),
            distinct_rate_count=("rate_per_usd", "nunique"),
            rate_candidate=("rate_per_usd", "first"),
        )
    )
    lookup["rate_ambiguous"] = lookup["distinct_rate_count"].gt(1)
    lookup.loc[lookup["distinct_rate_count"].ne(1), "rate_candidate"] = np.nan
    return lookup


def main() -> None:
    rpw = pd.read_csv(RPW_FILE, usecols=RPW_COLUMNS, dtype={"date": "string"})
    mapping = pd.read_csv(
        MAPPING_FILE,
        usecols=[
            "id",
            "date",
            "destination_code",
            "destination_currency",
            "currency_candidates",
            "currency_mapping_status",
        ],
        dtype={"date": "string", "destination_currency": "string"},
    )
    bis = pd.read_csv(
        BIS_FILE,
        usecols=["date", "currency", "rate_per_usd"],
        dtype={"date": "string", "currency": "string"},
    )

    # The mapping must be exactly one row per RPW observation and agree with
    # its date and destination country before it is attached by id.
    if rpw["id"].duplicated().any():
        raise ValueError("RPW contains duplicate IDs; cannot make a one-row-per-observation output")
    if mapping["id"].duplicated().any():
        raise ValueError("Destination mapping contains duplicate IDs")
    if len(mapping) != len(rpw) or set(mapping["id"]) != set(rpw["id"]):
        raise ValueError("Destination mapping IDs do not match the RPW observation IDs")

    mapping_check = rpw[["id", "date", "destination_code"]].merge(
        mapping[["id", "date", "destination_code"]],
        on="id",
        suffixes=("_rpw", "_mapping"),
        validate="one_to_one",
    )
    key_mismatch = (
        mapping_check["date_rpw"].ne(mapping_check["date_mapping"])
        | mapping_check["destination_code_rpw"].ne(mapping_check["destination_code_mapping"])
    )
    if key_mismatch.any():
        raise ValueError("Destination mapping date/country keys do not match RPW for one or more IDs")

    mapping_fields = mapping.drop(columns=["date", "destination_code"])
    output = rpw.merge(mapping_fields, on="id", how="left", validate="one_to_one")
    output["_join_date"] = output["date"]
    output["_source_currency"] = output["cc1_lcu_code"].str.strip().str.upper()
    output["_destination_currency"] = output["destination_currency"].str.strip().str.upper()

    # A currency can have several BIS reference-area series. Use the rate only
    # when all nonmissing series for that date/currency agree on one value.
    bis["currency"] = bis["currency"].str.strip().str.upper()
    bis_lookup = build_bis_rate_lookup(bis)

    source_lookup = bis_lookup.rename(
        columns={
            "currency": "_source_currency",
            "rate_candidate": "source_bis_rate_per_usd",
            "rate_ambiguous": "source_bis_rate_ambiguous",
            "bis_series_count": "source_bis_series_count",
        }
    )
    output = output.merge(
        source_lookup[
            [
                "date",
                "_source_currency",
                "source_bis_rate_per_usd",
                "source_bis_rate_ambiguous",
                "source_bis_series_count",
            ]
        ].rename(columns={"date": "_source_bis_date"}),
        left_on=["_join_date", "_source_currency"],
        right_on=["_source_bis_date", "_source_currency"],
        how="left",
        validate="many_to_one",
    )

    destination_lookup = bis_lookup.rename(
        columns={
            "currency": "_destination_currency",
            "rate_candidate": "destination_bis_rate_per_usd",
            "rate_ambiguous": "destination_bis_rate_ambiguous",
            "bis_series_count": "destination_bis_series_count",
        }
    )
    output = output.merge(
        destination_lookup[
            [
                "date",
                "_destination_currency",
                "destination_bis_rate_per_usd",
                "destination_bis_rate_ambiguous",
                "destination_bis_series_count",
            ]
        ].rename(columns={"date": "_destination_bis_date"}),
        left_on=["_join_date", "_destination_currency"],
        right_on=["_destination_bis_date", "_destination_currency"],
        how="left",
        validate="many_to_one",
    )

    for column in ["source_bis_rate_per_usd", "destination_bis_rate_per_usd"]:
        output[column] = pd.to_numeric(output[column], errors="coerce")
    for column in ["source_bis_series_count", "destination_bis_series_count"]:
        output[column] = output[column].fillna(0).astype("int64")
    for column in ["source_bis_rate_ambiguous", "destination_bis_rate_ambiguous"]:
        output[column] = output[column].fillna(False).astype(bool)

    source_rate_valid = output["source_bis_rate_per_usd"].notna() & output[
        "source_bis_rate_per_usd"
    ].ne(0)
    destination_rate_valid = output["destination_bis_rate_per_usd"].notna() & output[
        "destination_bis_rate_per_usd"
    ].ne(0)
    mapping_is_valid = output["currency_mapping_status"].eq("mapped") & output[
        "destination_currency"
    ].notna()
    output["benchmark_available"] = (
        mapping_is_valid & source_rate_valid & destination_rate_valid
    )

    reason = np.full(len(output), "benchmark_available", dtype=object)
    multiple = output["currency_mapping_status"].eq("multiple_currency_candidates").to_numpy()
    historical = output["currency_mapping_status"].eq("historical_currency_case").to_numpy()
    mapping_missing = (
        output["currency_mapping_status"].eq("unmapped")
        | output["destination_currency"].isna()
        | ~output["currency_mapping_status"].isin(
            ["mapped", "multiple_currency_candidates", "historical_currency_case", "unmapped"]
        )
    ).to_numpy()
    reason[mapping_missing] = "destination_currency_unmapped"
    reason[historical] = "destination_currency_historical_case"
    reason[multiple] = "destination_currency_ambiguous"

    mapping_ok = mapping_is_valid.to_numpy()
    source_bad = ~source_rate_valid.to_numpy()
    destination_bad = ~destination_rate_valid.to_numpy()
    source_ambiguous = output["source_bis_rate_ambiguous"].to_numpy()
    destination_ambiguous = output["destination_bis_rate_ambiguous"].to_numpy()
    rate_checks = mapping_ok

    both_bad = rate_checks & source_bad & destination_bad
    reason[both_bad & source_ambiguous & destination_ambiguous] = "both_bis_rates_ambiguous"
    reason[both_bad & source_ambiguous & ~destination_ambiguous] = (
        "source_bis_rate_ambiguous_and_destination_bis_rate_missing"
    )
    reason[both_bad & ~source_ambiguous & destination_ambiguous] = (
        "source_bis_rate_missing_and_destination_bis_rate_ambiguous"
    )
    reason[both_bad & ~source_ambiguous & ~destination_ambiguous] = "both_bis_rates_missing"
    source_only_bad = rate_checks & source_bad & ~destination_bad
    destination_only_bad = rate_checks & ~source_bad & destination_bad
    reason[source_only_bad & source_ambiguous] = "source_bis_rate_ambiguous"
    reason[source_only_bad & ~source_ambiguous] = "source_bis_rate_missing"
    reason[destination_only_bad & destination_ambiguous] = "destination_bis_rate_ambiguous"
    reason[destination_only_bad & ~destination_ambiguous] = "destination_bis_rate_missing"
    output["benchmark_unavailable_reason"] = reason

    output["bis_corridor_rate"] = np.nan
    output.loc[output["benchmark_available"], "bis_corridor_rate"] = (
        output.loc[output["benchmark_available"], "destination_bis_rate_per_usd"]
        / output.loc[output["benchmark_available"], "source_bis_rate_per_usd"]
    )

    interbank = pd.to_numeric(output["inter_lcu_bank_fx"], errors="coerce")
    interbank_valid = interbank.notna() & interbank.ne(0)
    interbank_comparison_valid = output["benchmark_available"] & interbank_valid
    output["bis_minus_rpw_interbank"] = np.nan
    output.loc[interbank_comparison_valid, "bis_minus_rpw_interbank"] = (
        output.loc[interbank_comparison_valid, "bis_corridor_rate"]
        - interbank.loc[interbank_comparison_valid]
    )
    output["bis_vs_rpw_interbank_pct"] = np.nan
    output.loc[interbank_comparison_valid, "bis_vs_rpw_interbank_pct"] = (
        output.loc[interbank_comparison_valid, "bis_minus_rpw_interbank"]
        / interbank.loc[interbank_comparison_valid]
        * 100
    )

    provider_rate = pd.to_numeric(output["cc1_lcu_fx_rate"], errors="coerce")
    provider_comparison_valid = (
        output["benchmark_available"]
        & provider_rate.notna()
        & output["bis_corridor_rate"].ne(0)
    )
    output["provider_vs_bis_spread_pct"] = np.nan
    output.loc[provider_comparison_valid, "provider_vs_bis_spread_pct"] = (
        (
            output.loc[provider_comparison_valid, "bis_corridor_rate"]
            - provider_rate.loc[provider_comparison_valid]
        )
        / output.loc[provider_comparison_valid, "bis_corridor_rate"]
        * 100
    )

    # Retain series counts to make duplicate BIS reference-area coverage
    # visible where an unambiguous date/currency rate could not be selected.
    output_columns = [
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
    result = output[output_columns].copy()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)

    available_count = int(result["benchmark_available"].sum())
    observation_count = len(result)
    availability_pct = available_count / observation_count * 100 if observation_count else 0
    print("RPW + BIS CC1 corridor benchmark diagnostic")
    print("Output shape:", result.shape)
    print("Unique RPW observations:", result["id"].nunique())
    print("Benchmarks available:", available_count)
    print("Benchmarks unavailable:", int((~result["benchmark_available"]).sum()))
    print(f"Benchmark availability: {availability_pct:.2f}%")
    print("Unavailable benchmark reasons:")
    print(
        result.loc[~result["benchmark_available"], "benchmark_unavailable_reason"]
        .value_counts()
        .sort_index()
        .to_string()
    )
    print("Unique source currencies:", result["cc1_lcu_code"].nunique())
    print("Unique mapped destination currencies:", result["destination_currency"].nunique())
    available = result.loc[result["benchmark_available"]]
    print("Unique benchmarked corridors:", available["corridor"].nunique())
    print("Date range:", result["date"].min(), "to", result["date"].max())

    validation_columns = [
        "firm",
        "cc1_lcu_code",
        "destination_currency",
        "cc1_lcu_fx_rate",
        "inter_lcu_bank_fx",
        "cc1_fx_margin",
        "source_bis_rate_per_usd",
        "destination_bis_rate_per_usd",
        "bis_corridor_rate",
        "bis_minus_rpw_interbank",
        "bis_vs_rpw_interbank_pct",
        "provider_vs_bis_spread_pct",
    ]
    validation_filter = (
        result["source_code"].eq("GBR")
        & result["destination_code"].eq("IND")
        & result["date"].eq("2016-05-10")
    )
    validation = result.loc[validation_filter, validation_columns]
    print("\nExact-date validation: GBR to IND on 2016-05-10")
    if validation.empty:
        print("No exact-date RPW observations found")
    else:
        print(validation.to_string(index=False))

    sbi_validation = validation.loc[validation["firm"].eq("State Bank of India")]
    print("\nState Bank of India validation rows:")
    if sbi_validation.empty:
        print("No State Bank of India row found for the exact corridor/date")
    else:
        print(sbi_validation.to_string(index=False))
        if not np.isclose(
            pd.to_numeric(sbi_validation["bis_corridor_rate"], errors="coerce"),
            96.296923,
            atol=0.00001,
        ).all():
            print("Warning: BIS corridor rate differs from the approximate validation expectation")

    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(f"Benchmark output was not created: {OUTPUT_FILE}")
    read_back = pd.read_csv(OUTPUT_FILE)
    if read_back.shape != result.shape:
        raise ValueError(
            f"Read-back shape {read_back.shape} does not match output shape {result.shape}"
        )
    print("\nGenerated CSV:", OUTPUT_FILE)
    print("Read-back shape:", read_back.shape)
    print("Read-back columns:", read_back.columns.tolist())
    print("Output exists and is readable: True")


if __name__ == "__main__":
    main()
