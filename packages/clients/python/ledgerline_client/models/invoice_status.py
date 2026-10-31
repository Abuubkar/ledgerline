from enum import StrEnum


class InvoiceStatus(StrEnum):
    EXCEPTION = "exception"
    EXTRACTED = "extracted"
    EXTRACTING = "extracting"
    FAILED = "failed"
    MATCHED = "matched"
    PARTIALLY_EXTRACTED = "partially_extracted"
    RECEIVED = "received"

    def __str__(self) -> str:
        return str(self.value)
