"""Shared silver-layer functions used by every rendered silver notebook.

DE Policy v2, silver section: explicit data types, a logical primary key,
Delta MERGE (never truncate-and-reload) and the four audit columns on
every table. These functions implement those rules once, so the notebooks
only carry table-specific settings.

The module never touches ``notebookutils`` or widgets: notebooks pass every
value in (job readiness rule JR6).
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional, Sequence, Tuple

AUDIT_COLUMNS = [
    ("InsertLoadStepID", "string"),
    ("InsertTimestamp", "timestamp"),
    ("LastUpdateLoadStepID", "string"),
    ("LastUpdateTimestamp", "timestamp"),
]
ORDER_PREFIX = "__order_"

Column = Tuple[str, str, str]


def resolve_load_date(load_date: str, today: Optional[dt.date] = None) -> str:
    """Return the load date, defaulting to yesterday (UTC).

    Args:
        load_date: ``yyyy-mm-dd`` or an empty string.
        today: Override for "today" (tests only).

    Returns:
        A ``yyyy-mm-dd`` date.

    Raises:
        ValueError: If ``load_date`` is not a valid date.
    """
    if load_date and load_date.strip():
        return dt.date.fromisoformat(load_date.strip()).isoformat()
    today = today or dt.datetime.now(dt.timezone.utc).date()
    return (today - dt.timedelta(days=1)).isoformat()


def select_expressions(columns: Sequence[Column],
                       order_by: Sequence[str]) -> List[str]:
    """Return the Spark SQL select list that renames and casts columns.

    Args:
        columns: (name, Spark type, expression) per silver column.
        order_by: Dedupe ordering expressions over the input columns,
            e.g. ``_ingested_at desc``. Each becomes a hidden column.

    Returns:
        Expressions for ``DataFrame.selectExpr``.
    """
    exprs = [f"cast(({expr}) as {data_type}) as `{name}`"
             for name, data_type, expr in columns]
    for i, item in enumerate(order_by):
        direction = "desc" if _is_descending(item) else "asc"
        exprs.append(f"{_order_expression(item)} as "
                     f"`{ORDER_PREFIX}{i}_{direction}`")
    return exprs


def _order_expression(item: str) -> str:
    """Strip ``asc``/``desc`` from an ordering item.

    Args:
        item: e.g. ``_ingested_at desc``.

    Returns:
        The expression without its direction.
    """
    words = item.strip().split()
    if len(words) > 1 and words[-1].lower() in ("asc", "desc"):
        return " ".join(words[:-1])
    return item.strip()


def _is_descending(item: str) -> bool:
    """Return True when an ordering item ends with ``desc``.

    Args:
        item: e.g. ``_ingested_at desc``.

    Returns:
        Whether to sort descending.
    """
    return item.strip().lower().endswith(" desc")


def merge_condition(keys: Sequence[str]) -> str:
    """Return the MERGE join condition on the business keys.

    Args:
        keys: Business key columns.

    Returns:
        e.g. ``t.`Customer_BK` = s.`Customer_BK```.
    """
    return " and ".join(f"t.`{k}` = s.`{k}`" for k in keys)


def change_condition(columns: Sequence[str]) -> Optional[str]:
    """Return a null-safe "any data column changed" condition.

    Args:
        columns: Data (non-key) columns.

    Returns:
        The condition, or None when there are no data columns.
    """
    if not columns:
        return None
    return " or ".join(f"not (t.`{c}` <=> s.`{c}`)" for c in columns)


def table_ddl(table: str, columns: Sequence[Column], keys: Sequence[str],
              description: str) -> str:
    """Return ``CREATE TABLE IF NOT EXISTS`` for a silver table.

    Column order follows the policy: business keys, data, audit columns.

    Args:
        table: ``lakehouse.schema.Table``.
        columns: (name, Spark type, expression) per silver column.
        keys: Business key columns (created NOT NULL).
        description: Table comment.

    Returns:
        Spark SQL DDL.
    """
    ordered = ([c for c in columns if c[0] in keys]
               + [c for c in columns if c[0] not in keys])
    lines = [f"`{name}` {data_type}{' NOT NULL' if name in keys else ''}"
             for name, data_type, _ in ordered]
    lines += [f"`{name}` {data_type} NOT NULL"
              for name, data_type in AUDIT_COLUMNS]
    comment = description.replace("'", "\\'")
    return (f"CREATE TABLE IF NOT EXISTS {table} (\n  "
            + ",\n  ".join(lines)
            + f"\n) USING DELTA COMMENT '{comment}'")


def read_bronze(spark, table: str, expected_columns: Sequence[str],
                watermark_column: Optional[str], load_date: str,
                lookback_days: int):
    """Read a bronze table, checking the columns this notebook relies on.

    Args:
        spark: The Spark session.
        table: ``lakehouse.schema.table`` in bronze.
        expected_columns: Columns that must exist (case-insensitive).
        watermark_column: Load timestamp column for incremental reads, or
            None to read the whole table.
        load_date: Business date (``yyyy-mm-dd``).
        lookback_days: Days before ``load_date`` to read again, so late
            rows are not missed.

    Returns:
        The bronze rows as a DataFrame.

    Raises:
        ValueError: If an expected column is missing from bronze.
    """
    frame = spark.read.table(table)
    present = {c.lower() for c in frame.columns}
    missing = [c for c in expected_columns if c.lower() not in present]
    if missing:
        raise ValueError(f"{table} is missing columns {missing}; the source "
                         "changed. Update the source and silver specs.")
    if watermark_column:
        start = (dt.date.fromisoformat(load_date)
                 - dt.timedelta(days=lookback_days)).isoformat()
        frame = frame.where(f"`{watermark_column}` >= date'{start}'")
    return frame


def conform(frame, columns: Sequence[Column], order_by: Sequence[str]):
    """Rename and cast every column to its declared type.

    Args:
        frame: Input rows.
        columns: (name, Spark type, expression) per silver column.
        order_by: Dedupe ordering, kept as hidden columns.

    Returns:
        The conformed DataFrame.
    """
    return frame.selectExpr(*select_expressions(columns, order_by))


def latest_per_key(frame, keys: Sequence[str]):
    """Keep one row per business key: the first by the dedupe ordering.

    Args:
        frame: Output of ``conform`` with hidden ordering columns.
        keys: Business key columns.

    Returns:
        One row per key, without the hidden columns.

    Raises:
        ValueError: If a key repeats and no ordering was given.
    """
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    hidden = [c for c in frame.columns if c.startswith(ORDER_PREFIX)]
    if not hidden:
        assert_unique(frame, keys)
        return frame
    order = []
    for name in sorted(hidden,
                       key=lambda c: int(c[len(ORDER_PREFIX):].split("_")[0])):
        column = F.col(name)
        order.append(column.desc_nulls_last() if name.endswith("_desc")
                     else column.asc_nulls_last())
    window = Window.partitionBy(*keys).orderBy(*order)
    ranked = frame.withColumn("__row", F.row_number().over(window))
    return ranked.where("__row = 1").drop("__row", *hidden)


def assert_unique(frame, keys: Sequence[str]) -> None:
    """Fail when a business key appears more than once.

    Args:
        frame: Rows about to be merged.
        keys: Business key columns.

    Raises:
        ValueError: If any key repeats (the MERGE would be ambiguous).
    """
    duplicates = frame.groupBy(*keys).count().where("count > 1").limit(1)
    if duplicates.count():
        raise ValueError(f"business key {list(keys)} is not unique; fix the "
                         "query or add dedupe_order_by to the spec")


def ensure_table(spark, table: str, columns: Sequence[Column],
                 keys: Sequence[str], description: str) -> None:
    """Create the silver table and add columns added to the spec since.

    Schema changes are explicit: new columns are added with ALTER TABLE,
    never by schema inference or ``mergeSchema``.

    Args:
        spark: The Spark session.
        table: ``lakehouse.schema.Table``.
        columns: (name, Spark type, expression) per silver column.
        keys: Business key columns.
        description: Table comment.
    """
    lakehouse_schema = table.rsplit(".", 1)[0]
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {lakehouse_schema}")
    spark.sql(table_ddl(table, columns, keys, description))
    existing = {c.lower() for c in spark.read.table(table).columns}
    new = [f"`{name}` {data_type}" for name, data_type, _ in columns
           if name.lower() not in existing]
    if new:
        spark.sql(f"ALTER TABLE {table} ADD COLUMNS ({', '.join(new)})")


def merge_into(spark, table: str, frame, keys: Sequence[str],
               load_step_id: str) -> int:
    """MERGE rows into a silver table on its business keys.

    Insert* audit columns are set on insert only; LastUpdate* columns on
    insert and on every update. Unchanged rows are not touched.

    Args:
        spark: The Spark session.
        table: ``lakehouse.schema.Table``.
        frame: One row per business key, with the silver columns.
        keys: Business key columns.
        load_step_id: Load step identifier for the audit columns.

    Returns:
        The number of rows in ``frame``.
    """
    from delta.tables import DeltaTable
    from pyspark.sql import functions as F

    data = [c for c in frame.columns if c not in keys]
    now = F.current_timestamp()
    step = F.lit(load_step_id)
    target = DeltaTable.forName(spark, table)
    merge = target.alias("t").merge(frame.alias("s"), merge_condition(keys))
    changed = change_condition(data)
    if changed:
        merge = merge.whenMatchedUpdate(condition=changed, set={
            **{f"`{c}`": F.col(f"s.`{c}`") for c in data},
            "LastUpdateLoadStepID": step,
            "LastUpdateTimestamp": now,
        })
    merge.whenNotMatchedInsert(values={
        **{f"`{c}`": F.col(f"s.`{c}`") for c in frame.columns},
        "InsertLoadStepID": step,
        "InsertTimestamp": now,
        "LastUpdateLoadStepID": step,
        "LastUpdateTimestamp": now,
    }).execute()
    return frame.count()
