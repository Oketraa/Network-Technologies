from beanie import Document
from pydantic import BaseModel, ConfigDict


class EventData(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {
            "title": "Встреча по FastAPI", "image": "https://example.com/event.png",
            "description": "Обсуждение практической работы с MongoDB",
            "tags": ["python", "fastapi"], "location": "Уфа"}})
    title: str
    image: str
    description: str
    tags: list[str]
    location: str


class Event(Document, EventData):
    class Settings:
        name = "events"


class EventUpdate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"location": "Hybrid"}})
    title: str | None = None
    image: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    location: str | None = None
