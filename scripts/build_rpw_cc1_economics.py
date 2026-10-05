"""Build a CC1 economics dataset from the cleaned RPW observations."""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_clean.csv"
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "rpw_cc1_economics.csv"

OUTPUT_COLUMNS = [
    "id",
    "date",
    "period",
    "corridor",
    "firm",
    "source_code",
    "source_name",
    "destination_code",
    "destination_name",
    "cc1_denomination_amount",
    "cc1_lcu_amount",
    "cc1_lcu_code",
    "cc1_lcu_fee",
    "cc1_lcu_fx_rate",
    "cc1_fx_margin",
    "cc1_total_cost_pct",
    "fee_pct",
]


def sha256_file(path: Path) -> str:
    """Return a SHA-256 digest for checking that the source remains unchanged."""
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    source_hash_before = sha256_file(SOURCE_FILE)

    source = pd.read_csv(SOURCE_FILE, usecols=OUTPUT_COLUMNS[:-1], low_memory=False)
    if len(source) != 197_999:
        raise ValueError(f"Expected 197,999 source rows; found {len(source):,}")
    if source["id"].duplicated().any():
        raise ValueError("Source IDs are not unique")

    fee = pd.to_numeric(source["cc1_lcu_fee"], errors="coerce")
    amount = pd.to_numeric(source["cc1_lcu_amount"], errors="coerce")
    # Keep undefined ratios missing, including rows with missing inputs or a
    # zero local-currency amount. No source observations are dropped.
    valid_ratio = fee.notna() & amount.notna() & amount.ne(0)
    source["fee_pct"] = np.nan
    source.loc[valid_ratio, "fee_pct"] = fee.loc[valid_ratio] / amount.loc[valid_ratio] * 100
    output = source[OUTPUT_COLUMNS].copy()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_FILE, index=False)

    # Read the new file back so the checks apply to the delivered CSV.
    checked = pd.read_csv(OUTPUT_FILE, low_memory=False)
    if checked.columns.tolist() != OUTPUT_COLUMNS:
        raise ValueError("Output columns do not match the requested column list")
    if len(checked) != 197_999:
        raise ValueError(f"Expected 197,999 output rows; found {len(checked):,}")
    if checked["id"].duplicated().any():
        raise ValueError("Output IDs are not unique")

    reconstruction_error = (
        pd.to_numeric(checked["fee_pct"], errors="coerce")
        + pd.to_numeric(checked["cc1_fx_margin"], errors="coerce")
        - pd.to_numeric(checked["cc1_total_cost_pct"], errors="coerce")
    )
    fee_pct = pd.to_numeric(checked["fee_pct"], errors="coerce")

    print("Output shape:", checked.shape)
    print("Output columns:", checked.columns.tolist())
    print("Row count:", len(checked))
    print("Unique ID count:", checked["id"].nunique(dropna=True))
    print("Missing fee_pct count:", int(fee_pct.isna().sum()))
    print("fee_pct minimum:", fee_pct.min())
    print("fee_pct median:", fee_pct.median())
    print("fee_pct mean:", fee_pct.mean())
    print("fee_pct maximum:", fee_pct.max())
    print(
        "Reconstruction errors with absolute value > 1:",
        int(reconstruction_error.abs().gt(1).sum()),
    )
    print("Mean reconstruction error:", reconstruction_error.mean())
    print("Median reconstruction error:", reconstruction_error.median())
    print("Maximum absolute reconstruction error:", reconstruction_error.abs().max())
    print("IDs are unique:", checked["id"].nunique(dropna=True) == len(checked))
    print("Source dataset unchanged:", source_hash_before == sha256_file(SOURCE_FILE))
    print("Output CSV:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
