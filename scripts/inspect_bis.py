import re

import pandas as pd


file_path = "data/external/bis/WS_XRU_csv_col.csv"
requested_currencies = ["USD", "GBP", "INR", "PHP", "PKR", "AED", "ZAR", "AUD", "EUR", "TRY"]
requested_dates = ["2024-01-02", "2024-01-03", "2024-01-04"]

# Read only the header first, then separate metadata fields from observation periods.
columns = pd.read_csv(file_path, nrows=0).columns.tolist()
observation_pattern = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?|-Q[1-4])?$")
observation_columns = [
    column for column in columns
    if observation_pattern.match(column)
]
metadata_columns = [
    column for column in columns
    if column not in observation_columns
]
available_dates = [date for date in requested_dates if date in columns]
missing_dates = [date for date in requested_dates if date not in columns]

print("Total columns:", len(columns))
print("Observation columns:", len(observation_columns))
print("Metadata columns:")
print(metadata_columns)

# Load metadata plus only the requested observation dates, not the full wide file.
columns_to_read = metadata_columns + available_dates
data = pd.read_csv(file_path, usecols=columns_to_read)
metadata = data[metadata_columns]

print("\nFrequency values:")
print(metadata["FREQ"].value_counts(dropna=False))

daily = metadata.loc[metadata["FREQ"] == "D", metadata_columns]

print("\nDaily series count:", len(daily))
print("Daily series metadata:")
print(daily.to_string(index=False))

daily_selected = data.loc[
    (data["FREQ"] == "D") & data["CURRENCY"].isin(requested_currencies)
]

print("\nRequested currencies:", ", ".join(requested_currencies))
if missing_dates:
    print("Requested date columns not present:", ", ".join(missing_dates))

observation_rows = []
for _, series in daily_selected.iterrows():
    for date in available_dates:
        observation_rows.append(
            {
                "REF_AREA": series["REF_AREA"],
                "CURRENCY": series["CURRENCY"],
                "Currency": series["Currency"],
                "date": date,
                "value": series[date],
            }
        )

observations = pd.DataFrame(
    observation_rows,
    columns=["REF_AREA", "CURRENCY", "Currency", "date", "value"],
)

print("\nSelected daily observations:")
print(observations.to_string(index=False))

# Validation calculation only: cross the BIS USD-based GBP and INR observations.
print("\nBIS cross-rate validation: GBP to INR")
cross_rate_rows = []
for date in available_dates:
    gbp_rows = daily_selected.loc[daily_selected["CURRENCY"] == "GBP"]
    inr_rows = daily_selected.loc[daily_selected["CURRENCY"] == "INR"]

    if len(gbp_rows) != 1 or len(inr_rows) != 1:
        print(f"{date}: unable to calculate; expected one GBP and one INR daily series")
        continue

    gbp_per_usd = gbp_rows.iloc[0][date]
    inr_per_usd = inr_rows.iloc[0][date]

    if pd.isna(gbp_per_usd) or pd.isna(inr_per_usd):
        print(f"{date}: unable to calculate; a BIS observation is missing")
        continue

    cross_rate_rows.append(
        {
            "date": date,
            "GBP_per_USD": gbp_per_usd,
            "INR_per_USD": inr_per_usd,
            "calculated_GBP_to_INR": inr_per_usd / gbp_per_usd,
        }
    )

cross_rate = pd.DataFrame(
    cross_rate_rows,
    columns=["date", "GBP_per_USD", "INR_per_USD", "calculated_GBP_to_INR"],
)
print(cross_rate.to_string(index=False))

# Inspect RPW only on the same exact dates; do not substitute nearby dates.
rpw_file_path = "data/processed/rpw_clean.csv"
rpw_columns = [
    "date",
    "firm",
    "source_code",
    "destination_code",
    "cc1_lcu_amount",
    "cc1_lcu_code",
    "cc1_lcu_fx_rate",
    "inter_lcu_bank_fx",
    "cc1_fx_margin",
]
rpw = pd.read_csv(rpw_file_path, usecols=rpw_columns, dtype={"date": "string"})
rpw_gbr_ind = rpw.loc[
    (rpw["source_code"] == "GBR")
    & (rpw["destination_code"] == "IND")
    & rpw["date"].isin(requested_dates),
    [
        "date",
        "firm",
        "cc1_lcu_amount",
        "cc1_lcu_code",
        "cc1_lcu_fx_rate",
        "inter_lcu_bank_fx",
        "cc1_fx_margin",
    ],
]

