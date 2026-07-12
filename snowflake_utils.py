"""snowflake_utils.py - connection / load / query helpers for Snowflake."""
import config


def get_connection():
    import snowflake.connector
    s = config.SNOWFLAKE
    return snowflake.connector.connect(
        account=s["account"], user=s["user"], password=s["password"],
        role=s["role"], warehouse=s["warehouse"], database=s["database"],
    )


def run_sql_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        script = f.read()
    statements = [s.strip() for s in script.split(";") if s.strip()
                  and not s.strip().startswith("--")]
    conn = get_connection()
    try:
        cur = conn.cursor()
        for stmt in statements:
            cur.execute(stmt)
        cur.close()
        print(f"[snowflake] ran {len(statements)} statements from {path}")
    finally:
        conn.close()


def execute(sql: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cur.close()
    finally:
        conn.close()


def query(sql: str):
    import pandas as pd
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if hasattr(cur, "fetch_pandas_all"):
            df = cur.fetch_pandas_all()
        else:
            df = pd.DataFrame(cur.fetchall(),
                              columns=[c[0] for c in cur.description])
        cur.close()
        return df
    finally:
        conn.close()


def load_dataframe(df, schema: str, table: str):
    from snowflake.connector.pandas_tools import write_pandas
    conn = get_connection()
    try:
        db = config.SNOWFLAKE["database"]
        cur = conn.cursor()
        cur.execute(f"USE WAREHOUSE {config.SNOWFLAKE['warehouse']}")
        cur.execute(f"USE DATABASE {db}")
        cur.execute(f"USE SCHEMA {db}.{schema.upper()}")
        cur.close()
        df = df.copy()
        df.columns = [c.upper() for c in df.columns]
        success, nchunks, nrows, _ = write_pandas(
            conn, df, table.upper(), schema=schema.upper(),
            database=db, quote_identifiers=False,
            use_logical_type=True)
        print(f"[snowflake] loaded {nrows} rows into {schema}.{table}")
        return nrows
    finally:
        conn.close()


def load_records(schema: str, table: str, rows: list, cols: list):
    import pandas as pd
    df = pd.DataFrame(rows, columns=cols)
    return load_dataframe(df, schema, table)