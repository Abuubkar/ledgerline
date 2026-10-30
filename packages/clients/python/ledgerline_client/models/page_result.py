from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.page_result_source import PageResultSource
from ..models.page_status import PageStatus

T = TypeVar("T", bound="PageResult")


@_attrs_define
class PageResult:
    """
    Attributes:
        page_no (int):
        status (PageStatus): blank pages (e.g. the back of a scan) are skipped, not failed.
        source (PageResultSource): text when the page has a text layer; image when it was rendered and read visually.
        error_code (None | str):
        llm_ms (int | None):
    """

    page_no: int
    status: PageStatus
    source: PageResultSource
    error_code: None | str
    llm_ms: int | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        page_no = self.page_no

        status = self.status.value

        source = self.source.value

        error_code: None | str
        error_code = self.error_code

        llm_ms: int | None
        llm_ms = self.llm_ms

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "page_no": page_no,
                "status": status,
                "source": source,
                "error_code": error_code,
                "llm_ms": llm_ms,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        page_no = d.pop("page_no")

        status = PageStatus(d.pop("status"))

        source = PageResultSource(d.pop("source"))

        def _parse_error_code(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error_code = _parse_error_code(d.pop("error_code"))

        def _parse_llm_ms(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        llm_ms = _parse_llm_ms(d.pop("llm_ms"))

        page_result = cls(
            page_no=page_no,
            status=status,
            source=source,
            error_code=error_code,
            llm_ms=llm_ms,
        )

        page_result.additional_properties = d
        return page_result

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
