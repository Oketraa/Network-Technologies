from pydantic import BaseModel, Field
from fastapi import Form


class Todo(BaseModel):
    id: int | None = None
    item: str = Field(min_length=1)

    @classmethod
    def as_form(cls, item: str = Form(min_length=1)) -> "Todo":
        return cls(item=item)

    model_config = {
        "json_schema_extra": {
            "example": {"id": 1, "item": "Выполнить практическую работу №5"}
        }
    }


class TodoItem(BaseModel):
    item: str = Field(min_length=1)

    model_config = {
        "json_schema_extra": {
            "example": {"item": "Прочитать следующую главу книги"}
        }
    }


class TodoItems(BaseModel):
    todos: list[TodoItem]

    model_config = {
        "json_schema_extra": {
            "example": {"todos": [{"item": "Первая задача"}, {"item": "Вторая задача"}]}
        }
    }
