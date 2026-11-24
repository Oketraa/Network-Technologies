"""Layouts and reusable interface components."""

from functools import lru_cache
from html import escape
import json
import re

from . import accounts, maps, orders, support
from .common import display_time, now
from .storage import ROOT

TEMPLATES = ROOT / "templates"
PLACEHOLDER = re.compile(r"{{(!?)([a-z_]+)}}")
MAP_PAGES = {"order", "quote", "active", "arrived", "trip", "early_stop"}

PAGES = {
    "index": ("Вход", "", "", ""),
    "code_sent": ("Подтверждение номера", "index.html", "", "auth.code_screen"),
    "order": ("Маршрут", "", "order", ""),
    "quote": ("Стоимость поездки", "order.html", "order", "order.quote_screen"),
    "active": ("Активная поездка", "", "active", "order.active_screen"),
    "arrived": ("Автомобиль прибыл", "order.html", "active", "trip.arrival_screen"),
    "unlocked": ("Посадка", "order.html", "active", "trip.unlocked_screen"),
    "trip": ("Поездка выполняется", "", "active", "trip.running_screen"),
    "early_stop": ("Досрочная остановка", "trip.html", "active", ""),
    "completed": ("Поездка завершена", "", "active", "trip.completed_screen"),
    "thankyou": ("Спасибо за отзыв", "", "active", "trip.feedback_screen"),
    "cancel": ("Заказ отменён", "history.html", "active", "order.cancelled_screen"),
    "profile": ("Профиль", "", "profile", ""),
    "profile_edit": ("Личные данные", "profile.html", "profile", ""),
    "history": ("История поездок", "profile.html", "profile", ""),
    "support": ("Поддержка", "", "support", ""),
    "contact": ("Написать в поддержку", "support.html", "support", ""),
    "phone_code": ("Подтверждение номера", "profile_edit.html", "", "auth.code_screen"),
    "ticket": ("Обращение", "support.html", "support", "support.ticket_screen"),
    "overview": ("Экраны интерфейса", "", "", ""),
}


class Markup(str):
    """HTML built from trusted templates and escaped values."""


def e(value):
    return escape(str(value), quote=True)


@lru_cache
def template_source(name):
    return (TEMPLATES / f"{name}.html").read_text(encoding="utf-8")


def template(template_id, **values):
    def replace(match):
        value = values[match[2]]
        if match[1]:
            if not isinstance(value, Markup):
                raise TypeError(f"Expected rendered HTML for {match[2]}")
            return value
        return e(value)

    return Markup(PLACEHOLDER.sub(replace, template_source(template_id)))


EMPTY = Markup("")


def combine(fragments):
    return Markup("".join(fragments))


def hidden(name, value):
    return Markup(f'<input type="hidden" name="{e(name)}" value="{e(value)}">')


def button_form(action, label, csrf, **fields):
    inputs = combine(hidden(name, value) for name, value in fields.items())
    return Markup(
        f'<form class="action-form" method="post" action="/action/{e(action)}">'
        f'{csrf}{inputs}<button class="button button-quiet" type="submit">{e(label)}</button></form>'
    )


def options(choices, selected):
    return combine(
        Markup(f'<option value="{e(key)}"{" selected" if key == str(selected) else ""}>{e(label)}</option>')
        for key, label in choices.items()
    )


def alert(message="", error=False):
    if not message:
        return EMPTY
    style, role = ("error", "alert") if error else ("success", "status")
    return Markup(
        f'<div class="notice-layer notice {style}" role="{role}">'
        f'<span>{e(message)}</span>'
        '<button type="button" data-dismiss-notice aria-label="Закрыть уведомление">×</button></div>'
    )


def navigation(active):
    links = combine(
        template(f"shared/nav-{link}", selected=" selected" if active == link else "",
                 current=Markup(' aria-current="page"') if active == link else EMPTY)
        for link in ("order", "active", "profile", "support")
    )
    return Markup(f'<nav class="bottom-nav" aria-label="Основная навигация">{links}</nav>')


def page(screen, session=None, *, notice=EMPTY, content=None, back=None, **values):
    title, default_back, active, log_state = PAGES[screen]
    back = default_back if back is None else back
    csrf = hidden("csrf", session["csrf"]) if session else EMPTY
    if content is None:
        body = "code_sent" if screen == "phone_code" else screen
        content = template(body, csrf=csrf, back=back, **values)
    if screen == "overview":
        body_class = "catalog-page"
    else:
        body_class = "mobile-page"
        if back:
            back_button = template("shared/back", back=back)
            leading = Markup(f'{back_button}<span class="top-label">{e(title)}</span>')
        else:
            leading = template("shared/brand")
        right = template("shared/help") if active and active != "support" else EMPTY
        content = template(
            "shared/mobile", leading=leading, header_right=right, content=content, notice=notice,
            nav=navigation(active) if active else EMPTY,
        )
    map_assets = template("shared/map-assets") if screen in MAP_PAGES else EMPTY
    return template(
        "shared/document", title=title, body_class=body_class, log_state=log_state,
        content=content, map_assets=map_assets,
    )


def empty(name, session, heading, message, link, link_text):
    content = template("empty", heading=heading, message=message, link=link, link_text=link_text)
    return page(name, session, content=content)


