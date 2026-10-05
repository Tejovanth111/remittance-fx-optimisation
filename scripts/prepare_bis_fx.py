from pathlib import Path
import re

import pandas as pd


project_folder = Path(__file__).resolve().parent.parent
rpw_file = project_folder / "data" / "processed" / "rpw_clean.csv"
bis_file = project_folder / "data" / "external" / "bis" / "WS_XRU_csv_col.csv"
output_file = project_folder / "data" / "processed" / "bis_daily_fx.csv"

start_date = "2016-05-09"
end_date = "2025-03-14"

# Read RPW source-side currency codes.
rpw_currencies = pd.read_csv(
    rpw_file,
    usecols=["cc1_lcu_code", "cc2_lcu_code"],
    dtype="string",
)
source_currency_values = pd.concat(
    [rpw_currencies["cc1_lcu_code"], rpw_currencies["cc2_lcu_code"]],
    ignore_index=True,
).dropna()
source_currencies = {
    currency.strip().upper()
    for currency in source_currency_values
    if currency.strip()
}

# Destination currencies come only from dated mappings marked as unambiguous.
destination_mapping_file = (
    project_folder / "data" / "processed" / "rpw_destination_currency_mapping.csv"
)
destination_mapping = pd.read_csv(
    destination_mapping_file,
    usecols=["destination_currency", "currency_mapping_status"],
    dtype="string",
)
destination_currency_values = destination_mapping.loc[
    destination_mapping["currency_mapping_status"].eq("mapped"),
    "destination_currency",
].dropna()
destination_currencies = {
    currency.strip().upper()
    for currency in destination_currency_values
    if currency.strip()
}

required_currencies = source_currencies | destination_currencies

# Read BIS metadata only to identify currencies that have daily series.
bis_metadata_columns = ["FREQ", "REF_AREA", "CURRENCY", "Currency"]
bis_metadata = pd.read_csv(
    bis_file,
    usecols=bis_metadata_columns,
    dtype="string",
)
daily_metadata = bis_metadata.loc[bis_metadata["FREQ"] == "D"]
available_bis_currencies = {
    currency.strip().upper()
    for currency in daily_metadata["CURRENCY"].dropna()
    if currency.strip()
}

available_currencies = required_currencies & available_bis_currencies
unavailable_currencies = sorted(required_currencies - available_bis_currencies)

# BIS stores observations in date-named columns. Keep only daily dates in the
# RPW period and only rows for currencies required by RPW.
bis_columns = pd.read_csv(bis_file, nrows=0).columns.tolist()
date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
observation_dates = [
    column for column in bis_columns
    if date_pattern.fullmatch(column) and start_date <= column <= end_date
]

if available_currencies and observation_dates:
    selected_columns = bis_metadata_columns + observation_dates
    bis_daily = pd.read_csv(bis_file, usecols=selected_columns, dtype={"CURRENCY": "string"})
    bis_daily = bis_daily.loc[
        (bis_daily["FREQ"] == "D")
        & bis_daily["CURRENCY"].str.strip().str.upper().isin(available_currencies)
    ]

    # Keep the BIS quote as units of currency per USD in rate_per_usd.
    # This preserves the source quote convention for later inspection and joins.
    # Cross-rates are deliberately deferred to a later analysis step.
    processed = bis_daily.melt(
        id_vars=["CURRENCY", "REF_AREA", "Currency"],
        value_vars=observation_dates,
        var_name="date",
        value_name="rate_per_usd",
    )
    processed = processed.rename(
        columns={
            "CURRENCY": "currency",
            "REF_AREA": "reference_area",
            "Currency": "currency_name",
        }
    )
    processed["date"] = pd.to_datetime(processed["date"], format="%Y-%m-%d")
    processed = processed[
        ["date", "currency", "reference_area", "currency_name", "rate_per_usd"]
    ].sort_values(["currency", "reference_area", "date"])
else:
    processed = pd.DataFrame(
        columns=["date", "currency", "reference_area", "currency_name", "rate_per_usd"]
    )

output_file.parent.mkdir(parents=True, exist_ok=True)
processed.to_csv(output_file, index=False)

print("Currencies required by RPW:", len(required_currencies))
print("Source currencies required:", len(source_currencies))
print("Destination currencies required:", len(destination_currencies))
print("Total unique currencies required:", len(required_currencies))
print("Required currencies available in BIS daily series:", len(available_currencies))
print("Currencies required but unavailable in BIS daily series:", len(unavailable_currencies))
print("Unavailable currencies:", unavailable_currencies)
print("Processed BIS rows:", len(processed))
print("Output shape:", processed.shape)
print("Sorted currencies in output:", sorted(processed["currency"].dropna().unique()))
print("Minimum date:", processed["date"].min())
print("Maximum date:", processed["date"].max())
print("Distinct currencies:", processed["currency"].nunique())
print("Missing rate count:", processed["rate_per_usd"].isna().sum())

print("\nRequested currency presence:")
for currency in ["GBP", "INR", "PHP", "AED", "ZAR", "TRY", "TZS", "KES"]:
    print(
        f"{currency}: "
        f"{'present' if currency in set(processed['currency']) else 'not present'} "
        f"({'available in BIS daily series' if currency in available_bis_currencies else 'no BIS daily series'})"
    )

print("\nFirst 10 rows:")
print(processed.head(10).to_string(index=False))

print("\nSample rows for GBP, INR, USD, PHP, and PKR:")
sample_currencies = ["GBP", "INR", "USD", "PHP", "PKR"]
for currency in sample_currencies:
    currency_rows = processed.loc[processed["currency"] == currency]
    if currency == "PKR":
        missing_sample = currency_rows.loc[currency_rows["rate_per_usd"].isna()].head(3)
        sample = missing_sample if not missing_sample.empty else currency_rows.head(3)
    else:
        sample = currency_rows.head(3)

    if sample.empty:
        if currency not in required_currencies:
            print(f"\n{currency}: not required by RPW, so excluded from the processed file")
        else:
            print(f"\n{currency}: no processed BIS rows")
    else:
        if currency == "PKR" and sample["rate_per_usd"].isna().all():
            print(f"\n{currency} (missing rates preserved):")
        else:
            print(f"\n{currency}:")
        print(sample.to_string(index=False))

# Confirm the generated file exists and can be read back with the same shape.
if not output_file.exists():
    raise FileNotFoundError(f"Processed BIS file was not created: {output_file}")

read_back = pd.read_csv(output_file)
if read_back.shape != processed.shape:
    raise ValueError(
        f"Read-back shape {read_back.shape} does not match written data {processed.shape}"
    )

print("\nGenerated CSV:", output_file)
print("Read-back shape:", read_back.shape)
