"""Domain and service exception hierarchy for dgg-pm."""

from __future__ import annotations


class DggPmError(Exception):
    """Base exception for all domain and service errors in dgg-pm."""


class DomainError(DggPmError):
    """Base exception for domain logic and business rule violations."""


class ValidationError(DomainError, ValueError):
    """Raised when validation of entity attributes or input parameters fails."""


class EntityNotFoundError(DomainError):
    """Base exception raised when an entity cannot be found."""


class TaskNotFoundError(EntityNotFoundError):
    """Raised when a specified task does not exist."""


class ProjectNotFoundError(EntityNotFoundError):
    """Raised when a specified project does not exist."""


class TeamNotFoundError(EntityNotFoundError):
    """Raised when a specified team does not exist."""


class EntityAlreadyExistsError(DomainError):
    """Base exception raised when creating an entity that violates uniqueness."""


class ProjectAlreadyExistsError(EntityAlreadyExistsError, ValueError):
    """Raised when creating a project with a duplicate name or prefix."""


class TeamAlreadyExistsError(EntityAlreadyExistsError, ValueError):
    """Raised when creating a team with a duplicate name."""


class StaleVersionError(DomainError):
    """Raised when an optimistic concurrency update fails due to a version mismatch."""
