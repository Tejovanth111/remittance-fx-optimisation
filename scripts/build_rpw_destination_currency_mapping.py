"""Build a dated, auditable RPW destination-country to currency mapping.

Currency validity is taken from Babel's CLDR data (Babel 2.18.0). The RPW
Countries sheet supplies destination alpha-3 codes and country names; those
names are matched to CLDR territory names to find the alpha-2 territory code
expected by Babel. The small crosswalk below covers World Bank name variants
that do not exactly match CLDR English territory names. It is a country-code
crosswalk, not a country-to-currency mapping.
"""

from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd
from babel import Locale
from babel.numbers import get_territory_currencies


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RPW_CSV = PROJECT_ROOT / "data" / "processed" / "rpw_clean.csv"
RPW_WORKBOOK = PROJECT_ROOT / "data" / "raw" / "rpw_dataset_2011_2025_q1.xlsx"
OUTPUT_CSV = PROJECT_ROOT / "data" / "processed" / "rpw_destination_currency_mapping.csv"

COUNTRY_CODE_COLUMN = "ISO 3166-1 alpha-3 country code"
COUNTRY_NAME_COLUMN = "Country name"

# CLDR supplementalData.xml territoryCodes crosswalk entries, used only where
# the workbook's World Bank country name differs from CLDR's English name.
CLDR_ALPHA3_TO_ALPHA2_EXCEPTIONS = {
    "BIH": "BA",  # Bosnia and Herzegovina
    "CIV": "CI",  # Côte d'Ivoire
    "COD": "CD",  # Congo, Dem. Rep.
    "CPV": "CV",  # Cabo Verde
    "EGY": "EG",  # Egypt, Arab Rep.
    "GMB": "GM",  # Gambia, The
    "KGZ": "KG",  # Kyrgyz Republic
    "LAO": "LA",  # Lao PDR
    "MMR": "MM",  # Myanmar
    "PSE": "PS",  # West Bank and Gaza
    "SYR": "SY",  # Syrian Arab Republic
    "YEM": "YE",  # Yemen, Rep.
}


def build_country_territory_crosswalk(countries: pd.DataFrame) -> dict[str, str]:
    """Match RPW alpha-3 codes to CLDR alpha-2 territory codes."""
    territory_names = Locale.parse("en").territories
    codes_by_name: dict[str, list[str]] = defaultdict(list)
    for territory_code, territory_name in territory_names.items():
        codes_by_name[territory_name].append(territory_code)

    crosswalk: dict[str, str] = {}
    for _, row in countries.iterrows():
        alpha3 = str(row[COUNTRY_CODE_COLUMN]).strip()
        country_name = str(row[COUNTRY_NAME_COLUMN]).strip()

        if alpha3 in CLDR_ALPHA3_TO_ALPHA2_EXCEPTIONS:
            crosswalk[alpha3] = CLDR_ALPHA3_TO_ALPHA2_EXCEPTIONS[alpha3]
            continue

        exact_matches = codes_by_name.get(country_name, [])
        if len(exact_matches) == 1:
            crosswalk[alpha3] = exact_matches[0]

    return crosswalk


