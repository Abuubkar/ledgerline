from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.problem_code import ProblemCode
from ..types import UNSET, Unset

T = TypeVar("T", bound="Problem")


@_attrs_define
class Problem:
    """
    Attributes:
        type_ (str): A URI identifying the problem type.
        title (str):
        status (int):
        code (ProblemCode):
        detail (None | str | Unset):
        duplicate_of (None | Unset | UUID): For `duplicate_invoice`, the id of the invoice already stored.
        duplicate_of_url (None | str | Unset): For `duplicate_invoice`, the path of the invoice already stored.
    """

    type_: str
    title: str
    status: int
    code: ProblemCode
    detail: None | str | Unset = UNSET
    duplicate_of: None | Unset | UUID = UNSET
    duplicate_of_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        title = self.title

        status = self.status

        code = self.code.value

        detail: None | str | Unset
        if isinstance(self.detail, Unset):
            detail = UNSET
        else:
            detail = self.detail

        duplicate_of: None | str | Unset
        if isinstance(self.duplicate_of, Unset):
            duplicate_of = UNSET
        elif isinstance(self.duplicate_of, UUID):
            duplicate_of = str(self.duplicate_of)
        else:
            duplicate_of = self.duplicate_of

        duplicate_of_url: None | str | Unset
        if isinstance(self.duplicate_of_url, Unset):
            duplicate_of_url = UNSET
        else:
            duplicate_of_url = self.duplicate_of_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "title": title,
                "status": status,
                "code": code,
            }
        )
        if detail is not UNSET:
            field_dict["detail"] = detail
        if duplicate_of is not UNSET:
            field_dict["duplicate_of"] = duplicate_of
        if duplicate_of_url is not UNSET:
            field_dict["duplicate_of_url"] = duplicate_of_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = d.pop("type")

        title = d.pop("title")

        status = d.pop("status")

        code = ProblemCode(d.pop("code"))

        def _parse_detail(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        detail = _parse_detail(d.pop("detail", UNSET))

        def _parse_duplicate_of(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                duplicate_of_type_0 = UUID(data)

                return duplicate_of_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        duplicate_of = _parse_duplicate_of(d.pop("duplicate_of", UNSET))

        def _parse_duplicate_of_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        duplicate_of_url = _parse_duplicate_of_url(d.pop("duplicate_of_url", UNSET))

        problem = cls(
            type_=type_,
            title=title,
            status=status,
            code=code,
            detail=detail,
            duplicate_of=duplicate_of,
            duplicate_of_url=duplicate_of_url,
        )

        problem.additional_properties = d
        return problem

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
