from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="Vendor")


@_attrs_define
class Vendor:
    """
    Attributes:
        id (UUID):
        name (str): The name as first seen; individual invoices may spell it differently.
        tax_id (None | str): Uppercase letters and digits only; country prefixes are kept (DE812345678).
    """

    id: UUID
    name: str
    tax_id: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        name = self.name

        tax_id: None | str
        tax_id = self.tax_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "tax_id": tax_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        name = d.pop("name")

        def _parse_tax_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        tax_id = _parse_tax_id(d.pop("tax_id"))

        vendor = cls(
            id=id,
            name=name,
            tax_id=tax_id,
        )

        vendor.additional_properties = d
        return vendor

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
