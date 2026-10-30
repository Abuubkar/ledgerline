from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.invoice import Invoice
from ...models.multi_status import MultiStatus
from ...models.problem import Problem
from ...models.upload_invoices_body import UploadInvoicesBody
from ...types import Response


def _get_kwargs(
    *,
    body: UploadInvoicesBody,
    idempotency_key: str,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    headers["Idempotency-Key"] = idempotency_key

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/invoices",
    }

    _kwargs["files"] = body.to_multipart()

    headers["Content-Type"] = "multipart/form-data; boundary=+++"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Invoice | MultiStatus | Problem | None:
    if response.status_code == 201:
        response_201 = Invoice.from_dict(response.json())

        return response_201

    if response.status_code == 207:
        response_207 = MultiStatus.from_dict(response.json())

        return response_207

    if response.status_code == 400:
        response_400 = Problem.from_dict(response.json())

        return response_400

    if response.status_code == 409:
        response_409 = Problem.from_dict(response.json())

        return response_409

    if response.status_code == 415:
        response_415 = Problem.from_dict(response.json())

        return response_415

    if response.status_code == 422:
        response_422 = Problem.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Invoice | MultiStatus | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: UploadInvoicesBody,
    idempotency_key: str,
) -> Response[Invoice | MultiStatus | Problem]:
    """Upload 1–10 invoice PDFs and extract their header fields

     Extraction runs synchronously for now (about 25 s per invoice on the reference machine), so one
    request carries at most 10 files. One file returns 201 (or an error status); several return 207
    with one result per file, so a bad file never fails the others.

    A file whose content is already stored (same normalized text, or the same bytes for PDFs without
    a text layer) is a duplicate: 409 with a link to the original. Failed extractions don't count as
    duplicates, so the same invoice can be re-uploaded after a model outage.

    Args:
        idempotency_key (str):
        body (UploadInvoicesBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Invoice | MultiStatus | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
        idempotency_key=idempotency_key,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: UploadInvoicesBody,
    idempotency_key: str,
) -> Invoice | MultiStatus | Problem | None:
    """Upload 1–10 invoice PDFs and extract their header fields

     Extraction runs synchronously for now (about 25 s per invoice on the reference machine), so one
    request carries at most 10 files. One file returns 201 (or an error status); several return 207
    with one result per file, so a bad file never fails the others.

    A file whose content is already stored (same normalized text, or the same bytes for PDFs without
    a text layer) is a duplicate: 409 with a link to the original. Failed extractions don't count as
    duplicates, so the same invoice can be re-uploaded after a model outage.

    Args:
        idempotency_key (str):
        body (UploadInvoicesBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Invoice | MultiStatus | Problem
    """

    return sync_detailed(
        client=client,
        body=body,
        idempotency_key=idempotency_key,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: UploadInvoicesBody,
    idempotency_key: str,
) -> Response[Invoice | MultiStatus | Problem]:
    """Upload 1–10 invoice PDFs and extract their header fields

     Extraction runs synchronously for now (about 25 s per invoice on the reference machine), so one
    request carries at most 10 files. One file returns 201 (or an error status); several return 207
    with one result per file, so a bad file never fails the others.

    A file whose content is already stored (same normalized text, or the same bytes for PDFs without
    a text layer) is a duplicate: 409 with a link to the original. Failed extractions don't count as
    duplicates, so the same invoice can be re-uploaded after a model outage.

    Args:
        idempotency_key (str):
        body (UploadInvoicesBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Invoice | MultiStatus | Problem]
    """

    kwargs = _get_kwargs(
        body=body,
        idempotency_key=idempotency_key,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: UploadInvoicesBody,
    idempotency_key: str,
) -> Invoice | MultiStatus | Problem | None:
    """Upload 1–10 invoice PDFs and extract their header fields

     Extraction runs synchronously for now (about 25 s per invoice on the reference machine), so one
    request carries at most 10 files. One file returns 201 (or an error status); several return 207
    with one result per file, so a bad file never fails the others.

    A file whose content is already stored (same normalized text, or the same bytes for PDFs without
    a text layer) is a duplicate: 409 with a link to the original. Failed extractions don't count as
    duplicates, so the same invoice can be re-uploaded after a model outage.

    Args:
        idempotency_key (str):
        body (UploadInvoicesBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Invoice | MultiStatus | Problem
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            idempotency_key=idempotency_key,
        )
    ).parsed
