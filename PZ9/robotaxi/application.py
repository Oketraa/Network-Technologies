"""HTTP-independent page routing and form actions."""

from dataclasses import dataclass
import hmac

from . import accounts, notifications, orders, support, views
from .common import InputError, integer, now

PUBLIC = {"index", "code_sent", "overview"}
TRIP_PAGES = {"active", "arrived", "unlocked", "trip", "early_stop", "completed", "thankyou", "cancel"}
READ_PAGES = {"order", "quote", "profile", "profile_edit", "history", "support", "contact", "ticket", "phone_code"}
ACTIONS = {"request_code", "resend_code", "verify_code", "signout", "quote", "confirm", "profile", "feedback", "ticket"} | orders.TRANSITIONS.keys()


@dataclass
class Response:
    status: int = 200
    html: str = ""
    location: str = ""
    cookie: str | None = None


def redirect(url, cookie=None):
    return Response(status=303, location="/" + url, cookie=cookie)


def error_page(status, heading, message):
    return Response(status, views.empty("index", None, heading, message, "index.html", "На главную"))


def show(screen, session=None, *, cookie=None, status=200, **values):
    return Response(status, views.page(screen, session, **values), cookie=cookie)


def code_screen(session, account=None, notice=views.EMPTY, status=200):
    if not session or not session["challenge_phone"] or session["challenge_purpose"] != "access":
        return redirect("profile_edit.html" if account else "index.html")
    phone = accounts.display_phone(session["challenge_phone"])
    return show(
        "phone_code" if account else "code_sent", session, status=status, notice=notice,
        code_hint=f"Код отправлен для номера {phone}.",
        inbox_url=notifications.INBOX_URL,
        back_label="Вернуться в профиль" if account else "Изменить номер",
    )


def order_page(db, session, account, page, query):
    order_id = query.get("id")
    if order_id is None:
        order = orders.latest_order(db, account["id"])
    else:
        order = orders.get_order(db, integer(order_id), account["id"])
        if not order:
            return error_page(404, "Заказ не найден", "Проверьте ссылку или откройте историю поездок.")
    if not order:
        return Response(html=views.empty(
            "active", session, "У вас пока нет поездок", "Задайте маршрут, чтобы заказать автомобиль.",
            "order.html", "Выбрать маршрут",
        ))
    current = orders.STATUS[order["status"]][1]
    is_early_stop = page == "early_stop" and current == "trip"
    has_feedback = page == "thankyou" and current == "completed" and orders.feedback_for(db, order["id"])
    if page != current and not is_early_stop and not has_feedback:
        return redirect(orders.order_url(order))
    back = f"trip.html?id={order['id']}" if is_early_stop else None
    return show(page, session, back=back, **views.trip_values(db, order, session))


def contact_values(db, account, data=None):
    data = data or {}
    order = orders.latest_order(db, account["id"])
    return {
        "topics": views.options(support.TOPICS, data.get("topic", "car")),
        "message": data.get("message", ""),
        "order_context": f"Заказ {orders.order_code(order['id'])}" if order else "Обращение без заказа",
        "linked_order": order["id"] if order else "",
    }


def get_page(db, page, query, session):
    if page not in PUBLIC | READ_PAGES | TRIP_PAGES:
        return error_page(404, "Страница не найдена", "Проверьте адрес страницы.")
    account = accounts.get_account(db, session)
    if page == "overview":
        return show(page)
    if page == "index":
        if account:
            return redirect("order.html")
        cookie = None
        if not session:
            session = accounts.make_session(db)
            cookie = session["token"]
        phone = accounts.display_phone(session["challenge_phone"]) if session["challenge_phone"] else ""
        return show(page, session, cookie=cookie, phone=phone)
    if page == "code_sent":
        return redirect("order.html") if account else code_screen(session)
    if not account:
        return redirect("index.html")
    if page in TRIP_PAGES:
        return order_page(db, session, account, page, query)
    if page == "phone_code":
        return code_screen(session, account)
    if page == "order":
        draft = orders.get_quote(session)
        return show(page, session, **views.draft_values(draft))
    if page == "quote":
        quote = orders.get_quote(session)
        if not quote or not quote.get("map") or quote["expires"] <= now():
            return redirect("order.html")
        return show(page, session, **views.quote_values(quote))
    if page in ("profile", "profile_edit"):
        notice = views.alert("Профиль сохранён.") if query.get("saved") == "1" else views.EMPTY
        return show(page, session, notice=notice, **views.profile_values(account))
    if page == "history":
        return show(page, session, rows=views.history_rows(orders.history(db, account["id"])))
    if page == "support":
        return show(page, session, tickets=views.passenger_tickets(support.tickets(db, account["id"])))
    if page == "contact":
        return show(page, session, **contact_values(db, account))
    ticket = support.get_ticket(db, integer(query.get("id")), account["id"])
    if not ticket:
        return error_page(404, "Обращение не найдено", "Откройте список «Мои обращения» в поддержке.")
    return show("ticket", session, **views.ticket_values(ticket))


