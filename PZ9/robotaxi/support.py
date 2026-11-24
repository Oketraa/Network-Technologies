"""Passenger support tickets."""

from .common import InputError, field, now

TOPICS = {
    "car": "Не могу найти автомобиль",
    "ride": "Проблема с поездкой",
    "payment": "Вопрос по оплате",
    "other": "Другое",
}


def ticket_code(ticket_id):
    return f"SUP-{ticket_id + 841:04d}"


def get_ticket(db, ticket_id, passenger_id):
    return db.execute(
        "SELECT * FROM tickets WHERE id = ? AND passenger_id = ?", (ticket_id, passenger_id)
    ).fetchone()


def tickets(db, passenger_id):
    return db.execute(
        "SELECT * FROM tickets WHERE passenger_id = ? ORDER BY id DESC", (passenger_id,)
    ).fetchall()


def create_ticket(db, account, order, data):
    topic = data.get("topic")
    if topic not in TOPICS:
        raise InputError("Выберите тему обращения.")
    message = field(data.get("message", ""), "Сообщение", 2000)
    cursor = db.execute(
        "INSERT INTO tickets(passenger_id, order_id, topic, message, created_at) VALUES (?, ?, ?, ?, ?)",
        (account["id"], order["id"] if order else None, topic, message, now()),
    )
    return cursor.lastrowid
