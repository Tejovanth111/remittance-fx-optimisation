-- Load the processed RPW data into a temporary view for analysis.
-- Run this file from the project root so the relative CSV path works.
CREATE OR REPLACE TEMP VIEW rpw AS
SELECT *
FROM read_csv_auto('data/processed/rpw_clean.csv', header = true);

-- 1. Total number of rows
SELECT COUNT(*) AS total_rows
FROM rpw;

-- 2. Number of distinct source countries
SELECT COUNT(DISTINCT source_name) AS distinct_source_countries
FROM rpw;

-- 3. Number of distinct destination countries
SELECT COUNT(DISTINCT destination_name) AS distinct_destination_countries
FROM rpw;

-- 4. Number of distinct corridors
SELECT COUNT(DISTINCT corridor) AS distinct_corridors
FROM rpw;

-- 5. Number of distinct providers
SELECT COUNT(DISTINCT firm) AS distinct_providers
FROM rpw;

-- 6. Earliest date
SELECT MIN(date) AS earliest_date
FROM rpw;

-- 7. Latest date
SELECT MAX(date) AS latest_date
FROM rpw;

-- 8. Number of distinct periods
SELECT COUNT(DISTINCT period) AS distinct_periods
FROM rpw;

-- 9. Top 10 corridors by number of observations
SELECT
    corridor,
    COUNT(*) AS observations
FROM rpw
GROUP BY corridor
ORDER BY observations DESC
LIMIT 10;

-- 10. Top 10 providers by number of observations
SELECT
    firm AS provider,
    COUNT(*) AS observations
FROM rpw
GROUP BY firm
ORDER BY observations DESC
LIMIT 10;
-- 11. Pricing observations with India as the destination
SELECT COUNT(*) AS india_destination_observations
FROM rpw
WHERE destination_name = 'India';
-- 12. Pricing observations from the United States to India
SELECT COUNT(*) AS usa_to_india_observations
FROM rpw
WHERE source_name = 'United States'
  AND destination_name = 'India';
  -- 13. Pricing observations destined for India or the Philippines
SELECT COUNT(*) AS india_or_philippines_observations
FROM rpw
WHERE destination_name = 'India'
   OR destination_name = 'Philippines';
   -- 14. Common CC1 transfer amounts
SELECT
    cc1_denomination_amount,
    COUNT(*) AS observations
FROM rpw
GROUP BY cc1_denomination_amount
ORDER BY observations DESC
LIMIT 10;
-- 15. Common CC2 transfer amounts
SELECT
    cc2_denomination_amount,
    COUNT(*) AS observations
FROM rpw
GROUP BY cc2_denomination_amount
ORDER BY observations DESC
LIMIT 10;
-- 16. CC1 observations with a fee greater than 10 local-currency units
SELECT COUNT(*) AS observations_fee_over_10
FROM rpw
WHERE cc1_lcu_fee > 10;
-- 17. CC1 observations with total cost above 5%
SELECT COUNT(*) AS observations_total_cost_over_5pct
FROM rpw
WHERE cc1_total_cost_pct > 5;
-- 18. Average CC1 total cost
SELECT
    AVG(cc1_total_cost_pct) AS average_cc1_total_cost_pct
FROM rpw;
-- 19. Average CC1 total cost by corridor
SELECT
    corridor,
    AVG(cc1_total_cost_pct) AS average_total_cost_pct
FROM rpw
GROUP BY corridor
ORDER BY average_total_cost_pct DESC
LIMIT 10;
-- 19. Average CC1 total cost and observation count by corridor
SELECT
    corridor,
    COUNT(*) AS observations,
    AVG(cc1_total_cost_pct) AS average_total_cost_pct
FROM rpw
GROUP BY corridor
ORDER BY average_total_cost_pct DESC
LIMIT 10;
-- 21. Corridors with at least 100 CC1 cost observations
SELECT
    corridor,
    COUNT(cc1_total_cost_pct) AS cost_observations,
    AVG(cc1_total_cost_pct) AS average_total_cost_pct