def apply_action(db, operation, data, session, account):
    if operation == "request_code":
        if account:
            return redirect("order.html")
        accounts.request_code(db, session, data.get("phone", ""))
        return redirect("code_sent.html")
    if operation == "resend_code":
        if not session["challenge_phone"] or session["challenge_purpose"] != "access":
            return code_screen(session, account)
        accounts.request_code(db, session, session["challenge_phone"], account, resend=True)
        return redirect("phone_code.html" if account else "code_sent.html")
    if operation == "verify_code":
        new_session = accounts.verify_code(db, session, data.get("code", ""), account)
        return redirect("profile.html?saved=1" if account else "order.html", new_session["token"])
    if operation == "signout":
        db.execute("DELETE FROM sessions WHERE token = ?", (session["token"],))
        return redirect("index.html", "")
    if operation == "quote":
        orders.estimate(db, session, account, data)
        return redirect("quote.html")
    if operation == "confirm":
        order, _ = orders.confirm(db, session, account, data.get("quote"))
        return redirect(orders.order_url(order))
    if operation == "profile":
        change_phone = accounts.save_profile(db, session, account, data)
        return redirect("phone_code.html" if change_phone else "profile.html?saved=1")
    if operation == "ticket":
        order = orders.get_order(db, integer(data.get("order")), account["id"])
        ticket_id = support.create_ticket(db, account, order, data)
        return redirect(f"ticket.html?id={ticket_id}")
    order = orders.get_order(db, integer(data.get("order")), account["id"])
    if not order:
        return error_page(404, "Заказ не найден", "Откройте раздел «Поездка» и повторите действие.")
    if operation == "feedback":
        orders.save_feedback(db, order, data)
        return redirect(f"thankyou.html?id={order['id']}")
    return redirect(orders.order_url(orders.passenger_transition(db, order, operation)))


def show_action_error(db, operation, data, session, account, message):
    notice = views.alert(message, error=True)
    if operation == "request_code":
        return show("index", session, notice=notice, status=422, phone=data.get("phone", ""))
    if operation in ("verify_code", "resend_code"):
        return code_screen(session, account, notice, status=422)
    if operation == "quote":
        return show("order", session, notice=notice, status=422, **views.draft_values(data))
    if operation == "confirm":
        quote = orders.get_quote(session)
        if quote and quote.get("map") and quote["expires"] > now():
            return show("quote", session, notice=notice, status=422, **views.quote_values(quote))
        return show("order", session, notice=notice, status=422, **views.draft_values(quote))
    if operation == "profile":
        return show("profile_edit", session, notice=notice, status=422, **views.profile_values(account, data))
    if operation == "ticket":
        return show("contact", session, notice=notice, status=422, **contact_values(db, account, data))
    order = orders.get_order(db, integer(data.get("order")), account["id"])
    if order:
        actual = orders.STATUS[order["status"]][1]
        return show(actual, session, notice=notice, status=422, **views.trip_values(db, order, session))
    return error_page(422, "Действие недоступно", message)


def post_action(db, operation, data, session):
    if operation not in ACTIONS:
        return error_page(404, "Действие недоступно", "Вернитесь в приложение и повторите действие.")
    if not session:
        return redirect("index.html")
    received = data.get("csrf", "")
    if not received.isascii() or not hmac.compare_digest(received, session["csrf"]):
        return error_page(403, "Форма устарела", "Обновите страницу и повторите действие.")
    account = accounts.get_account(db, session)
    if not account and operation not in ("request_code", "resend_code", "verify_code"):
        return redirect("index.html")
    try:
        return apply_action(db, operation, data, session, account)
    except InputError as exc:
        return show_action_error(db, operation, data, session, account, str(exc))
