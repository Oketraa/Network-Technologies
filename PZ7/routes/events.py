from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from database.connection import get_session
from models.events import Event, EventUpdate


event_router = APIRouter(tags=["События"])


@event_router.get("/", response_model=list[Event])
async def retrieve_all_events(session: Session = Depends(get_session)) -> list[Event]:
    statement = select(Event)
    events = session.exec(statement).all()
    return events


@event_router.get("/{id}", response_model=Event)
async def retrieve_event(id: int, session: Session = Depends(get_session)) -> Event:
    event = session.get(Event, id)
    if event:
        return event

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Событие с указанным ID не найдено.",
    )


@event_router.post("/new")
async def create_event(new_event: Event, session: Session = Depends(get_session)) -> dict:
    session.add(new_event)
    session.commit()
    session.refresh(new_event)
    return {"message": "Событие успешно создано!"}


@event_router.put("/edit/{id}", response_model=Event)
async def update_event(
    id: int,
    new_data: EventUpdate,
    session: Session = Depends(get_session),
) -> Event:
    event = session.get(Event, id)
    if event:
        event_data = new_data.model_dump(exclude_unset=True)
        for key, value in event_data.items():
            setattr(event, key, value)
        session.add(event)
        session.commit()
        session.refresh(event)
        return event

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Событие с указанным ID не найдено.",
    )


@event_router.delete("/{id}")
async def delete_event(id: int, session: Session = Depends(get_session)) -> dict:
    event = session.get(Event, id)
    if event:
        session.delete(event)
        session.commit()
        return {"message": "Событие успешно удалено!"}

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Событие с указанным ID не найдено.",
    )


@event_router.delete("/")
async def delete_all_events(session: Session = Depends(get_session)) -> dict:
    events = session.exec(select(Event)).all()
    for event in events:
        session.delete(event)
    session.commit()
    return {"message": "Все события успешно удалены!"}
