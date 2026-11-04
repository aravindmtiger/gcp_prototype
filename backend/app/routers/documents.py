"""Knowledge-base ingestion: paste text or upload a plain-text file into a collection."""

import re

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.deps import Builder, DbSession
from app.errors import log_error, sanitize_error_for_user
from app.schemas import DocumentIn, IngestResult
from app.services import knowledge
from app.services.llm import get_llm_client
from app.services.storage import get_object_storage, make_object_key

router = APIRouter(prefix="/api/v1/collections/{collection}", tags=["documents"])

COLLECTION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
ALLOWED_UPLOAD_TYPES = {"text/plain", "text/markdown", "text/csv"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _validate_collection(collection: str) -> None:
    if not COLLECTION_PATTERN.match(collection):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid collection name")


@router.post("/documents", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
async def ingest_document(
    collection: str, payload: DocumentIn, session: DbSession, user: Builder
) -> IngestResult:
    _validate_collection(collection)
    return await _ingest(session, user.email, collection, payload.source, payload.text)


@router.post("/files", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
async def upload_file(
    collection: str,
    session: DbSession,
    user: Builder,
    file: UploadFile = File(...),
) -> IngestResult:
    _validate_collection(collection)
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only text, markdown or CSV files"
        )

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds 5 MB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "File must be UTF-8 text"
        ) from exc

    # Keep the original upload in object storage (GCS in production) for audit and re-indexing.
    storage = get_object_storage()
    try:
        await storage.put(
            make_object_key(collection, file.filename or "upload"), data, content_type
        )
    except Exception as exc:
        error_id = log_error(exc, context={"operation": "store_upload", "collection": collection})
        raise HTTPException(500, sanitize_error_for_user(exc, error_id)) from exc

    return await _ingest(session, user.email, collection, file.filename or "upload", text)


async def _ingest(
    session: DbSession, owner_email: str, collection: str, source: str, text: str
) -> IngestResult:
    try:
        chunks = await knowledge.ingest_text(
            session,
            get_llm_client(),
            owner_email=owner_email,
            collection=collection,
            source=source,
            text=text,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        error_id = log_error(exc, context={"operation": "ingest", "collection": collection})
        raise HTTPException(500, sanitize_error_for_user(exc, error_id)) from exc
    return IngestResult(collection=collection, source=source, chunks=chunks)
