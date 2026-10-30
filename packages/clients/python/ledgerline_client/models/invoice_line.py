from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.money import Money


T = TypeVar("T", bound="InvoiceLine")


@_attrs_define
class InvoiceLine:
    """
    Attributes:
        page_no (int):
        line_no (int):
        description (None | str):
        quantity (None | str): Decimal as a string (e.g. "2.5"), so no precision is lost to JSON floats.
        unit_price (None | str): Decimal as a string; may have more decimals than the currency (e.g. "0.125").
        amount (Money | None):
        invalid_reason (None | str): Why a value on this line couldn't be used, if any.
    """

    page_no: int
    line_no: int
    description: None | str
    quantity: None | str
    unit_price: None | str
    amount: Money | None
    invalid_reason: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.money import Money  # noqa: PLC0415

        page_no = self.page_no

        line_no = self.line_no

        description: None | str
        description = self.description

        quantity: None | str
        quantity = self.quantity

        unit_price: None | str
        unit_price = self.unit_price

        amount: dict[str, Any] | None
        if isinstance(self.amount, Money):
            amount = self.amount.to_dict()
        else:
            amount = self.amount

        invalid_reason: None | str
        invalid_reason = self.invalid_reason

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "page_no": page_no,
                "line_no": line_no,
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": amount,
                "invalid_reason": invalid_reason,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.money import Money  # noqa: PLC0415

        d = dict(src_dict)
        page_no = d.pop("page_no")

        line_no = d.pop("line_no")

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        def _parse_quantity(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        quantity = _parse_quantity(d.pop("quantity"))

        def _parse_unit_price(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        unit_price = _parse_unit_price(d.pop("unit_price"))

        def _parse_amount(data: object) -> Money | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                amount_type_0 = Money.from_dict(data)

                return amount_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(Money | None, data)

        amount = _parse_amount(d.pop("amount"))

        def _parse_invalid_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        invalid_reason = _parse_invalid_reason(d.pop("invalid_reason"))

        invoice_line = cls(
            page_no=page_no,
            line_no=line_no,
            description=description,
            quantity=quantity,
            unit_price=unit_price,
            amount=amount,
            invalid_reason=invalid_reason,
        )

        invoice_line.additional_properties = d
        return invoice_line

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
