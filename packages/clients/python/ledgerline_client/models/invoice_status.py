from enum import StrEnum


class InvoiceStatus(StrEnum):
    EXTRACTED = "extracted"
    EXTRACTING = "extracting"
    FAILED = "failed"
    RECEIVED = "received"

    def __str__(self) -> str:
        return str(self.value)