def main() -> None:
    # Keep the source observation date as text for the output, and parse a
    # separate copy for exact-date CLDR validity checks.
    rpw = pd.read_csv(
        RPW_CSV,
        usecols=["id", "date", "destination_code", "destination_name"],
        dtype={"date": "string", "destination_code": "string", "destination_name": "string"},
    )
    countries = pd.read_excel(
        RPW_WORKBOOK,
        sheet_name="Countries",
        header=1,
        usecols=[COUNTRY_CODE_COLUMN, COUNTRY_NAME_COLUMN],
        dtype=str,
    )
    countries = countries.dropna(subset=[COUNTRY_CODE_COLUMN, COUNTRY_NAME_COLUMN]).copy()
    countries[COUNTRY_CODE_COLUMN] = countries[COUNTRY_CODE_COLUMN].str.strip()
    countries[COUNTRY_NAME_COLUMN] = countries[COUNTRY_NAME_COLUMN].str.strip()

    territory_by_alpha3 = build_country_territory_crosswalk(countries)
    rpw["_parsed_date"] = pd.to_datetime(rpw["date"], errors="coerce")

    @lru_cache(maxsize=None)
    def map_country_date(alpha3: str, observation_date):
        territory = territory_by_alpha3.get(alpha3)
        if territory is None:
            return None, "", "unmapped"

        if pd.isna(observation_date):
            return territory, "", "historical_currency_case"

        date_value = observation_date.date()
        exact_candidates = get_territory_currencies(
            territory,
            start_date=date_value,
            end_date=date_value,
            tender=True,
        )
        exact_candidates = sorted(set(exact_candidates))
        candidates_text = ";".join(exact_candidates)

        if len(exact_candidates) == 1:
            return territory, candidates_text, "mapped"
        if len(exact_candidates) > 1:
            return territory, candidates_text, "multiple_currency_candidates"

        # A known territory with currency history but no tender currency on
        # this exact observation date is a dated gap/transition for review.
        date_range_currencies = get_territory_currencies(
            territory,
            start_date=rpw["_parsed_date"].min().date(),
            end_date=rpw["_parsed_date"].max().date(),
            tender=True,
        )
        if date_range_currencies:
            return territory, "", "historical_currency_case"
        return territory, "", "unmapped"

    mapped = [
        map_country_date(code, date)
        for code, date in zip(rpw["destination_code"], rpw["_parsed_date"])
    ]
    rpw[["cldr_territory_code", "currency_candidates", "currency_mapping_status"]] = pd.DataFrame(
        mapped,
        index=rpw.index,
    )
    rpw["destination_currency"] = rpw["currency_candidates"].where(
        rpw["currency_mapping_status"].eq("mapped"),
        pd.NA,
    )

    output_columns = [
        "id",
        "date",
        "destination_code",
        "destination_name",
        "cldr_territory_code",
        "destination_currency",
        "currency_candidates",
        "currency_mapping_status",
    ]
    output = rpw[output_columns]
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_CSV, index=False)

    print("RPW destination currency mapping diagnostic")
    print(f"Output shape: {output.shape}")
    print(f"Unique destination countries: {output['destination_code'].nunique()}")
    print("Rows by currency_mapping_status:")
    print(output["currency_mapping_status"].value_counts(dropna=False).sort_index().to_string())

    mapped_currencies = sorted(output["destination_currency"].dropna().unique())
    print(f"Unique destination currencies: {len(mapped_currencies)}")
    print("Destination currencies: " + ", ".join(mapped_currencies))

    anomaly_statuses = [
        "multiple_currency_candidates",
        "historical_currency_case",
        "unmapped",
    ]
    anomalies = (
        output.loc[output["currency_mapping_status"].isin(anomaly_statuses)]
        .drop_duplicates(
            [
                "destination_code",
                "destination_name",
                "date",
                "currency_candidates",
                "currency_mapping_status",
            ]
        )
        .sort_values(["destination_code", "date"])
    )
    print("\nReview-combination counts by country/status/candidate:")
    if anomalies.empty:
        print("None")
    else:
        print(
            anomalies.groupby(
                ["destination_code", "destination_name", "currency_candidates", "currency_mapping_status"],
                dropna=False,
            )["date"]
            .size()
            .rename("distinct_country_date_combinations")
            .reset_index()
            .to_string(index=False)
        )
    print("\nAll distinct country-date combinations requiring review:")
    if anomalies.empty:
        print("None")
    else:
        print(
            anomalies[
                [
                    "destination_code",
                    "destination_name",
                    "date",
                    "currency_candidates",
                    "currency_mapping_status",
                ]
            ].to_string(index=False)
        )

    inspected_codes = [
        "GBR",
        "IND",
        "PHL",
        "ZAF",
        "TUR",
        "TZA",
        "KEN",
        "LSO",
        "NAM",
        "PAN",
        "PSE",
        "ZWE",
    ]
    specific = (
        output.loc[output["destination_code"].isin(inspected_codes)]
        .groupby(
            [
                "destination_code",
                "destination_name",
                "destination_currency",
                "currency_candidates",
                "currency_mapping_status",
            ],
            dropna=False,
        )
        .agg(observations=("id", "size"), distinct_dates=("date", "nunique"))
        .reset_index()
        .sort_values(["destination_code", "currency_mapping_status", "currency_candidates"])
    )
    # GBR is explicitly requested for verification, but may not occur as an
    # RPW destination. Show its CLDR currency set over the observation period
    # without adding a synthetic row to the observation-level output artifact.
    observed_codes = set(output["destination_code"].dropna())
    for alpha3 in inspected_codes:
        if alpha3 in observed_codes:
            continue
        territory = territory_by_alpha3.get(alpha3)
        date_range_candidates = []
        if territory is not None and rpw["_parsed_date"].notna().any():
            date_range_candidates = sorted(
                set(
                    get_territory_currencies(
                        territory,
                        start_date=rpw["_parsed_date"].min().date(),
                        end_date=rpw["_parsed_date"].max().date(),
                        tender=True,
                    )
                )
            )
        country_name = countries.loc[
            countries[COUNTRY_CODE_COLUMN].eq(alpha3), COUNTRY_NAME_COLUMN
        ].iloc[0]
        specific = pd.concat(
            [
                specific,
                pd.DataFrame(
                    [
                        {
                            "destination_code": alpha3,
                            "destination_name": country_name,
                            "destination_currency": pd.NA,
                            "currency_candidates": ";".join(date_range_candidates),
                            "currency_mapping_status": "no_destination_observations",
                            "observations": 0,
                            "distinct_dates": 0,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    specific = specific.sort_values(
        ["destination_code", "currency_mapping_status", "currency_candidates"]
    )
    print("\nRequested country checks:")
    print(specific.to_string(index=False))

    print(f"\nSaved mapping artifact: {OUTPUT_CSV.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
