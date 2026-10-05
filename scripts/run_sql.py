from pathlib import Path

import duckdb


project_folder = Path(__file__).resolve().parent.parent
sql_file = project_folder / "sql" / "01_basic_rpw_profile.sql"

with duckdb.connect(database=":memory:") as connection:
    sql_text = sql_file.read_text()

    # Split the file into statements and run them in the order they appear.
    statements = sql_text.split(";")
    select_number = 0

    for statement in statements:
        statement = statement.strip()

        if not statement:
            continue

        # Ignore leading SQL comments when deciding whether this is a SELECT.
        statement_without_comments = "\n".join(
            line for line in statement.splitlines()
            if not line.strip().startswith("--")
        ).strip()

        result = connection.execute(statement)

        if statement_without_comments.upper().startswith(("SELECT", "WITH")):
            select_number += 1
            dataframe = result.df()
            print(f"\nQuery {select_number} result:")
            print(dataframe)
