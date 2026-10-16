from app.domain.policies import DuplicateCandidate


class DomainError(Exception):
    """Base exception for expected business-rule failures."""


class PatientNotFoundError(DomainError):
    pass


class BranchNotFoundError(DomainError):
    pass


class DuplicatePatientIdentifierError(DomainError):
    pass


class PossibleDuplicatePatientError(DomainError):
    def __init__(self, candidates: list[DuplicateCandidate]) -> None:
        super().__init__("possible duplicate patient confirmation required")
        self.candidates = candidates


class InvalidPatientChangeError(DomainError):
    pass


class CatalogNotFoundError(DomainError):
    pass


class DuplicateCatalogCodeError(DomainError):
    pass


class InvalidCatalogOperationError(DomainError):
    pass


class OrderNotFoundError(DomainError):
    pass
