"""Load the project config (``fde.yml``) and the table specs (``models/``).

Layout read by this module::

    fde.yml
    models/sources/<source>.yml                 bronze tables (read-only)
    models/silver/<schema>/<Table>.yml          silver source table (1:1 bronze)
    models/silver/<domain>/<Table>.yml + .sql   silver integrated table
    models/gold/<domain>/<Table>.yml + .sql     gold Dim/Fact/Bridge table
    models/agents/<Name>.yml                    Fabric Data Agent definition

The schema of a model is its folder name and the table name is its file
name, so neither can drift from where the file lives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

REF_PATTERN = re.compile(
    r"\{\{\s*ref\(\s*['\"](?P<key>[A-Za-z0-9_]+\.[A-Za-z0-9_]+)['\"]\s*\)\s*\}\}")
SOURCE_PATTERN = re.compile(
    r"\{\{\s*source\(\s*['\"](?P<source>\w+)['\"]\s*,\s*"
    r"['\"](?P<table>\w+)['\"]\s*\)\s*\}\}")

AUDIT_COLUMNS = ["InsertLoadStepID", "InsertTimestamp",
                 "LastUpdateLoadStepID", "LastUpdateTimestamp"]
SCD_COLUMNS = ["StartDate", "EndDate", "IsCurrent"]
GOLD_PREFIXES = {"Dim": "dimension", "Fact": "fact", "Bridge": "bridge"}


class SpecError(Exception):
    """Raised when a spec file cannot be read at all."""


@dataclass
class Config:
    """Settings from ``fde.yml``.

    Attributes:
        root: Project root folder.
        project: Project name (snake_case).
        bronze_lakehouse: Bronze Lakehouse item name.
        silver_lakehouse: Silver Lakehouse item name.
        gold_warehouse: Gold Warehouse item name.
        targets: Target name -> settings (environment variable names).
        raw: The whole parsed file.
    """

    root: Path
    project: str
    bronze_lakehouse: str
    silver_lakehouse: str
    gold_warehouse: str
    targets: Dict[str, Dict[str, Any]]
    raw: Dict[str, Any]

    @property
    def silver_concurrency(self) -> int:
        """Return how many silver notebooks may run at the same time."""
        return int((self.raw.get("silver") or {}).get("concurrency", 4))

    @property
    def silver_wheel(self) -> str:
        """Return the wheel path notebooks install ``fabric_de_common`` from.

        Empty (the default) means the library comes from a Fabric
        Environment and notebooks install nothing.
        """
        return str((self.raw.get("silver") or {}).get("install_wheel") or "")

    @property
    def semantic_model(self) -> str:
        """Return the item name of the rendered semantic model."""
        ai = self.raw.get("ai") or {}
        return str(ai.get("semantic_model") or f"sm_{self.project}")

    @property
    def ai_pii(self) -> str:
        """Return how AI items treat PII columns: ``exclude`` or ``include``."""
        return str((self.raw.get("ai") or {}).get("pii", "exclude"))


@dataclass
class Column:
    """One column declared in a spec.

    Attributes:
        name: Column name.
        data_type: Spark type (silver) or Fabric Warehouse type (gold).
        description: Business meaning, unit and allowed values.
        business_key: True when the column is part of the logical key.
        expression: Spark SQL over bronze columns (silver source tables).
        references: ``schema.DimTable`` a gold ``_SK`` column points to.
        lineage: Optional explicit ``schema.Table.Column`` inputs.
        tests: Column tests as written in the spec.
        meta: Free metadata (``pii``, ``matrix``).
        synonyms: Other names the business uses (AI items only).
    """

    name: str
    data_type: str
    description: Optional[str]
    business_key: bool = False
    expression: Optional[str] = None
    references: Optional[str] = None
    lineage: List[str] = field(default_factory=list)
    tests: List[Any] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    synonyms: Any = field(default_factory=list)

    @property
    def pii(self) -> bool:
        """Return True when the column is marked ``meta.pii: true``."""
        return self.meta.get("pii") is True


@dataclass
class Model:
    """One silver or gold table.

    Attributes:
        layer: ``silver`` or ``gold``.
        kind: ``source`` / ``integrated`` (silver), ``dimension`` / ``fact`` /
            ``bridge`` (gold).
        schema: Schema name (the folder).
        name: Table name (the file name).
        path: Spec file.
        sql: Body of the ``.sql`` file, or None.
        spec: The parsed spec.
        columns: Declared columns, in order.
    """

    layer: str
    kind: str
    schema: str
    name: str
    path: Path
    sql: Optional[str]
    spec: Dict[str, Any]
    columns: List[Column]

    @property
    def key(self) -> str:
        """Return ``schema.Table``, the name used by ``ref()``."""
        return f"{self.schema}.{self.name}"

    @property
    def description(self) -> str:
        """Return the model description."""
        return " ".join(str(self.spec.get("description") or "").split())

    @property
    def business_keys(self) -> List[str]:
        """Return the business key column names, in declared order."""
        return [c.name for c in self.columns if c.business_key]

    @property
    def data_columns(self) -> List[Column]:
        """Return the columns that are not business keys."""
        return [c for c in self.columns if not c.business_key]

    @property
    def refs(self) -> List[str]:
        """Return the ``schema.Table`` keys referenced in the ``.sql`` file."""
        if not self.sql:
            return []
        return list(dict.fromkeys(m.group("key")
                                  for m in REF_PATTERN.finditer(self.sql)))

    @property
    def source(self) -> Optional[Tuple[str, str]]:
        """Return (source, table) for a silver source table, else None."""
        src = self.spec.get("source")
        if isinstance(src, dict) and src.get("source") and src.get("table"):
            return str(src["source"]), str(src["table"])
        return None

    @property
    def load(self) -> Dict[str, Any]:
        """Return the load settings (``mode``, column, lookback)."""
        return dict(self.spec.get("load") or {"mode": "full"})

    @property
    def scd_type(self) -> Optional[int]:
        """Return the SCD type of a dimension (1 or 2)."""
        value = self.spec.get("scd_type")
        return int(value) if value not in (None, "") else None

    @property
    def surrogate_key(self) -> str:
        """Return the ``{Table}_SK`` column name (gold only)."""
        return f"{self.name}_SK"

    @property
    def is_scd2(self) -> bool:
        """Return True for a type 2 dimension."""
        return self.kind == "dimension" and self.scd_type == 2

    @property
    def tests(self) -> List[Any]:
        """Return the table-level tests."""
        return list(self.spec.get("tests") or [])

    @property
    def meta(self) -> Dict[str, Any]:
        """Return the table metadata."""
        return dict(self.spec.get("meta") or {})

    @property
    def measures(self) -> List[Dict[str, Any]]:
        """Return the declared measures (facts only)."""
        return list(self.spec.get("measures") or [])

    @property
    def synonyms(self) -> Any:
        """Return the table synonyms (AI items only)."""
        return self.spec.get("synonyms") or []

    @property
    def ai_instructions(self) -> str:
        """Return the table guidance written for AI items."""
        return " ".join(str(self.spec.get("ai_instructions") or "").split())


@dataclass
class SourceTable:
    """One bronze table.

    Attributes:
        source: Source system name.
        name: Table name in bronze.
        description: What the table holds.
        columns: Column name -> SQL endpoint data type.
        meta: Free metadata.
    """

    source: str
    name: str
    description: Optional[str]
    columns: Dict[str, str]
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Source:
    """One bronze source system (a schema in the bronze Lakehouse).

    Attributes:
        name: Source system name.
        schema: Schema in the bronze Lakehouse.
        description: What the source is and how it lands.
        freshness: ``loaded_at_column``, ``warn_after_hours``,
            ``error_after_hours``.
        tables: Table name -> table.
        path: Spec file.
    """

    name: str
    schema: str
    description: Optional[str]
    freshness: Dict[str, Any]
    tables: Dict[str, SourceTable]
    path: Path


@dataclass
class Agent:
    """One Fabric Data Agent, from ``models/agents/<Name>.yml``.

    Attributes:
        name: Agent name (the file name, PascalCase).
        path: Spec file.
        spec: The parsed spec.
    """

    name: str
    path: Path
    spec: Dict[str, Any]

    @property
    def item_name(self) -> str:
        """Return the Fabric item name, ``da_<snake_name>``."""
        return f"da_{snake(self.name)}"

    @property
    def description(self) -> str:
        """Return the agent description."""
        return " ".join(str(self.spec.get("description") or "").split())

    @property
    def instructions(self) -> str:
        """Return the agent-level AI instructions."""
        return str(self.spec.get("instructions") or "").strip()

    @property
    def sources(self) -> List[Dict[str, Any]]:
        """Return the declared data sources."""
        return [s for s in self.spec.get("sources") or []
                if isinstance(s, dict)]

    @property
    def examples(self) -> List[Dict[str, Any]]:
        """Return the example question / query pairs."""
        return [e for e in self.spec.get("examples") or []
                if isinstance(e, dict)]


@dataclass
class Project:
    """Everything under ``models/`` plus the config.

    Attributes:
        config: The parsed ``fde.yml``.
        sources: Source name -> source.
        models: ``schema.Table`` -> model.
        errors: Problems found while loading (file, message).
        agents: Agent name -> Data Agent definition.
    """

    config: Config
    sources: Dict[str, Source]
    models: Dict[str, Model]
    errors: List[Tuple[str, str]]
    agents: Dict[str, Agent] = field(default_factory=dict)

    def silver(self) -> List[Model]:
        """Return the silver models, sorted by key."""
        return [m for k, m in sorted(self.models.items()) if m.layer == "silver"]

    def gold(self) -> List[Model]:
        """Return the gold models, sorted by key."""
        return [m for k, m in sorted(self.models.items()) if m.layer == "gold"]

    def relation(self, model: Model, engine: str = "tsql") -> str:
        """Return the name a model is queried by.

        Args:
            model: The model.
            engine: ``tsql`` (Warehouse, the default) or ``spark``.

        Returns:
            Silver tables as ``lakehouse.schema.Table``; gold tables as
            ``schema.Table`` (bracketed for T-SQL). In T-SQL the silver
            schema and table are lower-cased: Spark stores Lakehouse tables
            in lower case and the Warehouse resolves names case-sensitively.
        """
        if engine == "spark":
            return f"{self.config.silver_lakehouse}.{model.schema}.{model.name}"
        if model.layer == "silver":
            return (f"[{self.config.silver_lakehouse}]."
                    f"[{model.schema.lower()}].[{model.name.lower()}]")
        return f"[{model.schema}].[{model.name}]"

    def source_relation(self, source: str, table: str,
                        engine: str = "tsql") -> str:
        """Return the name a bronze table is queried by.

        Args:
            source: Source system name.
            table: Bronze table name.
            engine: ``tsql`` or ``spark``.

        Returns:
            ``lakehouse.schema.table``, bracketed for T-SQL.
        """
        schema = self.sources[source].schema if source in self.sources \
            else source
        lakehouse = self.config.bronze_lakehouse
        if engine == "spark":
            return f"{lakehouse}.{schema}.{table}"
        return f"[{lakehouse}].[{schema}].[{table}]"

    def resolve_sql(self, sql: str, engine: str) -> str:
        """Replace ``{{ ref() }}`` and ``{{ source() }}`` with real names.

        Args:
            sql: SQL text with placeholders.
            engine: ``tsql`` or ``spark``.

        Returns:
            The SQL with every known placeholder replaced. Unknown refs are
            left in place, so the check step can report them.
        """
        def ref(match: re.Match) -> str:
            model = self.models.get(match.group("key"))
            return self.relation(model, engine) if model else match.group(0)

        def src(match: re.Match) -> str:
            return self.source_relation(match.group("source"),
                                        match.group("table"), engine)

        return SOURCE_PATTERN.sub(src, REF_PATTERN.sub(ref, sql))

    def load_order(self, models: List[Model]) -> List[Model]:
        """Sort models so every model comes after the models it reads.

        Args:
            models: Models of one layer.

        Returns:
            The same models in dependency order (cycles keep file order).
        """
        keys = {m.key for m in models}
        done: List[Model] = []
        seen: set = set()

        def visit(model: Model, stack: Tuple[str, ...]) -> None:
            if model.key in seen or model.key in stack:
                return
            for ref in model.refs:
                if ref in keys and ref != model.key:
                    visit(self.models[ref], stack + (model.key,))
            seen.add(model.key)
            done.append(model)

        for model in sorted(models, key=lambda m: (m.kind != "dimension",
                                                   m.key)):
            visit(model, ())
        return done


def _read_yaml(path: Path) -> Dict[str, Any]:
    """Read one YAML file into a dict.

    Args:
        path: File to read.

    Returns:
        The parsed mapping (empty when the file is empty).

    Raises:
        SpecError: If the file is not valid YAML or not a mapping.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SpecError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError("expected a mapping at the top of the file")
    return data


