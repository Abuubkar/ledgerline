from enum import StrEnum


class InvoiceStatus(StrEnum):
    EXTRACTED = "extracted"
    FAILED = "failed"

    def __str__(self) -> str:
        return str(self.value)
