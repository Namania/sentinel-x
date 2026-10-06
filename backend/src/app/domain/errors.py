class DomainError(Exception):
    """Base class for business rule violations."""


class EmailAlreadyUsed(DomainError):
    pass


class InvalidCredentials(DomainError):
    pass


class UserNotFound(DomainError):
    pass


class InvalidReading(DomainError):
    """A sensor reading violates the accepted bounds."""