FROM rpw
GROUP BY corridor
HAVING COUNT(cc1_total_cost_pct) >= 100
ORDER BY average_total_cost_pct DESC
LIMIT 10;
-- 22. Compare average total cost for the $200 and $500 benchmarks
SELECT
    AVG(cc1_total_cost_pct) AS avg_cost_200,
    AVG(cc2_total_cost_pct) AS avg_cost_500
FROM rpw;
-- 23. Compare $200 and $500 average costs by corridor
SELECT
    corridor,
    COUNT(cc1_total_cost_pct) AS cc1_observations,
    COUNT(cc2_total_cost_pct) AS cc2_observations,
    AVG(cc1_total_cost_pct) AS avg_cost_200,
    AVG(cc2_total_cost_pct) AS avg_cost_500
FROM rpw
GROUP BY corridor
HAVING COUNT(cc1_total_cost_pct) >= 100
ORDER BY avg_cost_200 DESC
LIMIT 10;
-- 24. Compare average explicit fees for $200 and $500
SELECT
    AVG(cc1_lcu_fee) AS avg_fee_200_local_currency,
    AVG(cc2_lcu_fee) AS avg_fee_500_local_currency
FROM rpw;
-- 25. Compare average FX margin for $200 and $500
SELECT
    AVG(cc1_fx_margin) AS avg_fx_margin_200,
    AVG(cc2_fx_margin) AS avg_fx_margin_500
FROM rpw;
-- 26. Average reduction in reported total cost from $200 to $500
SELECT
    AVG(cc1_total_cost_pct - cc2_total_cost_pct) AS average_cost_difference
FROM rpw
WHERE cc1_total_cost_pct IS NOT NULL
  AND cc2_total_cost_pct IS NOT NULL;
  -- 26. Corridors with the largest reduction in reported total cost
SELECT
    corridor,
    COUNT(cc1_total_cost_pct) AS observations,
    AVG(cc1_total_cost_pct) AS avg_cost_200,
    AVG(cc2_total_cost_pct) AS avg_cost_500,
    AVG(cc1_total_cost_pct - cc2_total_cost_pct) AS average_cost_reduction
FROM rpw
WHERE cc1_total_cost_pct IS NOT NULL
  AND cc2_total_cost_pct IS NOT NULL
GROUP BY corridor
HAVING COUNT(cc1_total_cost_pct) >= 100
ORDER BY average_cost_reduction DESC
LIMIT 10;
-- 28. Relative reduction in reported total cost
SELECT
    corridor,
    COUNT(cc1_total_cost_pct) AS observations,
    AVG(cc1_total_cost_pct) AS avg_cost_200,
    AVG(cc2_total_cost_pct) AS avg_cost_500,
    AVG(cc1_total_cost_pct - cc2_total_cost_pct) AS reduction_percentage_points,
    (
        (AVG(cc1_total_cost_pct) - AVG(cc2_total_cost_pct))
        / AVG(cc1_total_cost_pct)
    ) * 100 AS relative_reduction_pct
FROM rpw
WHERE cc1_total_cost_pct IS NOT NULL
  AND cc2_total_cost_pct IS NOT NULL
GROUP BY corridor
HAVING COUNT(cc1_total_cost_pct) >= 100
ORDER BY relative_reduction_pct DESC
LIMIT 10;
-- 29. Average reported total cost by provider
SELECT
    firm AS provider,
    COUNT(cc1_total_cost_pct) AS observations,
    AVG(cc1_total_cost_pct) AS avg_cost_200,
    AVG(cc2_total_cost_pct) AS avg_cost_500
FROM rpw
WHERE cc1_total_cost_pct IS NOT NULL
GROUP BY firm
HAVING COUNT(cc1_total_cost_pct) >= 100
ORDER BY avg_cost_200 DESC
LIMIT 15;
-- 30. Compare major remittance providers
SELECT
    firm AS provider,
    COUNT(cc1_total_cost_pct) AS observations,
    AVG(cc1_total_cost_pct) AS avg_cost_200,
    AVG(cc2_total_cost_pct) AS avg_cost_500,
    AVG(cc1_fx_margin) AS avg_fx_margin_200,
    AVG(cc2_fx_margin) AS avg_fx_margin_500
