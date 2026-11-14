class DomainError(Exception):
    """A rule of the community was broken; the message is shown to the user. Maps to HTTP 400."""

    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code:
            self.status_code = status_code


class NotFound(DomainError):
    status_code = 404

    def __init__(self, message: str = "Not found."):
        super().__init__(message, 404)
