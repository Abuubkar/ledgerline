"""Which failures are worth retrying. Transient ones are retried with backoff; permanent ones go straight to
the dead-letter queue, because retrying a corrupt PDF only wastes model time."""

from botocore.exceptions import BotoCoreError, ClientError

from ledgerline_api.extraction import ExtractionError


class _CodedError(Exception):
    # Both values go to Exception.__init__ so `args` can rebuild the error: Celery pickles exceptions, and an
    # error that won't unpickle reaches on_failure as an UnpickleableExceptionWrapper.
    def __init__(self, code: str, detail: str):
        super().__init__(code, detail)
        self.code, self.detail = code, detail

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class TransientError(_CodedError):
    pass


class PermanentError(_CodedError):
    pass


# The model being unreachable or slow fixes itself; bad input or bad output doesn't (temperature is 0,
# so the same input gives the same output).
TRANSIENT_EXTRACTION_CODES = {"model_unavailable", "model_timeout"}

# S3 errors that mean "the object isn't there" rather than "the service is struggling".
PERMANENT_S3_CODES = {"NoSuchKey", "NoSuchBucket", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}


def classify(exc: BaseException) -> TransientError | PermanentError:
    if isinstance(exc, TransientError | PermanentError):
        return exc
    if isinstance(exc, ExtractionError):
        kind = TransientError if exc.code in TRANSIENT_EXTRACTION_CODES else PermanentError
        return kind(exc.code, exc.detail)
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        if code in PERMANENT_S3_CODES or (400 <= status < 500 and status not in (408, 429)):
            return PermanentError("storage_object_unavailable", f"{code} ({status})")
        return TransientError("storage_error", f"{code} ({status})")
    if isinstance(exc, BotoCoreError | ConnectionError | TimeoutError):
        return TransientError("dependency_unavailable", f"{type(exc).__name__}: {exc}")
    # Unknown errors are bugs; retrying won't fix them, so surface them in the dead-letter queue.
    return PermanentError("unexpected_error", f"{type(exc).__name__}: {exc}")
