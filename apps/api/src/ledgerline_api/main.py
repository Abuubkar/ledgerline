import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from ledgerline_api import service
from ledgerline_api.db import get_session
from ledgerline_api.graphql import graphql_router
from ledgerline_api.schemas import (
    ApiProblem,
    DeadLetter,
    DeadLetterPage,
    Invoice,
    InvoicePage,
    InvoiceStatus,
    MultiStatus,
    Problem,
    ProblemCode,
)

app = FastAPI(title="Ledgerline", version="0.2.0")
app.include_router(graphql_router, prefix="/graphql")

PROBLEM_JSON = "application/problem+json"
Session = Annotated[AsyncSession, Depends(get_session)]


def problem_response(problem: Problem, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(problem.model_dump(mode="json"), status_code=problem.status, media_type=PROBLEM_JSON, headers=headers)


@app.exception_handler(ApiProblem)
async def api_problem_handler(_: Request, exc: ApiProblem) -> JSONResponse:
    return problem_response(exc.problem, exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())
    return problem_response(ApiProblem(400, ProblemCode.INVALID_REQUEST, "Invalid request", details).problem)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = ProblemCode.NOT_FOUND if exc.status_code == 404 else ProblemCode.INVALID_REQUEST
    return problem_response(ApiProblem(exc.status_code, code, str(exc.detail)).problem)


def _problems(*statuses: int) -> dict:
    return {status: {"model": Problem, "description": "An RFC 9457 problem."} for status in statuses}


_default_openapi = app.openapi


def openapi_with_problem_json() -> dict:
    """FastAPI documents every response model as application/json and adds a 422 validation response to each
    route. Ours differ: errors are application/problem+json, and validation failures are 400 problems."""
    if app.openapi_schema is None:
        schema = _default_openapi()
        for operations in schema["paths"].values():
            for operation in operations.values():
                responses = operation.get("responses", {})
                if "HTTPValidationError" in str(responses.get("422", "")):
                    del responses["422"]
                for status, response in responses.items():
                    content = response.get("content", {})
                    if int(status) >= 400 and "application/json" in content:
                        response["content"] = {PROBLEM_JSON: content["application/json"]}
        for unused in ("HTTPValidationError", "ValidationError"):
            schema["components"]["schemas"].pop(unused, None)
    return app.openapi_schema


app.openapi = openapi_with_problem_json


@app.post(
    "/v1/invoices",
    operation_id="uploadInvoices",
    status_code=202,
    responses={
        202: {"model": Invoice, "description": "One file, stored and queued for extraction (status `received`)."},
        207: {"model": MultiStatus, "description": "Several files; one result per file, in upload order."},
        **_problems(400, 409, 415, 422, 429),
    },
)
async def upload_invoices(
    files: list[UploadFile],
    session: Session,
    # Checked by hand, not by FastAPI, so a missing key is 400 idempotency_key_missing as the draft asks.
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    if idempotency_key is None:
        raise ApiProblem(400, ProblemCode.IDEMPOTENCY_KEY_MISSING, "Idempotency-Key header required",
                         "send a client-generated UUID in Idempotency-Key so the upload can be retried safely")
    try:
        key = uuid.UUID(idempotency_key)
    except ValueError:
        raise ApiProblem(400, ProblemCode.INVALID_REQUEST, "Invalid Idempotency-Key", "must be a UUID") from None

    incoming = [
        service.IncomingFile(f.filename or "upload.pdf", f.content_type or "application/octet-stream", await f.read())
        for f in files
    ]
    result = await service.upload_invoices(session, incoming, key)
    headers = {"Idempotent-Replayed": "true"} if result.replayed else None
    media_type = PROBLEM_JSON if result.status >= 400 else "application/json"
    return JSONResponse(result.body, status_code=result.status, media_type=media_type, headers=headers)


@app.get("/v1/invoices", operation_id="listInvoices", responses=_problems(400))
async def list_invoices(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
    status: InvoiceStatus | None = None,
    created_after: datetime | None = None,
) -> InvoicePage:
    page = await service.list_invoices(session, limit, cursor, status, created_after)
    return InvoicePage(data=[Invoice.from_row(row) for row in page.items], next_cursor=page.next_cursor)


@app.get("/v1/invoices/{invoice_id}", operation_id="getInvoice", responses=_problems(400, 404))
async def get_invoice(invoice_id: uuid.UUID, session: Session) -> Invoice:
    invoice = await service.get_invoice(session, invoice_id)
    if invoice is None:
        raise ApiProblem(404, ProblemCode.NOT_FOUND, "Invoice not found", f"no invoice with id {invoice_id}")
    return Invoice.from_row(invoice)


@app.get("/v1/admin/dead-letters", operation_id="listDeadLetters", responses=_problems(400))
async def list_dead_letters(
    session: Session, limit: Annotated[int, Query(ge=1, le=100)] = 25, cursor: str | None = None
) -> DeadLetterPage:
    page = await service.list_dead_letters(session, limit, cursor)
    return DeadLetterPage(data=[DeadLetter.from_row(row) for row in page.items], next_cursor=page.next_cursor)


@app.post(
    "/v1/admin/dead-letters/{dead_letter_id}/replay",
    operation_id="replayDeadLetter",
    status_code=202,
    responses={
        202: {"model": DeadLetter, "description": "Queued again."},
        200: {"model": DeadLetter, "description": "Already replayed earlier; nothing was queued."},
        **_problems(400, 404, 409),
    },
)
async def replay_dead_letter(dead_letter_id: uuid.UUID, session: Session) -> JSONResponse:
    row, replayed_now = await service.replay_dead_letter(session, dead_letter_id)
    return JSONResponse(DeadLetter.from_row(row).model_dump(mode="json"), status_code=202 if replayed_now else 200)
