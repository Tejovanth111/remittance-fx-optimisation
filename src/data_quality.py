def audit_data_quality(df):
    missing = df.isna().sum()

    print("Missing values by column:")
    print(missing[missing > 0])
    missing_pct = (df.isna().sum() / len(df) * 100).round(2)

    print("Missing percentage by column:")
    print(missing_pct[missing_pct > 0])
    duplicate_count = df.duplicated().sum()

    print("Duplicate rows:", duplicate_count)

    duplicate_id_count = df["id"].duplicated().sum()

    print("Duplicate IDs:", duplicate_id_count)
