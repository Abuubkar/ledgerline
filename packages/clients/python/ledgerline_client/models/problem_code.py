from enum import StrEnum


class ProblemCode(StrEnum):
    DUPLICATE_INVOICE = "duplicate_invoice"
    IDEMPOTENCY_KEY_MISSING = "idempotency_key_missing"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    INVALID_CURSOR = "invalid_cursor"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    REQUEST_IN_PROGRESS = "request_in_progress"
    TOO_MANY_FILES = "too_many_files"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"

    def __str__(self) -> str:
        return str(self.value)
