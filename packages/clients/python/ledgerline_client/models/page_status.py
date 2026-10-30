from enum import StrEnum


class PageStatus(StrEnum):
    BLANK = "blank"
    EXTRACTED = "extracted"
    FAILED = "failed"

    def __str__(self) -> str:
        return str(self.value)
