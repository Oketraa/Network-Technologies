"""Route estimates, vehicle assignment, trip transitions, and feedback."""

import json
import secrets

from . import maps
from .accounts import PAYMENTS
from .common import InputError, field, integer, now

PICKUP_TIMES = {"0": "Сейчас", "15": "Через 15 минут", "30": "Через 30 минут"}
SEATS = {"1": "1 пассажир", "2": "2 пассажира", "3": "3 пассажира", "4": "4 пассажира"}

STATUS = {
    "assigned": ("Автомобиль в пути", "active", "blue"),
    "arrived": ("Ожидает посадку", "arrived", "amber"),
    "unlocked": ("Двери открыты", "unlocked", "amber"),
    "riding": ("Поездка выполняется", "trip", "green"),
    "completed": ("Завершён", "completed", "green"),
    "cancelled": ("Отменён", "cancel", "amber"),
}
ACTIVE = ("assigned", "arrived", "unlocked", "riding")
ACTIVE_SQL = "('assigned', 'arrived', 'unlocked', 'riding')"
TRANSITIONS = {
    "arrive": (("assigned",), "arrived"),
    "unlock": (("arrived",), "unlocked"),
    "start": (("unlocked",), "riding"),
    "finish": (("riding",), "completed"),
    "early_finish": (("riding",), "completed"),
    "cancel": (("assigned", "arrived"), "cancelled"),
}

ORDER_DETAILS = """
SELECT o.*, v.plate, v.color, a.name AS passenger
FROM orders o JOIN vehicles v ON o.vehicle_id = v.id
JOIN accounts a ON o.passenger_id = a.id
"""


def order_code(order_id):
    return f"AG-{order_id + 2047:04d}"


def order_url(order):
    return f"{STATUS[order['status']][1]}.html?id={order['id']}"


def get_order(db, order_id, passenger_id=None):
    sql = ORDER_DETAILS + " WHERE o.id = ?"
    args = (order_id,)
    if passenger_id is not None:
        sql += " AND o.passenger_id = ?"
        args += (passenger_id,)
    return db.execute(sql, args).fetchone()


def latest_order(db, passenger_id, *, active=False):
    sql = ORDER_DETAILS + " WHERE o.passenger_id = ?"
    if active:
        sql += " AND o.status IN " + ACTIVE_SQL
    return db.execute(sql + " ORDER BY o.id DESC LIMIT 1", (passenger_id,)).fetchone()


def history(db, passenger_id):
    return db.execute(
        ORDER_DETAILS + " WHERE o.passenger_id = ? ORDER BY o.id DESC", (passenger_id,)
    ).fetchall()



def estimate(db, session, account, data):
    pickup = field(data.get("from", ""), "Откуда", 140, required=False)
    destination = field(data.get("to", ""), "Куда", 140, required=False)
    pickup_time = data.get("when")
    seats = data.get("seats")
    if pickup_time not in PICKUP_TIMES or seats not in SEATS:
        raise InputError("Выберите время подачи и число пассажиров.")
    pickup_point, pickup = maps.resolve_place(pickup, data.get("pickup_point", ""))
    dropoff_point, destination = maps.resolve_place(destination, data.get("dropoff_point", ""))
    route = maps.road_route(pickup_point, dropoff_point)
    quote = {
        "token": secrets.token_urlsafe(16),
        "pickup": pickup,
        "destination": destination,
        "pickup_minutes": int(pickup_time),
        "seats": int(seats),
        **route,
        "price": 169 + round(route["distance"] * 2.5),
        "payment": account["payment"],
        "expires": now() + 15 * 60,
    }
    saved = db.execute(
        "UPDATE sessions SET quote = ? WHERE token = ? AND expires > ?",
        (json.dumps(quote), session["token"], now()),
    )
    if not saved.rowcount:
        raise InputError("Сеанс истёк. Войдите в аккаунт и рассчитайте маршрут заново.")
    return quote


def get_quote(session):
    return json.loads(session["quote"]) if session["quote"] else None


def free_vehicle(db, current=None):
    rows = db.execute(
        "SELECT id FROM vehicles WHERE id NOT IN "
        "(SELECT vehicle_id FROM orders WHERE status IN " + ACTIVE_SQL + ") ORDER BY id"
    )
    return next((row["id"] for row in rows if row["id"] != current), None)



def confirm(db, session, account, quote_token):
    existing = db.execute(
        "SELECT id FROM orders WHERE quote_token = ? AND passenger_id = ?", (quote_token, account["id"])
    ).fetchone()
    if existing:
        return get_order(db, existing["id"], account["id"]), False
    quote = get_quote(session)
    if not quote or not quote.get("map") or quote["expires"] <= now() or quote["token"] != quote_token:
        raise InputError("Расчёт устарел. Рассчитайте поездку заново.")
    if latest_order(db, account["id"], active=True):
        raise InputError("У вас уже есть активный заказ. Откройте раздел «Поездка».")
    vehicle = free_vehicle(db)
    if vehicle is None:
        raise InputError("Сейчас нет свободных автомобилей. Попробуйте позже.")
    created = now()
    cursor = db.execute(
        """INSERT INTO orders (
            passenger_id, quote_token, pickup, destination, pickup_minutes, seats, distance,
            duration, price, payment, vehicle_id, created_at, pickup_at, route_map
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            account["id"], quote["token"], quote["pickup"], quote["destination"],
            quote["pickup_minutes"], quote["seats"], quote["distance"], quote["duration"],
            quote["price"], quote["payment"], vehicle, created, created + quote["pickup_minutes"] * 60,
            json.dumps(quote["map"]),
        ),
    )
    return get_order(db, cursor.lastrowid), True


def _apply_status(db, order, status, operation):
    if status in ("completed", "cancelled"):
        payment_status = "charged" if status == "completed" else "void"
        db.execute(
            "UPDATE orders SET status = ?, payment_status = ?, completion = ?, ended_at = ? WHERE id = ?",
            (status, payment_status, operation, now(), order["id"]),
        )
    else:
        db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order["id"]))
    return get_order(db, order["id"])


def passenger_transition(db, order, operation):
    allowed, status = TRANSITIONS[operation]
    if order["status"] == status:
        return order
    if order["status"] not in allowed:
        raise InputError("Действие недоступно на текущем этапе поездки.")
    return _apply_status(db, order, status, operation)



def save_feedback(db, order, data):
    if order["status"] != "completed":
        raise InputError("Оценить можно завершённую поездку.")
    rating = integer(data.get("rating"))
    if rating not in range(1, 6):
        raise InputError("Поставьте оценку от 1 до 5.")
    comment = field(data.get("comment", ""), "Комментарий", 1000, required=False)
    db.execute(
        "INSERT OR IGNORE INTO feedback(order_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
        (order["id"], rating, comment, now()),
    )


def feedback_for(db, order_id):
    return db.execute("SELECT * FROM feedback WHERE order_id = ?", (order_id,)).fetchone()
