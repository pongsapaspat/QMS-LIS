class DomainError(Exception):
    """Base exception for expected business-rule failures."""


class PatientNotFoundError(DomainError):
    pass


class BranchNotFoundError(DomainError):
    pass


class DuplicatePatientIdentifierError(DomainError):
    pass
