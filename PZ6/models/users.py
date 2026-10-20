from pydantic import BaseModel, EmailStr
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
