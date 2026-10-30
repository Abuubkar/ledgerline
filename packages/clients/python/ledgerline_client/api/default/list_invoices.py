import datetime
from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.invoice_page import InvoicePage
from ...models.invoice_status import InvoiceStatus
from ...models.problem import Problem
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    limit: int | Unset = 25,
    cursor: None | str | Unset = UNSET,
    status: InvoiceStatus | None | Unset = UNSET,
    created_after: datetime.datetime | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    json_cursor: None | str | Unset
    if isinstance(cursor, Unset):
        json_cursor = UNSET
    else:
        json_cursor = cursor
    params["cursor"] = json_cursor

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    elif isinstance(status, InvoiceStatus):
        json_status = status.value
    else:
        json_status = status
    params["status"] = json_status

    json_created_after: None | str | Unset
    if isinstance(created_after, Unset):
        json_created_after = UNSET
    elif isinstance(created_after, datetime.datetime):
        json_created_after = created_after.isoformat()
    else:
        json_created_after = created_after
    params["created_after"] = json_created_after

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/invoices",
        "params": params,
    }

    return _kwargs


def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> InvoicePage | Problem | None:
    if response.status_code == 200:
        response_200 = InvoicePage.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = Problem.from_dict(response.json())

        return response_400

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[InvoicePage | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 25,
    cursor: None | str | Unset = UNSET,
    status: InvoiceStatus | None | Unset = UNSET,
    created_after: datetime.datetime | None | Unset = UNSET,
) -> Response[InvoicePage | Problem]:
    """List invoices, newest first, with keyset pagination

     Pass `next_cursor` from one page as `cursor` to get the next. Cursors are opaque, signed and bound
    to the filters they were issued with: a tampered cursor, or one reused with different filters, is
    rejected with 400 `invalid_cursor`.

    Args:
        limit (int | Unset):  Default: 25.
        cursor (None | str | Unset):
        status (InvoiceStatus | None | Unset):
        created_after (datetime.datetime | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[InvoicePage | Problem]
    """

    kwargs = _get_kwargs(
        limit=limit,
        cursor=cursor,
        status=status,
        created_after=created_after,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 25,
    cursor: None | str | Unset = UNSET,
    status: InvoiceStatus | None | Unset = UNSET,
    created_after: datetime.datetime | None | Unset = UNSET,
) -> InvoicePage | Problem | None:
    """List invoices, newest first, with keyset pagination

     Pass `next_cursor` from one page as `cursor` to get the next. Cursors are opaque, signed and bound
    to the filters they were issued with: a tampered cursor, or one reused with different filters, is
    rejected with 400 `invalid_cursor`.

    Args:
        limit (int | Unset):  Default: 25.
        cursor (None | str | Unset):
        status (InvoiceStatus | None | Unset):
        created_after (datetime.datetime | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        InvoicePage | Problem
    """

    return sync_detailed(
        client=client,
        limit=limit,
        cursor=cursor,
        status=status,
        created_after=created_after,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 25,
    cursor: None | str | Unset = UNSET,
    status: InvoiceStatus | None | Unset = UNSET,
    created_after: datetime.datetime | None | Unset = UNSET,
) -> Response[InvoicePage | Problem]:
    """List invoices, newest first, with keyset pagination

     Pass `next_cursor` from one page as `cursor` to get the next. Cursors are opaque, signed and bound
    to the filters they were issued with: a tampered cursor, or one reused with different filters, is
    rejected with 400 `invalid_cursor`.

    Args:
        limit (int | Unset):  Default: 25.
        cursor (None | str | Unset):
        status (InvoiceStatus | None | Unset):
        created_after (datetime.datetime | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[InvoicePage | Problem]
    """

    kwargs = _get_kwargs(
        limit=limit,
        cursor=cursor,
        status=status,
        created_after=created_after,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 25,
    cursor: None | str | Unset = UNSET,
    status: InvoiceStatus | None | Unset = UNSET,
    created_after: datetime.datetime | None | Unset = UNSET,
) -> InvoicePage | Problem | None:
    """List invoices, newest first, with keyset pagination

     Pass `next_cursor` from one page as `cursor` to get the next. Cursors are opaque, signed and bound
    to the filters they were issued with: a tampered cursor, or one reused with different filters, is
    rejected with 400 `invalid_cursor`.

    Args:
        limit (int | Unset):  Default: 25.
        cursor (None | str | Unset):
        status (InvoiceStatus | None | Unset):
        created_after (datetime.datetime | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        InvoicePage | Problem
    """

    return (
        await asyncio_detailed(
            client=client,
            limit=limit,
            cursor=cursor,
            status=status,
            created_after=created_after,
        )
    ).parsed
