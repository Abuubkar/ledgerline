import random

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from ledgerline_api.errors import PermanentError, TransientError, classify
from ledgerline_api.extraction import ExtractionError
from ledgerline_api.worker import backoff_seconds


def s3_error(code: str, status: int) -> ClientError:
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "GetObject")


@pytest.mark.parametrize(
    ("exc", "kind", "code"),
    [
        (ExtractionError("model_unavailable", "connection refused"), TransientError, "model_unavailable"),
        (ExtractionError("model_timeout", "180s"), TransientError, "model_timeout"),
        (ExtractionError("unreadable_pdf", "PDFSyntaxError"), PermanentError, "unreadable_pdf"),
        (ExtractionError("invalid_model_output", "bad JSON"), PermanentError, "invalid_model_output"),
        (ExtractionError("prompt_truncated", "too long"), PermanentError, "prompt_truncated"),
        (ExtractionError("no_text_layer", "scan"), PermanentError, "no_text_layer"),
        (s3_error("SlowDown", 503), TransientError, "storage_error"),
        (s3_error("InternalError", 500), TransientError, "storage_error"),
        (s3_error("NoSuchKey", 404), PermanentError, "storage_object_unavailable"),
        (s3_error("AccessDenied", 403), PermanentError, "storage_object_unavailable"),
        (EndpointConnectionError(endpoint_url="http://seaweedfs:8333"), TransientError, "dependency_unavailable"),
        (ConnectionError("redis down"), TransientError, "dependency_unavailable"),
        (KeyError("bug"), PermanentError, "unexpected_error"),  # bugs aren't retried; they surface in the DLQ
    ],
)
def test_failures_are_classified(exc, kind, code):
    error = classify(exc)
    assert isinstance(error, kind)
    assert error.code == code


def test_backoff_grows_exponentially_and_is_capped():
    random.seed(0)
    for retries in range(10):
        bound = min(300, 2.0 * 2**retries)
        samples = [backoff_seconds(retries, base=2.0, cap=300) for _ in range(200)]
        assert all(0 <= s <= bound for s in samples)
        # Full jitter: waits spread across the whole range, not bunched at the bound.
        assert min(samples) < bound * 0.2 and max(samples) > bound * 0.8


@pytest.mark.parametrize(
    "error",
    [TransientError("model_unavailable", "down"), PermanentError("unreadable_pdf", "bad"), ExtractionError("x", "y")],
)
def test_errors_survive_pickling(error):
    # Celery pickles exceptions; one that can't be rebuilt reaches on_failure as a wrapper and loses its code.
    import pickle

    restored = pickle.loads(pickle.dumps(error))
    assert type(restored) is type(error)
    assert (restored.code, restored.detail, str(restored)) == (error.code, error.detail, str(error))
