# Remittance Economics & FX Optimisation

## Business problem

International money transfers involve fees and exchange rates that affect how much a customer pays and how much a recipient receives. Understanding these costs across transfer routes can help explain customer value and provider economics.

## Project objective

Build a reproducible analytics project to study remittance activity, pricing, and foreign exchange (FX) costs, then explore how alternative pricing or FX assumptions could affect customer cost and provider economics where the available data supports the calculation.

## Key business questions

- How do transaction volume and transfer size vary across corridors?
- How do fees and exchange rates affect the total customer cost of a transfer, where the available data supports the calculation?
- How does the FX spread contribute to customer cost and provider economics, where the available data supports the calculation?
- How would alternative pricing or FX scenarios change these outcomes?

## Planned analysis

- Transaction volume and transfer size
- Corridor analysis
- Remittance pricing and FX rates
- FX spread and customer cost, where the available data supports the calculation
- Provider economics, where the available data supports the calculation
- Scenario analysis and optimisation

## Planned technology stack

- **Python** for data preparation and analysis
- **SQL** and **DuckDB** for querying data
- **Jupyter** for exploratory work and explanations
- **Git/GitHub** for version control and project history
- **Power BI** for a planned reporting layer

## Project structure

```text
.
├── dashboard/   # Planned dashboard work
├── data/
│   ├── external/   # External reference data
│   ├── processed/  # Prepared data
│   └── raw/        # Preserved source data
├── docs/        # Project documentation
├── notebooks/   # Exploratory analysis
├── reports/     # Analysis outputs
├── sql/         # SQL queries
├── src/         # Reusable Python code
└── tests/       # Automated checks
```

## Data principles

- Use real public data where possible, with **100,000+ transaction-level records** as a project target if suitable data is available. Data quality and suitability take priority over reaching the row-count target.
- Never fabricate data or present synthetic values as observed facts.
- Preserve raw source data and carry out preparation in separate locations.
- Document data sources, definitions, transformations, and assumptions.

Observed results will be clearly separated from modelled assumptions and scenario outputs. Customer cost, FX spread, and provider economics will be analysed where the available data supports the calculation.

## Project status

Currently in the **setup and data acquisition** stage. No data has been analysed yet.
