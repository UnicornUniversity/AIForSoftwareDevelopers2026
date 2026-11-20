"""Universal Database Access - classroom demo package."""

from uda.candidate import CandidateRejectedError, build_candidate
from uda.fixtures import load_demo_schema
from uda.models import (
    AttributeMapping,
    Candidate,
    Column,
    ConceptProposal,
    TableSchema,
)
from uda.provider import ProviderConfigurationError, build_deepseek_model
from uda.schema import (
    FixtureCatalog,
    FixtureSchemaProvider,
    SchemaProvider,
    UnknownTableError,
    load_fixture_catalog,
    schema_version,
)
from uda.sqlserver import (
    SqlServerConfigurationError,
    SqlServerError,
    SqlServerInspectionError,
    SqlServerSchemaProvider,
    connection_url_from_env,
    engine_from_env,
    inspect_table,
    table_schema_from_columns,
)
from uda.storage import CandidateStorageError, save_candidate
from uda.validation import (
    ValidationIssue,
    canonicalize_proposal,
    validate_candidate,
    validate_proposal,
)
from uda.workflow import WorkflowResult, run_workflow

__all__ = [
    "AttributeMapping",
    "Candidate",
    "CandidateRejectedError",
    "CandidateStorageError",
    "Column",
    "ConceptProposal",
    "FixtureCatalog",
    "FixtureSchemaProvider",
    "ProviderConfigurationError",
    "SchemaProvider",
    "SqlServerConfigurationError",
    "SqlServerError",
    "SqlServerInspectionError",
    "SqlServerSchemaProvider",
    "TableSchema",
    "UnknownTableError",
    "ValidationIssue",
    "WorkflowResult",
    "build_candidate",
    "build_deepseek_model",
    "canonicalize_proposal",
    "connection_url_from_env",
    "engine_from_env",
    "inspect_table",
    "load_demo_schema",
    "load_fixture_catalog",
    "run_workflow",
    "save_candidate",
    "schema_version",
    "table_schema_from_columns",
    "validate_candidate",
    "validate_proposal",
]

__version__ = "0.5.0"
