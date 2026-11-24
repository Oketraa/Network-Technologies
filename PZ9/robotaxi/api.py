"""JSON endpoints and their OpenAPI description."""

from dataclasses import dataclass

from . import accounts, maps, notifications, orders, support
from .common import InputError, integer


@dataclass(frozen=True)
class WriteResult:
    status: int
    body: dict | None = None
    cookie: str | None = None


SIGN_IN_REQUIRED = "Войдите в RoboTaxi, чтобы продолжить."
ID_PARAMETER = {
    "in": "path", "name": "id", "required": True,
    "description": "Числовой идентификатор записи",
    "schema": {"type": "integer", "minimum": 1},
}
CONFIRMATION_PARAMETER = {
    "in": "header", "name": "X-Confirmation-Code", "required": True,
    "description": "Код из письма «Удаление аккаунта RoboTaxi»",
    "schema": {"type": "string", "pattern": "^[0-9]{6}$"},
}


def account_body(account):
    return {key: account[key] for key in ("id", "phone", "name")}


def order_body(order):
    keys = ("passenger_id", "pickup", "destination", "price", "vehicle_id", "plate", "status")
    return {"id": order["id"], "code": orders.order_code(order["id"]), **{key: order[key] for key in keys}}


def ticket_body(ticket):
    return {
        "id": ticket["id"], "code": support.ticket_code(ticket["id"]),
        "passenger_id": ticket["passenger_id"], "order_id": ticket["order_id"],
        "order_code": orders.order_code(ticket["order_id"]) if ticket["order_id"] else None,
        "topic": ticket["topic"], "topic_label": support.TOPICS[ticket["topic"]], "message": ticket["message"],
    }


def read_resource(db, session, path, query):
    account = accounts.get_account(db, session)
    if path == "/api/map/address":
        if account is None:
            return 401, {"error": SIGN_IN_REQUIRED}
        try:
            label = maps.reverse_address(maps.point(query.get("point", "")))
        except InputError as exc:
            return 422, {"error": str(exc)}
        return 200, {"label": label}
    if path == "/api/me":
        if account is None:
            return 401, {"error": SIGN_IN_REQUIRED}
        return 200, account_body(account)

    parts = path.split("/")
    if len(parts) != 4 or parts[2] not in ("orders", "tickets"):
        return 404, {"error": "Ресурс не найден."}
    if account is None:
        return 401, {"error": SIGN_IN_REQUIRED}
    resource_id = integer(parts[3])
    if parts[2] == "orders":
        order = orders.get_order(db, resource_id, account["id"])
        if order is None:
            return 404, {"error": "Заказ не найден."}
        return 200, order_body(order)
    ticket = support.get_ticket(db, resource_id, account["id"])
    if ticket is None:
        return 404, {"error": "Обращение не найдено."}
    return 200, ticket_body(ticket)


def error(status, message):
    return WriteResult(status, {"error": message})


def request_login(db, session, account, data, resource_id):
    phone = accounts.normalize_phone(data["phone"])
    new_session = session is None
    if new_session:
        session = accounts.make_session(db)
    try:
        accounts.request_code(db, session, phone, resend=True)
    except InputError:
        if new_session:
            db.execute("DELETE FROM sessions WHERE token = ?", (session["token"],))
        raise
    return WriteResult(202, {"phone": phone, "inbox_url": notifications.INBOX_URL},
                       session["token"] if new_session else None)


def verify_login(db, session, account, data, resource_id):
    if session is None:
        return error(401, "Сначала запросите код в этом браузере или клиенте.")
    signed_in = accounts.verify_code(db, session, data["code"])
    return WriteResult(200, account_body(accounts.get_account(db, signed_in)), signed_in["token"])


def estimate_order(db, session, account, data, resource_id):
    form = {
        **data, "when": str(data["pickup_minutes"]), "seats": str(data["seats"]),
    }
    quote = orders.estimate(db, session, account, form)
    return WriteResult(200, quote)


def create_order(db, session, account, data, resource_id):
    order, created = orders.confirm(db, session, account, data["quote_token"])
    return WriteResult(201 if created else 200, order_body(order))


def cancel_order(db, session, account, data, resource_id):
    order = orders.get_order(db, resource_id, account["id"])
    if order is None:
        return error(404, "Заказ не найден.")
    try:
        return WriteResult(200, order_body(orders.passenger_transition(db, order, "cancel")))
    except InputError as exc:
        return error(409, str(exc))


def create_ticket(db, session, account, data, resource_id):
    order_id = data.get("order_id")
    order = orders.get_order(db, order_id, account["id"]) if order_id is not None else None
    if order_id is not None and order is None:
        return error(404, "Заказ не найден.")
    ticket_id = support.create_ticket(db, account, order, data)
    return WriteResult(201, ticket_body(support.get_ticket(db, ticket_id, account["id"])))


def has_active_order(db, account):
    return orders.latest_order(db, account["id"], active=True) is not None


def request_deletion(db, session, account, data, resource_id):
    if has_active_order(db, account):
        return error(409, "Завершите или отмените активный заказ перед удалением аккаунта.")
    phone = account["phone"]
    accounts.request_code(db, session, phone, account, resend=True, purpose="deletion")
    return WriteResult(202, {"phone": phone, "inbox_url": notifications.INBOX_URL})


