from enum import StrEnum


class PendingActionActionType(StrEnum):
    CREDIT_MEMO_REQUEST = "credit_memo_request"
    HOLD = "hold"

    def __str__(self) -> str:
        return str(self.value)