FROM rpw
WHERE cc1_total_cost_pct IS NOT NULL
  AND firm IN (
      'Western Union',
      'MoneyGram',
      'Ria',
      'WorldRemit',
      'Remitly',
      'Wise',
      'Xoom'
  )
GROUP BY firm
HAVING COUNT(cc1_total_cost_pct) >= 100
ORDER BY avg_cost_200;
-- 31. FX margin difference by major provider
SELECT
    firm AS provider,
    COUNT(cc1_fx_margin) AS observations,
    AVG(cc1_fx_margin) AS avg_fx_margin_200,
    AVG(cc2_fx_margin) AS avg_fx_margin_500,
    AVG(cc1_fx_margin - cc2_fx_margin) AS fx_margin_difference
FROM rpw
WHERE cc1_fx_margin IS NOT NULL
  AND cc2_fx_margin IS NOT NULL
  AND firm IN (
      'Western Union',
      'MoneyGram',
      'Ria',
      'WorldRemit',
      'Remitly',
      'Wise',
      'Xoom'
  )
GROUP BY firm
HAVING COUNT(cc1_fx_margin) >= 100
ORDER BY avg_fx_margin_200 DESC;
-- 32. Compare Wise and Western Union on shared corridors
SELECT
    corridor,
    firm AS provider,
    COUNT(cc1_total_cost_pct) AS observations,
    AVG(cc1_total_cost_pct) AS avg_cost_200,
    AVG(cc1_fx_margin) AS avg_fx_margin_200
FROM rpw
WHERE firm IN ('Wise', 'Western Union')
  AND cc1_total_cost_pct IS NOT NULL
GROUP BY corridor, firm
HAVING COUNT(cc1_total_cost_pct) >= 20
ORDER BY corridor, avg_cost_200;
-- 33. Direct Wise vs Western Union comparison by corridor
SELECT
    corridor,

    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_total_cost_pct
    END) AS wise_avg_cost_200,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_total_cost_pct
    END) AS western_union_avg_cost_200,

    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_fx_margin
    END) AS wise_avg_fx_margin,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_fx_margin
    END) AS western_union_avg_fx_margin

FROM rpw

WHERE firm IN ('Wise', 'Western Union')
  AND cc1_total_cost_pct IS NOT NULL

GROUP BY corridor

HAVING
    COUNT(CASE WHEN firm = 'Wise' THEN 1 END) >= 20
    AND COUNT(CASE WHEN firm = 'Western Union' THEN 1 END) >= 20

ORDER BY corridor;
-- 34. Wise vs Western Union cost difference on shared corridors
SELECT
    corridor,

    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_total_cost_pct
    END) AS wise_avg_cost_200,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_total_cost_pct
    END) AS western_union_avg_cost_200,

    AVG(
        CASE
            WHEN firm = 'Western Union'
            THEN cc1_total_cost_pct
        END
    )
    -
    AVG(
        CASE
            WHEN firm = 'Wise'
            THEN cc1_total_cost_pct
        END
    ) AS western_union_minus_wise

FROM rpw

WHERE firm IN ('Wise', 'Western Union')
  AND cc1_total_cost_pct IS NOT NULL

GROUP BY corridor

HAVING
    COUNT(CASE WHEN firm = 'Wise' THEN 1 END) >= 20
    AND COUNT(CASE WHEN firm = 'Western Union' THEN 1 END) >= 20

ORDER BY western_union_minus_wise DESC
LIMIT 15;
-- 35. Compare Wise vs Western Union cost and FX margin
SELECT
    corridor,

    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_total_cost_pct
    END) AS wise_cost_200,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_total_cost_pct
    END) AS western_union_cost_200,

    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_fx_margin
    END) AS wise_fx_margin,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_fx_margin
    END) AS western_union_fx_margin,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_fx_margin
    END)
    -
    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_fx_margin
    END) AS fx_margin_difference