def format_distance(tenths):
    return f"{tenths // 10},{tenths % 10} км"


def price(amount):
    return f"{amount:,}".replace(",", " ") + " ₽"


def map_view(route):
    if not route:
        return Markup('<p class="notice">Карта маршрута для этого заказа недоступна.</p>')
    return template("shared/map", map_data=json.dumps(route, separators=(",", ":")))


def draft_values(draft=None):
    draft = draft or {}
    route = draft.get("map", {})
    return {
        "pickup": draft.get("from", draft.get("pickup", "")),
        "destination": draft.get("to", draft.get("destination", "")),
        "pickup_point": draft.get("pickup_point", maps.point_label(route["pickup"]) if route else ""),
        "dropoff_point": draft.get("dropoff_point", maps.point_label(route["destination"]) if route else ""),
        "pickup_times": options(orders.PICKUP_TIMES, draft.get("when", draft.get("pickup_minutes", 0))),
        "seat_options": options(orders.SEATS, draft.get("seats", 1)),
    }


def quote_values(quote):
    return {
        "quote_token": quote["token"],
        "route": template("shared/route", **quote),
        "route_map": map_view(quote["map"]),
        "distance": format_distance(quote["distance"]),
        "duration": f"{quote['duration']} мин",
        "price": price(quote["price"]),
        "seats": orders.SEATS[str(quote["seats"])],
        "pickup_when": orders.PICKUP_TIMES[str(quote["pickup_minutes"])],
        "payment": accounts.PAYMENTS[quote["payment"]],
    }


def trip_values(db, order, session):
    finish_reason = order["completion"]
    stored_feedback = orders.feedback_for(db, order["id"]) if order["status"] == "completed" else None
    if stored_feedback:
        feedback = Markup(f'<section class="surface"><h2>Ваша оценка</h2><p>{stored_feedback["rating"]} из 5</p></section>')
    else:
        feedback = template("shared/feedback", csrf=hidden("csrf", session["csrf"]), order_id=order["id"])
    delay = max(0, (order["pickup_at"] - now() + 59) // 60)
    stopped = finish_reason == "early_finish"
    return {
        "order_id": order["id"],
        "order_code": orders.order_code(order["id"]),
        "pickup": order["pickup"],
        "route_map": map_view(json.loads(order["route_map"]) if order["route_map"] else None),
        "route": template("shared/route", pickup=order["pickup"], destination=order["destination"]),
        "vehicle": template("shared/vehicle", car_number=f"{order['vehicle_id']:03d}",
                            plate=order["plate"], car_color=order["color"]),
        "price": price(order["price"]),
        "payment": accounts.PAYMENTS[order["payment"]],
        "arrival_eta": f"{delay + 4} мин",
        "trip_eta": f"{max(1, order['duration'] // 2)} мин",
        "remaining": format_distance(max(1, order["distance"] // 2)),
        "completion_title": "Поездка завершена" if stopped else "Вы приехали!",
        "completion_note": "Выполнена досрочная остановка." if stopped else "Спасибо, что выбрали RoboTaxi.",
        "completion_status": "Стоимость поездки",
        "feedback": feedback,
        "cancel": button_form("cancel", "Отменить заказ", hidden("csrf", session["csrf"]), order=order["id"]),
    }


def profile_values(account, data=None):
    data = data or {}
    name = data.get("name", account["name"])
    return {
        "name": name,
        "phone": data.get("phone", accounts.display_phone(account["phone"])),
        "email": data.get("email", account["email"]),
        "payment": accounts.PAYMENTS[account["payment"]],
        "payments": options(accounts.PAYMENTS, data.get("payment", account["payment"])),
        "initials": "".join(word[0].upper() for word in name.split()[:2]),
    }


def detail_link(url, label, detail):
    return Markup(
        f'<a class="menu-row" href="{e(url)}"><span class="menu-text">'
        f'<strong>{e(label)}</strong><small>{e(detail)}</small></span></a>'
    )


def history_rows(history):
    if not history:
        return Markup('<p class="panel-empty">Здесь появятся ваши заказы.</p>')
    return combine(
        detail_link(
            orders.order_url(order),
            f"{order['pickup']} → {order['destination']}",
            f"{orders.order_code(order['id'])} · {orders.STATUS[order['status']][0]}"
            f" · {display_time(order['created_at'])} · {price(order['price'])}",
        )
        for order in history
    )


def passenger_tickets(rows):
    if not rows:
        return EMPTY
    links = combine(
        detail_link(f"ticket.html?id={row['id']}", support.TOPICS[row["topic"]],
                    f"{support.ticket_code(row['id'])} · Сохранено")
        for row in rows
    )
    return Markup(f'<section class="surface flush-surface"><h2 class="list-title">Мои обращения</h2>{links}</section>')


def ticket_values(ticket):
    return {
        "ticket_code": support.ticket_code(ticket["id"]),
        "ticket_status": "Сохранено",
        "ticket_note": "Обращение добавлено в список «Мои обращения».",
        "topic": support.TOPICS[ticket["topic"]],
        "order_context": f"Заказ {orders.order_code(ticket['order_id'])}" if ticket["order_id"] else "Обращение без заказа",
        "message": ticket["message"],
    }
