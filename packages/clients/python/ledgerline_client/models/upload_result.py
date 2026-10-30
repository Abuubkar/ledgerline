from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.invoice import Invoice
    from ..models.problem import Problem


T = TypeVar("T", bound="UploadResult")


@_attrs_define
class UploadResult:
    """
    Attributes:
        filename (str):
        status (int): The HTTP status this file would have had on its own (202, 409, 415, ...).
        invoice (Invoice | None):
        problem (None | Problem):
    """

    filename: str
    status: int
    invoice: Invoice | None
    problem: None | Problem
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.invoice import Invoice  # noqa: PLC0415
        from ..models.problem import Problem  # noqa: PLC0415

        filename = self.filename

        status = self.status

        invoice: dict[str, Any] | None
        if isinstance(self.invoice, Invoice):
            invoice = self.invoice.to_dict()
        else:
            invoice = self.invoice

        problem: dict[str, Any] | None
        if isinstance(self.problem, Problem):
            problem = self.problem.to_dict()
        else:
            problem = self.problem

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "filename": filename,
                "status": status,
                "invoice": invoice,
                "problem": problem,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.invoice import Invoice  # noqa: PLC0415
        from ..models.problem import Problem  # noqa: PLC0415

        d = dict(src_dict)
        filename = d.pop("filename")

        status = d.pop("status")

        def _parse_invoice(data: object) -> Invoice | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                invoice_type_0 = Invoice.from_dict(data)

                return invoice_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(Invoice | None, data)

        invoice = _parse_invoice(d.pop("invoice"))

        def _parse_problem(data: object) -> None | Problem:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                problem_type_0 = Problem.from_dict(data)

                return problem_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Problem, data)

        problem = _parse_problem(d.pop("problem"))

        upload_result = cls(
            filename=filename,
            status=status,
            invoice=invoice,
            problem=problem,
        )

        upload_result.additional_properties = d
        return upload_result

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
