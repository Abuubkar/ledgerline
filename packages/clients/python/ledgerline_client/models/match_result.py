from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.match_result_status import MatchResultStatus

if TYPE_CHECKING:
    from ..models.match_reason import MatchReason


T = TypeVar("T", bound="MatchResult")


@_attrs_define
class MatchResult:
    """
    Attributes:
        status (MatchResultStatus):
        purchase_order_id (None | UUID): The purchase order the invoice was matched against; null when it wasn't found.
        reasons (list[MatchReason]): Why it didn't match; empty when matched.
        matched_at (datetime.datetime):
    """

    status: MatchResultStatus
    purchase_order_id: None | UUID
    reasons: list[MatchReason]
    matched_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status.value

        purchase_order_id: None | str
        if isinstance(self.purchase_order_id, UUID):
            purchase_order_id = str(self.purchase_order_id)
        else:
            purchase_order_id = self.purchase_order_id

        reasons = []
        for reasons_item_data in self.reasons:
            reasons_item = reasons_item_data.to_dict()
            reasons.append(reasons_item)

        matched_at = self.matched_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "status": status,
                "purchase_order_id": purchase_order_id,
                "reasons": reasons,
                "matched_at": matched_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.match_reason import MatchReason  # noqa: PLC0415

        d = dict(src_dict)
        status = MatchResultStatus(d.pop("status"))

        def _parse_purchase_order_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                purchase_order_id_type_0 = UUID(data)

                return purchase_order_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        purchase_order_id = _parse_purchase_order_id(d.pop("purchase_order_id"))

        reasons = []
        _reasons = d.pop("reasons")
        for reasons_item_data in _reasons:
            reasons_item = MatchReason.from_dict(reasons_item_data)

            reasons.append(reasons_item)

        matched_at = datetime.datetime.fromisoformat(d.pop("matched_at"))

        match_result = cls(
            status=status,
            purchase_order_id=purchase_order_id,
            reasons=reasons,
            matched_at=matched_at,
        )

        match_result.additional_properties = d
        return match_result

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
