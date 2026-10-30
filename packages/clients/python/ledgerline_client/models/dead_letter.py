from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="DeadLetter")


@_attrs_define
class DeadLetter:
    """
    Attributes:
        id (UUID):
        task_name (str):
        invoice_id (UUID):
        error_code (str): Why the job gave up, e.g. unreadable_pdf, model_unavailable.
        exception_chain (str):
        attempts (int):
        created_at (datetime.datetime):
        replayed_at (datetime.datetime | None):
    """

    id: UUID
    task_name: str
    invoice_id: UUID
    error_code: str
    exception_chain: str
    attempts: int
    created_at: datetime.datetime
    replayed_at: datetime.datetime | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        task_name = self.task_name

        invoice_id = str(self.invoice_id)

        error_code = self.error_code

        exception_chain = self.exception_chain

        attempts = self.attempts

        created_at = self.created_at.isoformat()

        replayed_at: None | str
        if isinstance(self.replayed_at, datetime.datetime):
            replayed_at = self.replayed_at.isoformat()
        else:
            replayed_at = self.replayed_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "task_name": task_name,
                "invoice_id": invoice_id,
                "error_code": error_code,
                "exception_chain": exception_chain,
                "attempts": attempts,
                "created_at": created_at,
                "replayed_at": replayed_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        task_name = d.pop("task_name")

        invoice_id = UUID(d.pop("invoice_id"))

        error_code = d.pop("error_code")

        exception_chain = d.pop("exception_chain")

        attempts = d.pop("attempts")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        def _parse_replayed_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                replayed_at_type_0 = datetime.datetime.fromisoformat(data)

                return replayed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        replayed_at = _parse_replayed_at(d.pop("replayed_at"))

        dead_letter = cls(
            id=id,
            task_name=task_name,
            invoice_id=invoice_id,
            error_code=error_code,
            exception_chain=exception_chain,
            attempts=attempts,
            created_at=created_at,
            replayed_at=replayed_at,
        )

        dead_letter.additional_properties = d
        return dead_letter

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