print("\nRPW GBR to IND observations on the exact BIS dates:")
if rpw_gbr_ind.empty:
    print("No RPW GBR to IND observations exist on the requested exact dates.")
else:
    print(rpw_gbr_ind.head(20).to_string(index=False))

# Find the first ten qualifying RPW GBR-to-IND rows in the CSV's existing order.
rpw_qualifying = rpw.loc[
    (rpw["source_code"] == "GBR")
    & (rpw["destination_code"] == "IND")
    & rpw["date"].notna()
    & rpw["cc1_lcu_fx_rate"].notna()
    & rpw["inter_lcu_bank_fx"].notna()
].head(10)

rpw_display_columns = [
    "date",
    "firm",
    "cc1_lcu_amount",
    "cc1_lcu_code",
    "cc1_lcu_fx_rate",
    "inter_lcu_bank_fx",
    "cc1_fx_margin",
]

print("\nFirst 10 qualifying RPW GBR to IND observations:")
if rpw_qualifying.empty:
    print("No qualifying RPW observations were found.")
else:
    print(rpw_qualifying[rpw_display_columns].to_string(index=False))

    rpw_dates = rpw_qualifying["date"].drop_duplicates().tolist()
    daily_date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    exact_bis_dates = [
        date for date in rpw_dates
        if daily_date_pattern.match(date) and date in columns
    ]
    unavailable_bis_dates = [
        date for date in rpw_dates
        if date not in exact_bis_dates
    ]

    print("\nExact RPW dates available as BIS daily columns:")
    print(exact_bis_dates if exact_bis_dates else "None")
    if unavailable_bis_dates:
        print("RPW dates without an exact BIS daily column:", unavailable_bis_dates)

    comparison_rows = []
    if exact_bis_dates:
        bis_date_data = pd.read_csv(
            file_path,
            usecols=metadata_columns + exact_bis_dates,
        )
        gbp_series = bis_date_data.loc[
            (bis_date_data["FREQ"] == "D")
            & (bis_date_data["REF_AREA"] == "GB")
            & (bis_date_data["CURRENCY"] == "GBP")
        ]
        inr_series = bis_date_data.loc[
            (bis_date_data["FREQ"] == "D")
            & (bis_date_data["REF_AREA"] == "IN")
            & (bis_date_data["CURRENCY"] == "INR")
        ]

        for _, rpw_row in rpw_qualifying.iterrows():
            date = rpw_row["date"]
            gbp_per_usd = float("nan")
            inr_per_usd = float("nan")
            bis_cross_rate = float("nan")

            if date in exact_bis_dates and len(gbp_series) == 1 and len(inr_series) == 1:
                gbp_per_usd = gbp_series.iloc[0][date]
                inr_per_usd = inr_series.iloc[0][date]
                if pd.notna(gbp_per_usd) and pd.notna(inr_per_usd):
                    bis_cross_rate = inr_per_usd / gbp_per_usd

            comparison_rows.append(
                {
                    **{column: rpw_row[column] for column in rpw_display_columns},
                    "GBP_per_USD": gbp_per_usd,
                    "INR_per_USD": inr_per_usd,
                    "GBP_to_INR_BIS": bis_cross_rate,
                }
            )
    else:
        for _, rpw_row in rpw_qualifying.iterrows():
            comparison_rows.append(
                {
                    **{column: rpw_row[column] for column in rpw_display_columns},
                    "GBP_per_USD": float("nan"),
                    "INR_per_USD": float("nan"),
                    "GBP_to_INR_BIS": float("nan"),
                }
            )

    comparison = pd.DataFrame(comparison_rows)
    print("\nRPW and exact-date BIS comparison:")
    print(comparison.to_string(index=False))
