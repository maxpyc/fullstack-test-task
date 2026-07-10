import uuid
from collections.abc import Sequence
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Alert, StoredFile

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    def __init__(self, session: AsyncSession, model_class: type[ModelType]) -> None:
        self.session = session
        self.model_class = model_class

    async def get_by_id(self, id_: uuid.UUID | int) -> ModelType | None:
        return await self.session.get(self.model_class, id_)

    async def add(self, instance: ModelType) -> ModelType:
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def commit_changes(self) -> None:
        await self.session.commit()

    async def delete(self, instance: ModelType) -> None:
        await self.session.delete(instance)
        await self.session.commit()


class FileRepository(BaseRepository[StoredFile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, StoredFile)

    async def list_all(self) -> Sequence[StoredFile]:
        stmt = select(StoredFile).order_by(StoredFile.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()


class AlertRepository(BaseRepository[Alert]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Alert)

    async def list_all(self) -> Sequence[Alert]:
        stmt = select(Alert).order_by(Alert.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()