def load_config(root: Path) -> Config:
    """Read ``fde.yml`` from the project root.

    Args:
        root: Project root folder.

    Returns:
        The config.

    Raises:
        SpecError: If ``fde.yml`` is missing or incomplete.
    """
    path = root / "fde.yml"
    if not path.exists():
        raise SpecError(f"{path} not found; run fde from the project root")
    raw = _read_yaml(path)
    items = raw.get("items") or {}
    return Config(
        root=root,
        project=str(raw.get("project") or "fabric_project"),
        bronze_lakehouse=str(items.get("bronze_lakehouse", "lh_bronze")),
        silver_lakehouse=str(items.get("silver_lakehouse", "lh_silver")),
        gold_warehouse=str(items.get("gold_warehouse", "wh_gold")),
        targets=dict(raw.get("targets") or {}),
        raw=raw,
    )


def _column(raw: Any) -> Column:
    """Build a column from its spec entry.

    Args:
        raw: The YAML mapping for one column.

    Returns:
        The column.
    """
    raw = raw if isinstance(raw, dict) else {"name": str(raw)}
    lineage = raw.get("lineage") or []
    return Column(
        name=str(raw.get("name") or ""),
        data_type=str(raw.get("data_type") or "").strip().lower(),
        description=raw.get("description"),
        business_key=bool(raw.get("business_key", False)),
        expression=raw.get("expression"),
        references=raw.get("references"),
        lineage=[lineage] if isinstance(lineage, str) else list(lineage),
        tests=list(raw.get("tests") or []),
        meta=dict(raw.get("meta") or {}),
        synonyms=raw.get("synonyms") or [],
    )


