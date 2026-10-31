from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.pending_action_action_type import PendingActionActionType
from ..models.pending_action_status import PendingActionStatus

if TYPE_CHECKING:
    from ..models.pending_action_details import PendingActionDetails


T = TypeVar("T", bound="PendingAction")


@_attrs_define
class PendingAction:
    """What the exception agent proposes for an invoice, waiting for a person. `details` for
    credit_memo_request: amount_minor, currency, lines, reason (the amount is computed in code from the PO
    and receipts, never by the model). For hold: reason_code, explanation.

        Attributes:
            id (UUID):
            invoice_id (UUID):
            agent_run_id (UUID):
            action_type (PendingActionActionType):
            status (PendingActionStatus):
            details (PendingActionDetails):
            version (int): Goes up with every change; the ETag.
            decision_note (None | str):
            created_at (datetime.datetime):
            decided_at (datetime.datetime | None):
    """

    id: UUID
    invoice_id: UUID
    agent_run_id: UUID
    action_type: PendingActionActionType
    status: PendingActionStatus
    details: PendingActionDetails
    version: int
    decision_note: None | str
    created_at: datetime.datetime
    decided_at: datetime.datetime | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        invoice_id = str(self.invoice_id)

        agent_run_id = str(self.agent_run_id)

        action_type = self.action_type.value

        status = self.status.value

        details = self.details.to_dict()

        version = self.version

        decision_note: None | str
        decision_note = self.decision_note

        created_at = self.created_at.isoformat()

        decided_at: None | str
        if isinstance(self.decided_at, datetime.datetime):
            decided_at = self.decided_at.isoformat()
        else:
            decided_at = self.decided_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "invoice_id": invoice_id,
                "agent_run_id": agent_run_id,
                "action_type": action_type,
                "status": status,
                "details": details,
                "version": version,
                "decision_note": decision_note,
                "created_at": created_at,
                "decided_at": decided_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.pending_action_details import PendingActionDetails  # noqa: PLC0415

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        invoice_id = UUID(d.pop("invoice_id"))

        agent_run_id = UUID(d.pop("agent_run_id"))

        action_type = PendingActionActionType(d.pop("action_type"))

        status = PendingActionStatus(d.pop("status"))

        details = PendingActionDetails.from_dict(d.pop("details"))

        version = d.pop("version")

        def _parse_decision_note(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        decision_note = _parse_decision_note(d.pop("decision_note"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        def _parse_decided_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                decided_at_type_0 = datetime.datetime.fromisoformat(data)

                return decided_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        decided_at = _parse_decided_at(d.pop("decided_at"))

        pending_action = cls(
            id=id,
            invoice_id=invoice_id,
            agent_run_id=agent_run_id,
            action_type=action_type,
            status=status,
            details=details,
            version=version,
            decision_note=decision_note,
            created_at=created_at,
            decided_at=decided_at,
        )

        pending_action.additional_properties = d
        return pending_action

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
