from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from todo import todo_router


app = FastAPI(title="Персональный Todo API Панкевича Романа", version="1.0")


@app.get("/", include_in_schema=False)
async def welcome():
    return RedirectResponse(url="/todo")


app.include_router(todo_router)
