from harness.errors import ConflictError, NotFoundError


class ApprovalNotFoundError(NotFoundError):
    pass


class ApprovalNotPendingError(ConflictError):
    pass
