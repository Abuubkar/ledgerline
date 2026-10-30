from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.dead_letter import DeadLetter
from ...models.problem import Problem
from ...types import Response


def _get_kwargs(
    dead_letter_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/admin/dead-letters/{dead_letter_id}/replay".format(
            dead_letter_id=quote(str(dead_letter_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> DeadLetter | Problem | None:
    if response.status_code == 200:
        response_200 = DeadLetter.from_dict(response.json())

        return response_200

    if response.status_code == 202:
        response_202 = DeadLetter.from_dict(response.json())

        return response_202

    if response.status_code == 400:
        response_400 = Problem.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = Problem.from_dict(response.json())

        return response_409

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[DeadLetter | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dead_letter_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Response[DeadLetter | Problem]:
    """Queue a dead-lettered job again with a fresh retry budget

     The invoice goes back to `received` and is extracted again. Replaying the same dead letter twice
    does nothing the second time: it returns 200 with the original `replayed_at`.

    Args:
        dead_letter_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeadLetter | Problem]
    """

    kwargs = _get_kwargs(
        dead_letter_id=dead_letter_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dead_letter_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> DeadLetter | Problem | None:
    """Queue a dead-lettered job again with a fresh retry budget

     The invoice goes back to `received` and is extracted again. Replaying the same dead letter twice
    does nothing the second time: it returns 200 with the original `replayed_at`.

    Args:
        dead_letter_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeadLetter | Problem
    """

    return sync_detailed(
        dead_letter_id=dead_letter_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    dead_letter_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> Response[DeadLetter | Problem]:
    """Queue a dead-lettered job again with a fresh retry budget

     The invoice goes back to `received` and is extracted again. Replaying the same dead letter twice
    does nothing the second time: it returns 200 with the original `replayed_at`.

    Args:
        dead_letter_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeadLetter | Problem]
    """

    kwargs = _get_kwargs(
        dead_letter_id=dead_letter_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dead_letter_id: UUID,
    *,
    client: AuthenticatedClient | Client,
) -> DeadLetter | Problem | None:
    """Queue a dead-lettered job again with a fresh retry budget

     The invoice goes back to `received` and is extracted again. Replaying the same dead letter twice
    does nothing the second time: it returns 200 with the original `replayed_at`.

    Args:
        dead_letter_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeadLetter | Problem
    """

    return (
        await asyncio_detailed(
            dead_letter_id=dead_letter_id,
            client=client,
        )
    ).parsed
