"""Authentication error types."""


class AuthenticationError(Exception):
    """Raised when authentication fails before crawling starts."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause
