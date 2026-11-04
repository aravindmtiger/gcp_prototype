"""Knowledge Studio: structured tables (SQL Executor) and RAG corpora (Knowledge Retriever)."""

from fastapi import APIRouter, status
from sqlalchemy import select

from app.deps import Builder, DbSession, User
from app.models import KnowledgeSource
from app.schemas import KnowledgeSourceIn, KnowledgeSourceOut
from app.services.resources import get_owned

router = APIRouter(prefix="/api/v1/knowledge-sources", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeSourceOut])
async def list_sources(session: DbSession, user: User) -> list[KnowledgeSource]:
    statement = select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc())
    if not user.is_admin:
        statement = statement.where(KnowledgeSource.owner_email == user.email)
    return list((await session.execute(statement)).scalars().all())


@router.post("", response_model=KnowledgeSourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: KnowledgeSourceIn, session: DbSession, user: Builder
) -> KnowledgeSource:
    source = KnowledgeSource(
        owner_email=user.email,
        name=payload.name,
        kind=payload.kind,
        description=payload.description,
        config=payload.config,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@router.get("/{source_id}", response_model=KnowledgeSourceOut)
async def get_source(source_id: str, session: DbSession, user: User) -> KnowledgeSource:
    return await get_owned(session, KnowledgeSource, user, source_id, "Knowledge source")
