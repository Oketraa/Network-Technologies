from pathlib import Path as FilePath

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Request, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

from model import Todo, TodoItem


todo_router = APIRouter()
todo_list: list[Todo] = []
templates = Jinja2Templates(directory=str(FilePath(__file__).resolve().parent / "templates"))


@todo_router.post("/todo", status_code=status.HTTP_201_CREATED)
async def add_todo(request: Request, todo: Todo = Depends(Todo.as_form)):
    todo.id = max((task.id for task in todo_list if task.id is not None), default=0) + 1
    todo_list.append(todo)
    return templates.TemplateResponse(
        request=request,
        name="todo.html",
        context={"todos": todo_list},
        status_code=status.HTTP_201_CREATED,
    )


@todo_router.get("/todo")
async def retrieve_todos(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="todo.html",
        context={"todos": todo_list},
    )


@todo_router.get("/todo/{todo_id}")
async def get_single_todo(
    request: Request,
    todo_id: int = Path(..., title="ID задачи для поиска"),
):
    for todo in todo_list:
        if todo.id == todo_id:
            return templates.TemplateResponse(
                request=request,
                name="todo.html",
                context={"todo": todo},
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Задача с указанным ID не найдена в вашем списке.",
    )


@todo_router.get("/todo/{todo_id}/edit", include_in_schema=False)
async def edit_todo_page(request: Request, todo_id: int):
    for todo in todo_list:
        if todo.id == todo_id:
            return templates.TemplateResponse(
                request=request,
                name="todo.html",
                context={"edit_todo": todo},
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Задача с указанным ID не найдена в вашем списке.",
    )


@todo_router.post("/todo/{todo_id}/edit", include_in_schema=False)
async def edit_todo_from_page(todo_id: int, item: str = Form(min_length=1)):
    for todo in todo_list:
        if todo.id == todo_id:
            todo.item = item
            return RedirectResponse(url="/todo", status_code=status.HTTP_303_SEE_OTHER)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Задача с указанным ID не найдена в вашем списке.",
    )


@todo_router.put("/todo/{todo_id}")
async def update_todo(
    todo_data: TodoItem,
    todo_id: int = Path(..., title="ID задачи для обновления"),
) -> dict:
    for todo in todo_list:
        if todo.id == todo_id:
            todo.item = todo_data.item
            return {"message": "Задача успешно обновлена в вашем списке!"}

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Задача с указанным ID не найдена в вашем списке.",
    )


@todo_router.post("/todo/{todo_id}/delete", include_in_schema=False)
async def delete_todo_from_page(todo_id: int):
    for index, todo in enumerate(todo_list):
        if todo.id == todo_id:
            todo_list.pop(index)
            return RedirectResponse(url="/todo", status_code=status.HTTP_303_SEE_OTHER)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Задача с указанным ID не найдена в вашем списке.",
    )


@todo_router.delete("/todo/{todo_id}")
async def delete_single_todo(todo_id: int) -> dict:
    for index, todo in enumerate(todo_list):
        if todo.id == todo_id:
            todo_list.pop(index)
            return {"message": "Задача успешно удалена из вашего списка!"}

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Задача с указанным ID не найдена в вашем списке.",
    )


@todo_router.delete("/todo")
async def delete_all_todo() -> dict:
    todo_list.clear()
    return {"message": "Все задачи успешно удалены из вашего списка!"}
