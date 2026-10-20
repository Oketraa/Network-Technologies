from fastapi import APIRouter, HTTPException, status
from models.users import NewUser, UserSignIn

user_router = APIRouter(tags=["Пользователи"])
users: dict[str, NewUser] = {}


@user_router.post("/signup")
async def sign_new_user(data: NewUser) -> dict:
    if data.email in users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с указанной почтой уже зарегистрирован.",
        )

    users[data.email] = data
    return {"message": "Пользователь успешно зарегистрирован!"}


@user_router.post("/signin")
async def sign_user_in(user: UserSignIn) -> dict:
    if user.email not in users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь с указанной почтой не найден.",
        )

    if users[user.email].password != user.password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Неверный пароль.",
        )

    return {"message": "Вход выполнен успешно!"}
