from fastapi import APIRouter, Body, HTTPException, status
from models.events import Event

event_router = APIRouter(tags=["События"])
events: list[Event] = []


@event_router.get("/", response_model=list[Event])
async def retrieve_all_events() -> list[Event]:
    return events


@event_router.get("/{id}", response_model=Event)
async def retrieve_event(id: int) -> Event:
    for event in events:
        if event.id == id:
            return event

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Событие с указанным ID не найдено.",
    )


@event_router.post("/new")
async def create_event(body: Event = Body(...)) -> dict:
    events.append(body)
    return {"message": "Событие успешно создано!"}


@event_router.delete("/{id}")
async def delete_event(id: int) -> dict:
    for event in events:
        if event.id == id:
            events.remove(event)
            return {"message": "Событие успешно удалено!"}

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Событие с указанным ID не найдено.",
    )


@event_router.delete("/")
async def delete_all_events() -> dict:
    events.clear()
    return {"message": "Все события успешно удалены!"}
