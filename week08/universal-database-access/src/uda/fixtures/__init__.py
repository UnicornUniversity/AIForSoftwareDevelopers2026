"""Bundled schema fixtures used by the offline demo."""

from uda.models import TableSchema
from uda.schema import FixtureSchemaProvider


def load_demo_schema() -> TableSchema:
    """Load the legacy demo table (``dbo.Customer``) from the fixture catalog."""
    return FixtureSchemaProvider().load("Customer")
