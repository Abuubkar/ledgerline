from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.invoice_status import InvoiceStatus

if TYPE_CHECKING:
    from ..models.invoice_field_confidence_type_0 import InvoiceFieldConfidenceType0
    from ..models.invoice_invalid_fields_type_0 import InvoiceInvalidFieldsType0
    from ..models.invoice_line import InvoiceLine
    from ..models.money import Money
    from ..models.page_result import PageResult


T = TypeVar("T", bound="Invoice")


@_attrs_define
class Invoice:
    """
    Attributes:
        id (UUID):
        status (InvoiceStatus): received → extracting → extracted | partially_extracted | exception, or failed when the
            job is
            dead-lettered. Precedence when several apply: failed > partially_extracted > exception > extracted.
        original_filename (str):
        page_count (int | None):
        vendor_name (None | str):
        vendor_tax_id (None | str): Uppercase letters and digits only; country prefixes are kept (DE812345678).
        invoice_number (None | str):
        invoice_date (datetime.date | None):
        due_date (datetime.date | None):
        currency (None | str):
        subtotal (Money | None):
        tax (Money | None):
        total (Money | None):
        field_confidence (InvoiceFieldConfidenceType0 | None):
        invalid_fields (InvoiceInvalidFieldsType0 | None): Fields the model returned in a shape that couldn't be used,
            with the reason.
        error_code (None | str): Why extraction failed, when `status` is `failed`.
        error_detail (None | str):
        model (None | str):
        prompt_version (None | str):
        prompt_tokens (int | None):
        output_tokens (int | None):
        llm_ms (int | None): Total model time across all pages and any repair call.
        repair_attempted (bool): True when the totals didn't add up and the model was asked once to re-read them.
        pages (list[PageResult]):
        lines (list[InvoiceLine]):
        created_at (datetime.datetime):
    """

    id: UUID
    status: InvoiceStatus
    original_filename: str
    page_count: int | None
    vendor_name: None | str
    vendor_tax_id: None | str
    invoice_number: None | str
    invoice_date: datetime.date | None
    due_date: datetime.date | None
    currency: None | str
    subtotal: Money | None
    tax: Money | None
    total: Money | None
    field_confidence: InvoiceFieldConfidenceType0 | None
    invalid_fields: InvoiceInvalidFieldsType0 | None
    error_code: None | str
    error_detail: None | str
    model: None | str
    prompt_version: None | str
    prompt_tokens: int | None
    output_tokens: int | None
    llm_ms: int | None
    repair_attempted: bool
    pages: list[PageResult]
    lines: list[InvoiceLine]
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.invoice_field_confidence_type_0 import InvoiceFieldConfidenceType0  # noqa: PLC0415
        from ..models.invoice_invalid_fields_type_0 import InvoiceInvalidFieldsType0  # noqa: PLC0415
        from ..models.money import Money  # noqa: PLC0415

        id = str(self.id)

        status = self.status.value

        original_filename = self.original_filename

        page_count: int | None
        page_count = self.page_count

        vendor_name: None | str
        vendor_name = self.vendor_name

        vendor_tax_id: None | str
        vendor_tax_id = self.vendor_tax_id

        invoice_number: None | str
        invoice_number = self.invoice_number

        invoice_date: None | str
        if isinstance(self.invoice_date, datetime.date):
            invoice_date = self.invoice_date.isoformat()
        else:
            invoice_date = self.invoice_date

        due_date: None | str
        if isinstance(self.due_date, datetime.date):
            due_date = self.due_date.isoformat()
        else:
            due_date = self.due_date

        currency: None | str
        currency = self.currency

        subtotal: dict[str, Any] | None
        if isinstance(self.subtotal, Money):
            subtotal = self.subtotal.to_dict()
        else:
            subtotal = self.subtotal

        tax: dict[str, Any] | None
        if isinstance(self.tax, Money):
            tax = self.tax.to_dict()
        else:
            tax = self.tax

        total: dict[str, Any] | None
        if isinstance(self.total, Money):
            total = self.total.to_dict()
        else:
            total = self.total

        field_confidence: dict[str, Any] | None
        if isinstance(self.field_confidence, InvoiceFieldConfidenceType0):
            field_confidence = self.field_confidence.to_dict()
        else:
            field_confidence = self.field_confidence

        invalid_fields: dict[str, Any] | None
        if isinstance(self.invalid_fields, InvoiceInvalidFieldsType0):
            invalid_fields = self.invalid_fields.to_dict()
        else:
            invalid_fields = self.invalid_fields

        error_code: None | str
        error_code = self.error_code

        error_detail: None | str
        error_detail = self.error_detail

        model: None | str
        model = self.model

        prompt_version: None | str
        prompt_version = self.prompt_version

        prompt_tokens: int | None
        prompt_tokens = self.prompt_tokens

        output_tokens: int | None
        output_tokens = self.output_tokens

        llm_ms: int | None
        llm_ms = self.llm_ms

        repair_attempted = self.repair_attempted

        pages = []
        for pages_item_data in self.pages:
            pages_item = pages_item_data.to_dict()
            pages.append(pages_item)

        lines = []
        for lines_item_data in self.lines:
            lines_item = lines_item_data.to_dict()
            lines.append(lines_item)

        created_at = self.created_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "status": status,
                "original_filename": original_filename,
                "page_count": page_count,
                "vendor_name": vendor_name,
                "vendor_tax_id": vendor_tax_id,
                "invoice_number": invoice_number,
                "invoice_date": invoice_date,
                "due_date": due_date,
                "currency": currency,
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
                "field_confidence": field_confidence,
                "invalid_fields": invalid_fields,
                "error_code": error_code,
                "error_detail": error_detail,
                "model": model,
                "prompt_version": prompt_version,
                "prompt_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "llm_ms": llm_ms,
                "repair_attempted": repair_attempted,
                "pages": pages,
                "lines": lines,
                "created_at": created_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.invoice_field_confidence_type_0 import InvoiceFieldConfidenceType0  # noqa: PLC0415
        from ..models.invoice_invalid_fields_type_0 import InvoiceInvalidFieldsType0  # noqa: PLC0415
        from ..models.invoice_line import InvoiceLine  # noqa: PLC0415
        from ..models.money import Money  # noqa: PLC0415
        from ..models.page_result import PageResult  # noqa: PLC0415

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        status = InvoiceStatus(d.pop("status"))

        original_filename = d.pop("original_filename")

        def _parse_page_count(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        page_count = _parse_page_count(d.pop("page_count"))

        def _parse_vendor_name(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        vendor_name = _parse_vendor_name(d.pop("vendor_name"))

        def _parse_vendor_tax_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        vendor_tax_id = _parse_vendor_tax_id(d.pop("vendor_tax_id"))

        def _parse_invoice_number(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        invoice_number = _parse_invoice_number(d.pop("invoice_number"))

        def _parse_invoice_date(data: object) -> datetime.date | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                invoice_date_type_0 = datetime.date.fromisoformat(data)

                return invoice_date_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None, data)

        invoice_date = _parse_invoice_date(d.pop("invoice_date"))

        def _parse_due_date(data: object) -> datetime.date | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                due_date_type_0 = datetime.date.fromisoformat(data)

                return due_date_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None, data)

        due_date = _parse_due_date(d.pop("due_date"))

        def _parse_currency(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        currency = _parse_currency(d.pop("currency"))

        def _parse_subtotal(data: object) -> Money | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                subtotal_type_0 = Money.from_dict(data)

                return subtotal_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(Money | None, data)

        subtotal = _parse_subtotal(d.pop("subtotal"))

        def _parse_tax(data: object) -> Money | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                tax_type_0 = Money.from_dict(data)

                return tax_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(Money | None, data)

        tax = _parse_tax(d.pop("tax"))

        def _parse_total(data: object) -> Money | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                total_type_0 = Money.from_dict(data)

                return total_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(Money | None, data)

        total = _parse_total(d.pop("total"))

        def _parse_field_confidence(data: object) -> InvoiceFieldConfidenceType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                field_confidence_type_0 = InvoiceFieldConfidenceType0.from_dict(data)

                return field_confidence_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(InvoiceFieldConfidenceType0 | None, data)

        field_confidence = _parse_field_confidence(d.pop("field_confidence"))

        def _parse_invalid_fields(data: object) -> InvoiceInvalidFieldsType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                invalid_fields_type_0 = InvoiceInvalidFieldsType0.from_dict(data)

                return invalid_fields_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(InvoiceInvalidFieldsType0 | None, data)

        invalid_fields = _parse_invalid_fields(d.pop("invalid_fields"))

        def _parse_error_code(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error_code = _parse_error_code(d.pop("error_code"))

        def _parse_error_detail(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error_detail = _parse_error_detail(d.pop("error_detail"))

        def _parse_model(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        model = _parse_model(d.pop("model"))

        def _parse_prompt_version(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        prompt_version = _parse_prompt_version(d.pop("prompt_version"))

        def _parse_prompt_tokens(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        prompt_tokens = _parse_prompt_tokens(d.pop("prompt_tokens"))

        def _parse_output_tokens(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        output_tokens = _parse_output_tokens(d.pop("output_tokens"))

        def _parse_llm_ms(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        llm_ms = _parse_llm_ms(d.pop("llm_ms"))

        repair_attempted = d.pop("repair_attempted")

        pages = []
        _pages = d.pop("pages")
        for pages_item_data in _pages:
            pages_item = PageResult.from_dict(pages_item_data)

            pages.append(pages_item)

        lines = []
        _lines = d.pop("lines")
        for lines_item_data in _lines:
            lines_item = InvoiceLine.from_dict(lines_item_data)

            lines.append(lines_item)

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        invoice = cls(
            id=id,
            status=status,
            original_filename=original_filename,
            page_count=page_count,
            vendor_name=vendor_name,
            vendor_tax_id=vendor_tax_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            currency=currency,
            subtotal=subtotal,
            tax=tax,
            total=total,
            field_confidence=field_confidence,
            invalid_fields=invalid_fields,
            error_code=error_code,
            error_detail=error_detail,
            model=model,
            prompt_version=prompt_version,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            llm_ms=llm_ms,
            repair_attempted=repair_attempted,
            pages=pages,
            lines=lines,
            created_at=created_at,
        )

        invoice.additional_properties = d
        return invoice

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
