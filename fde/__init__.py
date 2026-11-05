"""fde: the Fabric data engineering toolkit behind this kit.

It does for a Fabric Lakehouse + Warehouse project what dbt does for a dbt
project: it reads table specs (``models/``), checks them, renders the code
that Fabric runs (silver notebooks, gold views and stored procedures, data
quality procedures) and runs builds and tests against a workspace.

Run ``python -m fde --help`` for the commands.
"""

__version__ = "0.1.0"