def delete_account(db, session, account, data, resource_id):
    if has_active_order(db, account):
        return error(409, "Завершите или отмените активный заказ перед удалением аккаунта.")
    accounts.verify_challenge(db, session, data["confirmation"], purpose="deletion", expected_phone=account["phone"])
    accounts.delete_account(db, account["id"])
    return WriteResult(204, cookie="")


def object_schema(properties, *, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required}


def properties(**types):
    return {name: {"type": kind} if isinstance(kind, str) else kind for name, kind in types.items()}


SCHEMAS = {
    "Account": object_schema(properties(id="integer", phone="string", name="string")),
    "Order": object_schema(properties(
        id="integer", code="string", passenger_id="integer", pickup="string", destination="string",
        price="integer", vehicle_id="integer", plate="string", status="string",
    )),
    "Ticket": object_schema(properties(
        id="integer", code="string", passenger_id="integer", order_id={"type": "integer", "nullable": True},
        order_code={"type": "string", "nullable": True}, topic="string", topic_label="string", message="string",
    )),
    "Delivery": object_schema(properties(phone="string", inbox_url="string")),
    "Quote": object_schema(properties(
        token={"type": "string", "description": "Передайте как quote_token при создании заказа."},
        pickup="string", destination="string", pickup_minutes="integer", seats="integer",
        distance={"type": "integer", "description": "Расстояние в десятых долях километра."},
        duration={"type": "integer", "description": "Длительность в минутах."},
        price={"type": "integer", "description": "Стоимость в рублях."}, payment="string",
        expires={"type": "integer", "description": "Время истечения расчёта в секундах Unix."},
        map={"type": "object", "description": "Координаты и линия маршрута."},
    )),
    "Error": object_schema(properties(error="string")),
}

PHONE = object_schema(properties(phone={"type": "string", "example": "+79000000000"}))
CODE = object_schema(properties(code={"type": "string", "pattern": "^[0-9]{6}$", "description": "Код из Mailpit."}))
QUOTE_REQUEST = object_schema(properties(
    **{"from": {"type": "string", "example": "Уфа, улица Ленина, 18"}},
    to={"type": "string", "example": "Уфа, улица Пархоменко, 104"},
    pickup_minutes={"type": "integer", "enum": [0, 15, 30]},
    seats={"type": "integer", "enum": [1, 2, 3, 4]},
    pickup_point={"type": "string", "description": "Вместо адреса посадки можно передать координаты «широта,долгота»."},
    dropoff_point={"type": "string", "description": "Вместо адреса назначения можно передать координаты «широта,долгота»."},
), required=["pickup_minutes", "seats"])
QUOTE_REQUEST["example"] = {
    "from": "Уфа, улица Ленина, 18", "to": "Уфа, улица Пархоменко, 104", "pickup_minutes": 0, "seats": 1,
}
ORDER_REQUEST = object_schema(properties(quote_token={"type": "string", "description": "Значение token из расчёта."}))
TICKET_REQUEST = object_schema(properties(
    topic={"type": "string", "enum": list(support.TOPICS)},
    message={"type": "string", "example": "Не вижу автомобиль у места посадки."},
    order_id={"type": "integer", "minimum": 1, "example": 1},
), required=["topic", "message"])
TICKET_REQUEST["example"] = {"topic": "car", "message": "Не вижу автомобиль у места посадки."}

TYPE_CHECKS = {"string": str, "integer": int}


def validate_body(data, schema):
    if schema is None:
        if data:
            raise InputError("У этого запроса нет тела.")
        return
    fields = schema["properties"]
    for key in schema["required"]:
        if key not in data:
            raise InputError(f"Заполните поле {key}.")
    for key, value in data.items():
        if key not in fields:
            raise InputError(f"Неизвестное поле {key}.")
        if type(value) is not TYPE_CHECKS[fields[key]["type"]]:
            raise InputError(f"Проверьте тип поля {key}.")
        if isinstance(value, int) and not 0 <= value <= 999_999_999:
            raise InputError(f"Проверьте значение поля {key}.")


def response(description, schema_name=None):
    result = {"description": description}
    if schema_name:
        result["content"] = {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema_name}"}}}
    return result


@dataclass(frozen=True)
class Operation:
    summary: str
    description: str
    handler: object
    successes: dict
    body: dict | None = None
    parameters: tuple = ()
    guest: bool = False
    errors: tuple = ()


