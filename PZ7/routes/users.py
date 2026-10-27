from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from database.connection import get_session
from models.users import NewUser, UserSignIn, UserRecord


user_router = APIRouter(tags=["Пользователи"])


@user_router.post("/signup")
async def sign_new_user(
    data: NewUser, session: Session = Depends(get_session)
) -> dict:
    if session.get(UserRecord, str(data.email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с указанной почтой уже зарегистрирован.",
        )

    new_user = UserRecord(
        email=str(data.email),
        password=data.password,
        username=data.username,
        events=[event.model_dump() for event in data.events],
    )
    session.add(new_user)
    session.commit()
    return {"message": "Пользователь успешно зарегистрирован!"}


@user_router.post("/signin")
async def sign_user_in(
    user: UserSignIn, session: Session = Depends(get_session)
) -> dict:
    db_user = session.get(UserRecord, str(user.email))
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь с указанной почтой не найден.",
        )

    if db_user.password != user.password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Неверный пароль.",
        )

    return {"message": "Вход выполнен успешно!"}
