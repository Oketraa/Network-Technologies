from pathlib import Path
from typing import Generic, TypeVar

from beanie import Document, PydanticObjectId, init_beanie
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo import AsyncMongoClient

from models.events import Event
from models.users import User


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8", extra="ignore")
    DATABASE_URL: str = Field(default="mongodb://127.0.0.1:27017/planner", repr=False)

    async def initialize_database(self):
        client = AsyncMongoClient(self.DATABASE_URL, serverSelectionTimeoutMS=5000)
        try:
            database = client.get_default_database()
            await database.command("ping")
            await init_beanie(database=database, document_models=[Event, User])
        except Exception:
            await client.close()
            raise RuntimeError("Не удалось подключиться к MongoDB. Проверьте DATABASE_URL и сервер.") from None
        return client


T = TypeVar("T", bound=Document)


class Database(Generic[T]):
    def __init__(self, model: type[T]):
        self.model = model

    async def save(self, document: T) -> T:
        return await document.create()

    async def get(self, id: PydanticObjectId) -> T | None:
        return await self.model.get(id)

    async def get_all(self) -> list[T]:
        return await self.model.find_all().to_list()

    async def update(self, id: PydanticObjectId, body: BaseModel) -> T | None:
        doc = await self.get(id)
        if doc is None:
            return None
        fields = body.model_dump(exclude_unset=True, exclude_none=True)
        if fields:
            await doc.update({"$set": fields})
        return doc

    async def delete(self, id: PydanticObjectId) -> bool:
        doc = await self.get(id)
        if doc is None:
            return False
        await doc.delete()
        return True

    async def delete_all(self) -> None:
        await self.model.find_all().delete()
