"""Connections to a Fabric workspace: T-SQL over TDS, and the Fabric REST API.

Sign-in uses ``azure-identity``'s ``DefaultAzureCredential``. That takes a
service principal from ``AZURE_TENANT_ID`` / ``AZURE_CLIENT_ID`` /
``AZURE_CLIENT_SECRET`` when they are set (CI and production), otherwise
your ``az login`` session, otherwise a browser sign-in. No token or secret
is ever stored in the repo.

Each target in ``fde.yml`` names the environment variables that hold its
workspace SQL endpoint and workspace id, so the repo holds no hosts or ids.
"""

from __future__ import annotations

import json
import os
import re
import struct
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from fde.project import Config

SQL_SCOPE = "https://database.windows.net/.default"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
FABRIC_API = "https://api.fabric.microsoft.com/v1"
WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|exec|execute|"
    r"grant|revoke|deny|into|commit|rollback|save|begin|set|waitfor|dbcc|"
    r"kill|shutdown|backup|restore|bulk|openrowset|openquery|"
    r"opendatasource|use|declare|xp_\w+|sp_\w+)\b", re.I)
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_credential = None


class TargetError(Exception):
    """Raised when a target is missing, incomplete or not allowed."""


def credential():
    """Return the shared Azure credential (created on first use).

    Returns:
        A ``DefaultAzureCredential`` that may open a browser sign-in.
    """
    global _credential
    if _credential is None:
        from azure.identity import DefaultAzureCredential
        _credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=False)
    return _credential


def target_settings(config: Config, target: str, writes: bool) -> Dict[str, str]:
    """Return the resolved settings of a target.

    Args:
        config: The project config.
        target: Target name, e.g. ``dev``.
        writes: True when the command changes the workspace.

    Returns:
        ``sql_endpoint`` and ``workspace_id`` (empty when not set).

    Raises:
        TargetError: If the target is unknown, its SQL endpoint variable is
            not set, or a write targets prod outside CI.
    """
    settings = config.targets.get(target)
    if settings is None:
        raise TargetError(f"target '{target}' is not in fde.yml")
    if writes and settings.get("protected") and \
            os.environ.get("FDE_ALLOW_PROTECTED") != "1":
        raise TargetError(
            f"target '{target}' is protected: only the release pipeline "
            "writes to it (it sets FDE_ALLOW_PROTECTED=1). Use dev.")
    resolved = {}
    for key in ("sql_endpoint", "workspace_id"):
        var = settings.get(f"{key}_env")
        resolved[key] = os.environ.get(var, "") if var else ""
        resolved[f"{key}_env"] = var or ""
    if not resolved["sql_endpoint"]:
        raise TargetError(
            f"set {resolved['sql_endpoint_env'] or 'the SQL endpoint variable'}"
            f" to the workspace SQL connection string host for '{target}' "
            "(Warehouse > Settings > SQL connection string)")
    return resolved


def sql_connection(config: Config, target: str, writes: bool = False):
    """Open a T-SQL connection to the gold Warehouse of a target.

    The Warehouse can read the bronze and silver SQL endpoints of the same
    workspace by three-part name, so one connection serves every layer.

    Args:
        config: The project config.
        target: Target name.
        writes: True when the caller will change objects.

    Returns:
        An open ``pyodbc`` connection with autocommit on.
    """
    import pyodbc

    settings = target_settings(config, target, writes)
    token = credential().get_token(SQL_SCOPE).token.encode("utf-16-le")
    packed = struct.pack(f"<I{len(token)}s", len(token), token)
    driver = os.environ.get("FDE_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    conn_str = (f"Driver={{{driver}}};Server={settings['sql_endpoint']},1433;"
                f"Database={config.gold_warehouse};Encrypt=yes;"
                "TrustServerCertificate=no;Connection Timeout=60")
    connection = pyodbc.connect(conn_str, attrs_before={1256: packed})
    connection.autocommit = True
    return connection


def query(connection, sql: str, limit: Optional[int] = None) -> List[Dict]:
    """Run a query and return the rows as dicts.

    Args:
        connection: Open connection.
        sql: One statement.
        limit: Maximum rows to fetch.

    Returns:
        Rows as column -> value.
    """
    cursor = connection.cursor()
    cursor.execute(sql)
    if cursor.description is None:
        return []
    names = [d[0] for d in cursor.description]
    rows = cursor.fetchmany(limit) if limit else cursor.fetchall()
    return [dict(zip(names, row)) for row in rows]


