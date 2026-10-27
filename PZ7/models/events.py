from sqlmodel import SQLModel, Field, Column, JSON


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    image: str
    description: str
    tags: list[str] = Field(sa_column=Column(JSON))
    location: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Встреча по FastAPI",
                "image": "https://example.com/event.png",
                "description": "Обсуждение практических работ по FastAPI",
                "tags": ["python", "fastapi"],
                "location": "Уфа",
            }
        }
    }


class EventUpdate(SQLModel):
    title: str | None = None
    image: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    location: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {"title": "Обновлённая встреча по FastAPI"}
        }
    }