def _load_source(path: Path) -> Source:
    """Read one ``models/sources/<source>.yml`` file.

    Args:
        path: Spec file.

    Returns:
        The source.
    """
    raw = _read_yaml(path)
    name = str(raw.get("source") or path.stem)
    tables = {}
    for table in raw.get("tables") or []:
        cols = {}
        for col in table.get("columns") or []:
            if isinstance(col, dict):
                cols[str(col.get("name"))] = str(col.get("data_type") or "")
            else:
                cols[str(col)] = ""
        tables[str(table["name"])] = SourceTable(
            source=name, name=str(table["name"]),
            description=table.get("description"), columns=cols,
            meta=dict(table.get("meta") or {}))
    return Source(name=name, schema=str(raw.get("schema") or name),
                  description=raw.get("description"),
                  freshness=dict(raw.get("freshness") or {}),
                  tables=tables, path=path)


def _gold_kind(name: str) -> str:
    """Return the gold kind from the table name prefix.

    Args:
        name: Gold table name.

    Returns:
        ``dimension``, ``fact``, ``bridge`` or ``unknown``.
    """
    for prefix, kind in GOLD_PREFIXES.items():
        if name.startswith(prefix) and name[len(prefix):][:1].isupper():
            return kind
    return "unknown"


def _load_model(path: Path, layer: str) -> Model:
    """Read one silver or gold spec plus its ``.sql`` file.

    Args:
        path: Spec file.
        layer: ``silver`` or ``gold``.

    Returns:
        The model.
    """
    raw = _read_yaml(path)
    sql_path = path.with_suffix(".sql")
    sql = sql_path.read_text(encoding="utf-8") if sql_path.exists() else None
    if layer == "silver":
        kind = "source" if raw.get("source") else "integrated"
    else:
        kind = _gold_kind(path.stem)
    return Model(layer=layer, kind=kind, schema=path.parent.name,
                 name=path.stem, path=path, sql=sql, spec=raw,
                 columns=[_column(c) for c in raw.get("columns") or []])


