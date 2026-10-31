from enum import StrEnum


class MatchResultStatus(StrEnum):
    EXCEPTION = "exception"
    MATCHED = "matched"

    def __str__(self) -> str:
        return str(self.value)
