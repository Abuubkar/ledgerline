from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.decision import Decision
from ...models.pending_action import PendingAction
from ...models.problem import Problem
from ...types import UNSET, Response, Unset


def _get_kwargs(
    action_id: UUID,
    *,
    body: Decision | None | Unset = UNSET,
    if_match: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(if_match, Unset):
        headers["If-Match"] = if_match

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/pending-actions/{action_id}:approve".format(
            action_id=quote(str(action_id), safe=""),
        ),
    }

    if isinstance(body, Decision):
        _kwargs["json"] = body.to_dict()
    else:
        _kwargs["json"] = body

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> PendingAction | Problem | None:
    if response.status_code == 200:
        response_200 = PendingAction.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = Problem.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = Problem.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = Problem.from_dict(response.json())

        return response_409

    if response.status_code == 412:
        response_412 = Problem.from_dict(response.json())

        return response_412

    if response.status_code == 428:
        response_428 = Problem.from_dict(response.json())

        return response_428

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[PendingAction | Problem]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    action_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: Decision | None | Unset = UNSET,
    if_match: None | str | Unset = UNSET,
) -> Response[PendingAction | Problem]:
    """Approve a proposal at the version you saw

     Send the proposal's ETag in `If-Match`. If someone decided first, or the proposal changed, the
    answer is 412 with `current_version`; reload and decide again. Missing `If-Match` → 428; deciding
    an already decided proposal at its current version → 409. Recording the decision is all this does
    for now: nothing is sent to the vendor or the ERP.

    Args:
        action_id (UUID):
        if_match (None | str | Unset):
        body (Decision | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PendingAction | Problem]
    """

    kwargs = _get_kwargs(
        action_id=action_id,
        body=body,
        if_match=if_match,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    action_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: Decision | None | Unset = UNSET,
    if_match: None | str | Unset = UNSET,
) -> PendingAction | Problem | None:
    """Approve a proposal at the version you saw

     Send the proposal's ETag in `If-Match`. If someone decided first, or the proposal changed, the
    answer is 412 with `current_version`; reload and decide again. Missing `If-Match` → 428; deciding
    an already decided proposal at its current version → 409. Recording the decision is all this does
    for now: nothing is sent to the vendor or the ERP.

    Args:
        action_id (UUID):
        if_match (None | str | Unset):
        body (Decision | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PendingAction | Problem
    """

    return sync_detailed(
        action_id=action_id,
        client=client,
        body=body,
        if_match=if_match,
    ).parsed


async def asyncio_detailed(
    action_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: Decision | None | Unset = UNSET,
    if_match: None | str | Unset = UNSET,
) -> Response[PendingAction | Problem]:
    """Approve a proposal at the version you saw

     Send the proposal's ETag in `If-Match`. If someone decided first, or the proposal changed, the
    answer is 412 with `current_version`; reload and decide again. Missing `If-Match` → 428; deciding
    an already decided proposal at its current version → 409. Recording the decision is all this does
    for now: nothing is sent to the vendor or the ERP.

    Args:
        action_id (UUID):
        if_match (None | str | Unset):
        body (Decision | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PendingAction | Problem]
    """

    kwargs = _get_kwargs(
        action_id=action_id,
        body=body,
        if_match=if_match,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    action_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: Decision | None | Unset = UNSET,
    if_match: None | str | Unset = UNSET,
) -> PendingAction | Problem | None:
    """Approve a proposal at the version you saw

     Send the proposal's ETag in `If-Match`. If someone decided first, or the proposal changed, the
    answer is 412 with `current_version`; reload and decide again. Missing `If-Match` → 428; deciding
    an already decided proposal at its current version → 409. Recording the decision is all this does
    for now: nothing is sent to the vendor or the ERP.

    Args:
        action_id (UUID):
        if_match (None | str | Unset):
        body (Decision | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PendingAction | Problem
    """

    return (
        await asyncio_detailed(
            action_id=action_id,
            client=client,
            body=body,
            if_match=if_match,
        )
    ).parsed
