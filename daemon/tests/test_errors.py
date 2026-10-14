from nestd.errors import ConflictError, InvalidInputError, NestError, NotFoundError


def test_error_classes_carry_http_status_and_detail() -> None:
    assert NotFoundError("no such thing").status_code == 404
    assert ConflictError("busy").status_code == 409
    assert InvalidInputError("bad").status_code == 422
    assert issubclass(NotFoundError, NestError)
    assert ConflictError("busy").payload() == {"detail": "busy"}
