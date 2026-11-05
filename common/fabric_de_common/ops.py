"""Operational helpers for the ops notebooks (Fabric REST calls)."""

from __future__ import annotations

import time


def refresh_sql_endpoint(lakehouse: str, timeout_seconds: int = 600) -> None:
    """Refresh the SQL analytics endpoint metadata of a lakehouse.

    The endpoint syncs Delta metadata asynchronously. Gold loads and tests
    read silver through it, so the pipeline refreshes it after silver.
    [Spike] confirm the refreshMetadata API in your tenant.

    Args:
        lakehouse: Lakehouse name in the current workspace.
        timeout_seconds: How long to wait for the refresh to finish.

    Raises:
        RuntimeError: If the refresh fails or does not finish in time.
    """
    import sempy.fabric as fabric

    client = fabric.FabricRestClient()
    workspace = fabric.get_workspace_id()
    endpoint = fabric.resolve_item_id(lakehouse, type="SQLEndpoint")
    response = client.post(
        f"v1/workspaces/{workspace}/sqlEndpoints/{endpoint}/refreshMetadata",
        json={})
    if response.status_code == 200:
        return
    if response.status_code != 202:
        raise RuntimeError(f"refreshMetadata failed: {response.status_code} "
                           f"{response.text}")
    location = response.headers.get("Location")
    deadline = time.time() + timeout_seconds
    while location and time.time() < deadline:
        time.sleep(int(response.headers.get("Retry-After", 5)))
        response = client.get(location)
        status = (response.json() or {}).get("status", "")
        if status in ("Succeeded", "Completed"):
            return
        if status in ("Failed", "Cancelled"):
            raise RuntimeError(f"refreshMetadata {status}: {response.text}")
    raise RuntimeError("refreshMetadata did not finish in time")