OPERATIONS = {
    ("POST", "/api/auth/request-code"): Operation(
        "Отправить код входа", "Отправляет код в Mailpit и создаёт анонимный сеанс.",
        request_login, {"202": ("Код отправлен", "Delivery")}, body=PHONE, guest=True, errors=(409,),
    ),
    ("POST", "/api/auth/verify-code"): Operation(
        "Войти по коду", "Введите код из Mailpit в том же браузере. Сервер установит cookie сеанса.",
        verify_login, {"200": ("Вход выполнен", "Account")}, body=CODE, guest=True, errors=(401, 409),
    ),
    ("POST", "/api/orders/quote"): Operation(
        "Рассчитать поездку", "Передайте два адреса или две точки. Расчёт сохраняется в сеансе на 15 минут.",
        estimate_order, {"200": ("Готовый расчёт", "Quote")}, body=QUOTE_REQUEST,
    ),
    ("POST", "/api/orders"): Operation(
        "Подтвердить заказ", "Используйте токен расчёта из POST /api/orders/quote.",
        create_order, {"201": ("Заказ создан", "Order"), "200": ("Заказ уже создан с этим токеном", "Order")},
        body=ORDER_REQUEST,
    ),
    ("POST", "/api/orders/{id}/cancel"): Operation(
        "Отменить заказ", "Меняет статус заказа до открытия дверей.",
        cancel_order, {"200": ("Заказ отменён", "Order")}, parameters=(ID_PARAMETER,), errors=(404, 409),
    ),
    ("POST", "/api/tickets"): Operation(
        "Создать обращение", "Можно указать идентификатор своего заказа.",
        create_ticket, {"201": ("Обращение сохранено", "Ticket")}, body=TICKET_REQUEST, errors=(404,),
    ),
    ("POST", "/api/me/deletion-code"): Operation(
        "Запросить код удаления аккаунта", "Отправляет отдельный код на подтверждённый номер через Mailpit.",
        request_deletion, {"202": ("Код отправлен", "Delivery")}, errors=(409,),
    ),
    ("DELETE", "/api/me"): Operation(
        "Удалить свой аккаунт", "Удаляет аккаунт, сеансы, заказы, отзывы и обращения. Сначала запросите код удаления.",
        delete_account, {"204": ("Аккаунт удалён", None)}, parameters=(CONFIRMATION_PARAMETER,), errors=(409,),
    ),
}

ERRORS = {
    400: "Некорректный JSON",
    401: "Требуется действующий сеанс",
    403: "Запрос пришёл с другого сайта",
    404: "Запись не найдена у текущего пассажира",
    409: "Действие недоступно в текущем состоянии",
    413: "Тело запроса слишком большое",
    415: "Ожидается application/json",
    422: "Данные не прошли проверку",
}


def write_resource(db, session, method, path, data, confirmation):
    route = OPERATIONS.get((method, path))
    resource_id = None
    if route is None and method == "POST" and path.startswith("/api/orders/") and path.endswith("/cancel"):
        resource_id = integer(path.removeprefix("/api/orders/").removesuffix("/cancel"))
        if resource_id is not None:
            route = OPERATIONS[("POST", "/api/orders/{id}/cancel")]
    if route is None:
        return error(404, "Операция не найдена.")
    account = accounts.get_account(db, session)
    if route.guest and account:
        return error(409, "Вы уже вошли в аккаунт.")
    if not route.guest and account is None:
        return error(401, SIGN_IN_REQUIRED)
    try:
        validate_body(data, route.body)
        if method == "DELETE":
            data = {"confirmation": confirmation}
        return route.handler(db, session, account, data, resource_id)
    except InputError as exc:
        return error(422, str(exc))


def openapi():
    paths = {}
    read_operations = (
        ("/api/me", "Текущий пассажир", "Account"),
        ("/api/orders/{id}", "Сохранённый заказ", "Order"),
        ("/api/tickets/{id}", "Сохранённое обращение", "Ticket"),
    )
    for path, summary, schema in read_operations:
        operation = {
            "summary": summary,
            "responses": {"200": response("Данные из SQLite", schema), "401": response(ERRORS[401], "Error")},
        }
        if "{id}" in path:
            operation["parameters"] = [ID_PARAMETER]
            operation["responses"]["404"] = response(ERRORS[404], "Error")
        paths[path] = {"get": operation}
    for (method, path), route in OPERATIONS.items():
        errors = {403, 422, *route.errors}
        if route.body:
            errors.update((400, 413, 415))
        if not route.guest:
            errors.add(401)
        operation = {
            "summary": route.summary, "description": route.description,
            "responses": {
                **{code: response(*value) for code, value in route.successes.items()},
                **{str(code): response(ERRORS[code], "Error") for code in sorted(errors)},
            },
        }
        if route.guest:
            operation["security"] = []
        if route.parameters:
            operation["parameters"] = list(route.parameters)
        if route.body:
            body = {**route.body, "additionalProperties": False}
            operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": body}}}
        paths.setdefault(path, {})[method.lower()] = operation
    return {
        "openapi": "3.0.3",
        "info": {"title": "RoboTaxi API", "version": "1.1",
                 "description": "Используйте сессию браузера. Войдите через RoboTaxi или выполните два POST-запроса "
                                "входа ниже. Cookie передаётся автоматически при выполнении запросов."},
        "security": [{"passengerSession": []}],
        "components": {"schemas": SCHEMAS, "securitySchemes": {"passengerSession": {
            "type": "apiKey", "in": "cookie", "name": "robotaxi_session",
            "description": "Браузер получает HttpOnly cookie после входа и отправляет её автоматически.",
        }}},
        "paths": paths,
    }
