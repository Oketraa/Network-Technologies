from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from database.connection import Settings
from routes.events import event_router
from routes.users import user_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = await Settings().initialize_database()
    try:
        yield
    finally:
        await client.close()


app = FastAPI(title="Планировщик событий Панкевича Романа", lifespan=lifespan)
app.include_router(user_router, prefix="/user")
app.include_router(event_router, prefix="/event")


@app.get("/", include_in_schema=False)
async def home():
    return RedirectResponse(url="/event/")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=True)