FROM rpw

WHERE firm IN ('Wise', 'Western Union')
  AND cc1_total_cost_pct IS NOT NULL
  AND cc1_fx_margin IS NOT NULL

GROUP BY corridor

HAVING
    COUNT(CASE WHEN firm = 'Wise' THEN 1 END) >= 20
    AND COUNT(CASE WHEN firm = 'Western Union' THEN 1 END) >= 20

ORDER BY fx_margin_difference DESC
LIMIT 15;
-- 36. Compare provider cost differences with FX-margin differences
SELECT
    corridor,

    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_total_cost_pct
    END) AS wise_cost_200,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_total_cost_pct
    END) AS western_union_cost_200,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_total_cost_pct
    END)
    -
    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_total_cost_pct
    END) AS cost_difference,

    AVG(CASE
        WHEN firm = 'Western Union'
        THEN cc1_fx_margin
    END)
    -
    AVG(CASE
        WHEN firm = 'Wise'
        THEN cc1_fx_margin
    END) AS fx_margin_difference

FROM rpw

WHERE firm IN ('Wise', 'Western Union')
  AND cc1_total_cost_pct IS NOT NULL
  AND cc1_fx_margin IS NOT NULL

GROUP BY corridor

HAVING
    COUNT(CASE WHEN firm = 'Wise' THEN 1 END) >= 20
    AND COUNT(CASE WHEN firm = 'Western Union' THEN 1 END) >= 20

ORDER BY cost_difference DESC;
-- 37. Relationship between FX margin difference and total cost difference
WITH corridor_comparison AS (
    SELECT
        corridor,

        AVG(CASE
            WHEN firm = 'Wise'
            THEN cc1_total_cost_pct
        END) AS wise_cost_200,

        AVG(CASE
            WHEN firm = 'Western Union'
            THEN cc1_total_cost_pct
        END) AS western_union_cost_200,

        AVG(CASE
            WHEN firm = 'Western Union'
            THEN cc1_total_cost_pct
        END)
        -
        AVG(CASE
            WHEN firm = 'Wise'
            THEN cc1_total_cost_pct
        END) AS cost_difference,

        AVG(CASE
            WHEN firm = 'Western Union'
            THEN cc1_fx_margin
        END)
        -
        AVG(CASE
            WHEN firm = 'Wise'
            THEN cc1_fx_margin
        END) AS fx_margin_difference

    FROM rpw

    WHERE firm IN ('Wise', 'Western Union')
      AND cc1_total_cost_pct IS NOT NULL
      AND cc1_fx_margin IS NOT NULL

    GROUP BY corridor

    HAVING
        COUNT(CASE WHEN firm = 'Wise' THEN 1 END) >= 20
        AND COUNT(CASE WHEN firm = 'Western Union' THEN 1 END) >= 20
)

SELECT
    COUNT(*) AS shared_corridors,
    CORR(cost_difference, fx_margin_difference) AS correlation
FROM corridor_comparison;
-- 38. Relationship between the CC1 local-currency fee and total cost percentage
SELECT
    COUNT(*) AS valid_observations,
    AVG(cc1_lcu_fee) AS average_lcu_fee,
    AVG(cc1_total_cost_pct) AS average_total_cost_pct,
    CORR(cc1_lcu_fee, cc1_total_cost_pct) AS fee_cost_correlation
FROM rpw
WHERE cc1_lcu_fee IS NOT NULL
  AND cc1_total_cost_pct IS NOT NULL;
-- 39. Relationship between reported CC1 FX margin and total cost percentage
SELECT
    COUNT(*) AS valid_observations,
    AVG(cc1_fx_margin) AS average_fx_margin,
    AVG(cc1_total_cost_pct) AS average_total_cost_pct,
    CORR(cc1_fx_margin, cc1_total_cost_pct) AS fx_margin_cost_correlation
FROM rpw
WHERE cc1_fx_margin IS NOT NULL
  AND cc1_total_cost_pct IS NOT NULL;