def _strip_literals(sql: str) -> str:
    """Blank out comments, strings and bracketed names in one pass.

    A single left-to-right scan, so a quote cannot hide a comment
    marker and a comment cannot hide a quote (``select '/*'; delete
    ...; select '*/'`` is seen as two statements, not one).

    Args:
        sql: Query text.

    Returns:
        The text with every comment, string literal and ``[name]`` /
        ``"name"`` identifier replaced by a space.

    Raises:
        TargetError: If a string, identifier or comment is not closed.
    """
    out, i, n = [], 0, len(sql)
    closers = {"'": "'", '"': '"', "[": "]"}
    while i < n:
        two = sql[i:i + 2]
        if two == "--":
            end = sql.find("\n", i)
            i = n if end < 0 else end
            out.append(" ")
        elif two == "/*":
            depth, i = 1, i + 2
            while i < n and depth:
                if sql[i:i + 2] == "/*":
                    depth, i = depth + 1, i + 2
                elif sql[i:i + 2] == "*/":
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                raise TargetError("unclosed comment")
            out.append(" ")
        elif sql[i] in closers or two.lower() == "n'":
            if two.lower() == "n'":
                i += 1
            close, i = closers[sql[i]], i + 1
            while True:
                end = sql.find(close, i)
                if end < 0:
                    raise TargetError("unclosed string or identifier")
                if sql[end + 1:end + 2] == close:   # doubled = escaped
                    i = end + 2
                    continue
                i = end + 1
                break
            out.append(" ")
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def assert_read_only(sql: str) -> None:
    """Refuse anything that is not a single read-only SELECT.

    This guards against mistakes, not against a hostile user: ``show``
    also runs inside a transaction that is always rolled back, and
    production reads use a principal with ``SELECT`` only.

    Args:
        sql: Query text.

    Raises:
        TargetError: If the text could change data or holds several
            statements.
    """
    if CONTROL_CHARS.search(sql):
        raise TargetError("control characters (including carriage returns) "
                          "are not allowed")
    text = _strip_literals(sql).strip().rstrip(";").strip()
    if ";" in text:
        raise TargetError("only one statement is allowed")
    if not re.match(r"^\s*(select|with)\b", text, re.I):
        raise TargetError("only SELECT (or WITH ... SELECT) is allowed")
    if WRITE_WORDS.search(text):
        raise TargetError("the query contains a write keyword; read-only only")


def read_only_query(connection, sql: str,
                    limit: Optional[int] = None) -> List[Dict]:
    """Run a checked SELECT inside a transaction that is rolled back.

    Args:
        connection: Open connection.
        sql: One SELECT statement.
        limit: Maximum rows to fetch.

    Returns:
        Rows as column -> value.
    """
    assert_read_only(sql)
    connection.autocommit = False
    try:
        return query(connection, sql, limit)
    finally:
        connection.rollback()
        connection.autocommit = True


def execute_batches(connection, script: str) -> int:
    """Run a T-SQL script made of ``GO``-separated batches.

    Args:
        connection: Open connection.
        script: Script text.

    Returns:
        The number of batches run.
    """
    batches = [b.strip() for b in re.split(r"^\s*GO\s*$", script,
                                           flags=re.M | re.I)]
    count = 0
    cursor = connection.cursor()
    for batch in batches:
        if not re.sub(r"--[^\n]*", "", batch).strip():
            continue
        cursor.execute(batch)
        while cursor.nextset():
            pass
        count += 1
    return count


def rest(method: str, url: str, body: Optional[dict] = None) -> tuple:
    """Call the Fabric REST API.

    Args:
        method: HTTP method.
        url: Full URL or a path under ``/v1``.
        body: JSON body.

    Returns:
        (status, headers, parsed JSON or None).

    Raises:
        TargetError: On an HTTP error, with the response text.
    """
    if not url.startswith("https://"):
        url = f"{FABRIC_API}/{url.lstrip('/')}"
    token = credential().get_token(FABRIC_SCOPE).token
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            parsed = json.loads(raw) if raw else None
            return response.status, dict(response.headers), parsed
    except urllib.error.HTTPError as exc:
        raise TargetError(f"Fabric API {method} {url} failed: {exc.code} "
                          f"{exc.read().decode(errors='replace')}") from exc


def find_item(workspace_id: str, name: str, item_type: str) -> str:
    """Return the id of a workspace item by name.

    Args:
        workspace_id: Workspace id.
        name: Item display name.
        item_type: Fabric item type, e.g. ``Notebook``.

    Returns:
        The item id.

    Raises:
        TargetError: If no such item exists.
    """
    _, _, body = rest("GET", f"workspaces/{workspace_id}/items?type={item_type}")
    for item in (body or {}).get("value", []):
        if item.get("displayName") == name:
            return item["id"]
    raise TargetError(f"{item_type} '{name}' not found in the workspace; "
                      "deploy first (python -m fde deploy)")


def run_notebook(workspace_id: str, name: str, parameters: Dict[str, Any],
                 timeout_seconds: int = 7200) -> str:
    """Run a notebook on demand and wait for it to finish.

    Args:
        workspace_id: Workspace id.
        name: Notebook name.
        parameters: Values for the notebook's parameters cell.
        timeout_seconds: How long to wait.

    Returns:
        The final job status (``Completed``).

    Raises:
        TargetError: If the run fails or times out.
    """
    item = find_item(workspace_id, name, "Notebook")
    body = {"executionData": {"parameters": {
        k: {"value": str(v), "type": "string"} for k, v in parameters.items()}}}
    _, headers, _ = rest(
        "POST", f"workspaces/{workspace_id}/items/{item}/jobs/instances"
                "?jobType=RunNotebook", body)
    location = headers.get("Location") or headers.get("location")
    if not location:
        raise TargetError("the Fabric API returned no job location")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(int(headers.get("Retry-After", 15)))
        _, headers, job = rest("GET", location)
        status = (job or {}).get("status", "")
        if status == "Completed":
            return status
        if status in ("Failed", "Cancelled", "Deduped"):
            reason = (job or {}).get("failureReason") or {}
            raise TargetError(f"notebook {name} {status}: "
                              f"{reason.get('message', job)}")
    raise TargetError(f"notebook {name} did not finish in "
                      f"{timeout_seconds} seconds")
