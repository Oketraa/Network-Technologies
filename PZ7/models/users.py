from pydantic import BaseModel, EmailStr
from sqlmodel import SQLModel, Field, Column, JSON
from models.events import Event


class User(BaseModel):
    email: EmailStr
    password: str
    events: list[Event] = []


class NewUser(User):
    username: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "roman@example.com",
                "password": "Strong123!",
                "username": "RomanPankevich",
                "events": [],
            }
        }
    }


class UserSignIn(BaseModel):
    email: EmailStr
    password: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "roman@example.com",
                "password": "Strong123!",
            }
        }
    }


class UserRecord(SQLModel, table=True):
    __tablename__ = "users"

    email: str = Field(primary_key=True)
    password: str
    username: str
    events: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
