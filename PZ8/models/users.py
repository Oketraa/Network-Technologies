from typing import Annotated

from beanie import Document, Link, PydanticObjectId
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pymongo import ASCENDING, IndexModel

from models.events import Event


class UserSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class NewUser(UserSignIn):
    password: Annotated[str, Field(min_length=8, max_length=128)]
    username: Annotated[str, Field(min_length=1, max_length=100)] = "Пользователь"
    events: list[PydanticObjectId] = Field(default_factory=list, max_length=100)
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "email": "roman@example.com", "password": "Strong123!",
        "username": "RomanPankevich", "events": []}})

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Имя не может быть пустым")
        return value


class User(Document):
    email: EmailStr
    password: str | None = Field(default=None, repr=False)
    username: str
    events: list[Link[Event]] = Field(default_factory=list)

    class Settings:
        name = "users"
        indexes = [IndexModel([("email", ASCENDING)], unique=True)]
