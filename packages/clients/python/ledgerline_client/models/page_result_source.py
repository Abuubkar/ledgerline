from enum import StrEnum


class PageResultSource(StrEnum):
    IMAGE = "image"
    TEXT = "text"

    def __str__(self) -> str:
        return str(self.value)
