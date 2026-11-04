from beanie import PydanticObjectId
from bson import DBRef
from fastapi import APIRouter, HTTPException

from database.connection import Database
from models.events import Event, EventData, EventUpdate
from models.users import User

event_router = APIRouter(tags=["События"])
event_database = Database(Event)


EVENT_NOT_FOUND = "Событие с указанным ID не найдено."


@event_router.get("/", response_model=list[Event])
async def retrieve_all_events():
    return await event_database.get_all()


@event_router.get("/{id}", response_model=Event)
async def retrieve_event(id: PydanticObjectId):
    event = await event_database.get(id)
    if event is None:
        raise HTTPException(404, EVENT_NOT_FOUND)
    return event


@event_router.post("/new")
async def create_event(body: EventData):
    await event_database.save(Event(**body.model_dump()))
    return {"message": "Событие успешно создано!"}


@event_router.put("/{id}", response_model=Event)
async def update_event(id: PydanticObjectId, body: EventUpdate):
    event = await event_database.update(id, body)
    if event is None:
        raise HTTPException(404, EVENT_NOT_FOUND)
    return event


@event_router.delete("/{id}")
async def delete_event(id: PydanticObjectId):
    # Beanie stores Link[Event] as DBRef. Remove references even on a retry.
    await User.find_all().update({"$pull": {"events": {"$eq": DBRef("events", id)}}})
    if not await event_database.delete(id):
        raise HTTPException(404, EVENT_NOT_FOUND)
    return {"message": "Событие успешно удалено!"}


@event_router.delete("/")
async def delete_all_events():
    await User.find_all().update({"$set": {"events": []}})
    await event_database.delete_all()
    return {"message": "Все события успешно удалены!"}
