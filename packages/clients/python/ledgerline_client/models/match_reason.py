from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="MatchReason")


@_attrs_define
class MatchReason:
    """
    Attributes:
        code (str): po_missing, po_not_found, vendor_mismatch, currency_mismatch, not_received, no_lines,
            line_unreadable, line_not_on_po, price_variance, quantity_over_po, short_shipment,
            quantity_mismatch. New codes may be added.
        detail (str): For a person, e.g. "unit price 92.00 vs PO 89.50 (+2.79%, tolerance 1%)".
        line (None | str): The invoice line it concerns ("page 1 line 2"), or null for the whole invoice.
    """

    code: str
    detail: str
    line: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        code = self.code

        detail = self.detail

        line: None | str
        line = self.line

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "code": code,
                "detail": detail,
                "line": line,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        code = d.pop("code")

        detail = d.pop("detail")

        def _parse_line(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        line = _parse_line(d.pop("line"))

        match_reason = cls(
            code=code,
            detail=detail,
            line=line,
        )

        match_reason.additional_properties = d
        return match_reason

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