def load_project(root: Path) -> Project:
    """Load the config and every spec under ``models/``.

    Args:
        root: Project root folder.

    Returns:
        The project. Files that could not be read are listed in ``errors``.
    """
    config = load_config(root)
    errors: List[Tuple[str, str]] = []
    sources: Dict[str, Source] = {}
    models: Dict[str, Model] = {}
    base = root / "models"
    for path in sorted((base / "sources").glob("*.yml")):
        try:
            source = _load_source(path)
            sources[source.name] = source
        except (SpecError, KeyError, TypeError) as exc:
            errors.append((rel(path, root), str(exc)))
    for layer in ("silver", "gold"):
        for path in sorted((base / layer).glob("*/*.yml")):
            try:
                model = _load_model(path, layer)
            except SpecError as exc:
                errors.append((rel(path, root), str(exc)))
                continue
            if model.key in models:
                errors.append((rel(path, root),
                               f"{model.key} is defined twice"))
            models[model.key] = model
        for path in sorted((base / layer).glob("*/*.sql")):
            if not path.with_suffix(".yml").exists():
                errors.append((rel(path, root),
                               "SQL file has no matching .yml spec"))
    agents: Dict[str, Agent] = {}
    for path in sorted((base / "agents").glob("*.yml")):
        try:
            agents[path.stem] = Agent(name=path.stem, path=path,
                                      spec=_read_yaml(path))
        except SpecError as exc:
            errors.append((rel(path, root), str(exc)))
    return Project(config=config, sources=sources, models=models,
                   errors=errors, agents=agents)


def rel(path: Path, root: Path) -> str:
    """Return a path relative to the project root, with forward slashes.

    Args:
        path: Any path inside the project.
        root: Project root folder.

    Returns:
        The relative path as text.
    """
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def snake(name: str) -> str:
    """Convert PascalCase to snake_case.

    Args:
        name: A PascalCase name such as ``NewBusiness``.

    Returns:
        The snake_case form, e.g. ``new_business``.
    """
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", text)
    return text.lower()


def identifiers(expression: str) -> List[str]:
    """Return the bare identifiers in a SQL expression (lower case).

    Args:
        expression: A Spark or T-SQL expression.

    Returns:
        Identifier tokens outside string literals, lower-cased.
    """
    text = re.sub(r"'[^']*'", "", expression or "")
    return [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)]
