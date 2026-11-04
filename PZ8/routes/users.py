from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from database.connection import Database
from models.events import Event
from models.users import NewUser, User, UserSignIn

user_router = APIRouter(tags=["Пользователи"])
user_database = Database(User)


@user_router.post("/signup")
async def sign_new_user(data: NewUser):
    if await User.find_one(User.email == str(data.email)):
        raise HTTPException(409, "Пользователь с указанной почтой уже зарегистрирован.")
    linked_events = []
    for id in dict.fromkeys(data.events):
        event = await Event.get(id)
        if event is None:
            raise HTTPException(404, "Событие из списка пользователя не найдено.")
        linked_events.append(event)
    user = User(email=data.email, password=data.password, username=data.username,
                events=linked_events)
    try:
        await user_database.save(user)
    except DuplicateKeyError:
        raise HTTPException(409, "Пользователь с указанной почтой уже зарегистрирован.") from None
    return {"message": "Пользователь успешно зарегистрирован!"}


@user_router.post("/signin")
async def sign_user_in(data: UserSignIn):
    user = await User.find_one(User.email == str(data.email))
    if user is None:
        raise HTTPException(404, "Пользователь с указанной почтой не найден.")
    if user.password != data.password:
        raise HTTPException(401, "Неверный пароль.")
    return {"message": "Вход выполнен успешно!"}
