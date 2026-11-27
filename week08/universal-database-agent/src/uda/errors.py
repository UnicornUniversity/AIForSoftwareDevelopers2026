"""Project-specific error types."""

from __future__ import annotations

from collections.abc import Sequence


class UDAError(Exception):
    """Base class for all UDA errors."""


class ConfigurationError(UDAError):
    """Invalid or missing configuration. Messages never include secret values."""


class AdapterError(UDAError):
    """A database-adapter operation failed."""


class AdapterConfigurationError(ConfigurationError):
    """Database connection settings are incomplete or contradictory."""


class AdapterConnectionError(AdapterError):
    """The database connection could not be established."""


class AdapterPermissionError(AdapterError):
    """The database login lacks permission for a metadata operation."""


class AdapterMetadataError(AdapterError):
    """Database metadata could not be read."""


class UnsupportedCapabilityError(AdapterError):
    """The adapter does not implement this capability in the current phase."""


class RepositoryError(UDAError):
    """A Knowledge Repository operation failed."""


class RepositoryValidationError(RepositoryError):
    """A repository snapshot is incomplete, inconsistent, or unsafe to publish."""


class RepositoryWriteError(RepositoryError):
    """A repository snapshot could not be written."""


class RepositoryPathError(RepositoryValidationError):
    """A repository path would escape the managed repository root."""


class FixtureError(UDAError):
    """A recorded metadata fixture could not be read."""


class TracingError(UDAError):
    """Tracing could not be configured or emitted."""


class GraphError(UDAError):
    """The query graph could not be built or executed."""


class DiscoveryError(UDAError):
    """Structure-first semantic discovery failed."""


class DiscoveryInputError(DiscoveryError):
    """The physical evidence required for discovery is missing or unusable."""


class ProposalValidationError(DiscoveryError):
    """LLM-generated proposals failed schema or semantic validation."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__(
            "Proposal validation failed: " + "; ".join(self.errors)
        )


class ProposalRepositoryError(RepositoryError):
    """A proposal repository operation failed."""


class ProposalRepositoryValidationError(ProposalRepositoryError):
    """An existing proposal repository is invalid or internally inconsistent."""


class ProposalRepositoryWriteError(ProposalRepositoryError):
    """Proposal records could not be written safely."""


class LLMProviderError(UDAError):
    """A live LLM provider call failed; messages never contain secrets."""


class CandidateRepositoryError(DiscoveryError):
    """An object-level discovery candidate store operation failed."""


class CandidateRepositoryValidationError(CandidateRepositoryError):
    """A stored candidate or candidate repository record is invalid."""


class CandidateRepositoryWriteError(CandidateRepositoryError):
    """A candidate record could not be written safely."""
