import pandas as pd
from data_quality import audit_data_quality

file_path = "data/raw/rpw_dataset_2011_2025_q1.xlsx"

df = pd.read_excel(
    file_path,
    sheet_name="Dataset (from Q2 2016)"
)
print(df.shape)
print(df.columns.tolist())
df.columns = (
    df.columns
    .str.strip()
    .str.lower()
    .str.replace(" ", "_")
    .str.replace("%", "pct")
)
print(df.columns.tolist())
df["date"] = pd.to_datetime(
    df["date"],
    format="mixed",
    errors="coerce"
)

print(df["date"].dtype)
print(df["date"].isna().sum())
output_path = "data/processed/rpw_clean.csv"

df.to_csv(output_path, index=False)

print(f"Saved processed dataset to: {output_path}")
check_df = pd.read_csv(output_path, dtype={"note2": "string"})

print("Processed shape:", check_df.shape)
print("Processed columns:", len(check_df.columns))
audit_data_quality(df)
