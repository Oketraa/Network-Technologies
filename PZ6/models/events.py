from pydantic import BaseModel


class Event(BaseModel):
    id: int
    title: str
    image: str
    description: str
    tags: list[str]
    location: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "title": "Встреча по FastAPI",
                "image": "https://example.com/event.png",
                "description": "Обсуждение практических работ по FastAPI",
                "tags": ["python", "fastapi"],
                "location": "Уфа",
            }
        }
    }
