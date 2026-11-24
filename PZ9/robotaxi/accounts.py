"""One-time confirmation codes, session lifecycle, and passenger profiles."""

import hmac
import re
import secrets

from .common import InputError, field, now
from . import notifications

PAYMENTS = {
    "card": "Банковская карта",
    "wallet": "Электронный кошелёк",
}
SESSION_AGE = 7 * 24 * 60 * 60
CODE_AGE = 5 * 60
RESEND_DELAY = 45
MAX_ATTEMPTS = 5
OTP_KEY = secrets.token_bytes(32)


def normalize_phone(raw):
    if not re.fullmatch(r"[+0-9() \-]{10,24}", raw.strip()):
        raise InputError("Введите российский номер из 10 или 11 цифр.")
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or digits[0] not in "78":
        raise InputError("Введите российский номер из 10 или 11 цифр.")
    return "+7" + digits[1:]


def display_phone(phone):
    return f"{phone[:2]} {phone[2:5]} {phone[5:8]}-{phone[8:10]}-{phone[10:]}"


def get_session(db, token):
    if token:
        return db.execute(
            "SELECT * FROM sessions WHERE token = ? AND expires > ?", (token, now())
        ).fetchone()
    return None


def make_session(db, account_id=None, previous=None):
    if previous:
        db.execute("DELETE FROM sessions WHERE token = ?", (previous,))
    db.execute("DELETE FROM sessions WHERE expires <= ?", (now(),))
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions(token, csrf, account_id, expires) VALUES (?, ?, ?, ?)",
        (token, secrets.token_urlsafe(24), account_id, now() + SESSION_AGE),
    )
    return get_session(db, token)


def get_account(db, session):
    if not session or session["account_id"] is None:
        return None
    return db.execute("SELECT * FROM accounts WHERE id = ?", (session["account_id"],)).fetchone()


def available_phone(db, phone, account):
    conflict = db.execute("SELECT id FROM accounts WHERE phone = ?", (phone,)).fetchone()
    if conflict and conflict["id"] != account["id"]:
        raise InputError("Этот номер уже используется.")


def code_digest(token, phone, code, purpose):
    return hmac.digest(OTP_KEY, f"{token}:{phone}:{purpose}:{code}".encode("ascii"), "sha256").hex()


def request_code(db, session, raw_phone, account=None, *, resend=False, purpose="access"):
    phone = normalize_phone(raw_phone)
    if account:
        available_phone(db, phone, account)
    if (
        session["challenge_phone"] == phone
        and session["challenge_purpose"] == purpose
        and session["challenge_digest"]
        and (session["challenge_expires"] or 0) > now() + CODE_AGE - RESEND_DELAY
    ):
        if resend:
            raise InputError("Новый код можно запросить через 45 секунд после отправки.")
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    if purpose == "deletion":
        notifications.send_deletion_code(phone, code)
    else:
        notifications.send_code(phone, code)
    db.execute(
        """UPDATE sessions SET challenge_phone = ?, challenge_expires = ?,
           challenge_digest = ?, challenge_purpose = ?, attempts = 0 WHERE token = ?""",
        (phone, now() + CODE_AGE, code_digest(session["token"], phone, code, purpose), purpose, session["token"]),
    )


def verify_challenge(db, session, raw_code, *, purpose="access", expected_phone=None):
    phone = session["challenge_phone"]
    digest = session["challenge_digest"]
    if (
        not phone or not digest or session["challenge_purpose"] != purpose
        or (session["challenge_expires"] or 0) <= now()
        or (expected_phone is not None and phone != expected_phone)
    ):
        raise InputError("Срок действия кода истёк. Запросите новый код.")
    if session["attempts"] >= MAX_ATTEMPTS:
        raise InputError("Попытки исчерпаны. Запросите новый код.")
    if not re.fullmatch(r"[0-9]{6}", raw_code) or not hmac.compare_digest(
        digest, code_digest(session["token"], phone, raw_code, purpose)
    ):
        db.execute("UPDATE sessions SET attempts = attempts + 1 WHERE token = ?", (session["token"],))
        raise InputError("Неверный код подтверждения.")
    return phone


def verify_code(db, session, raw_code, account=None):
    phone = verify_challenge(db, session, raw_code)
    if account:
        available_phone(db, phone, account)
        db.execute("UPDATE accounts SET phone = ? WHERE id = ?", (phone, account["id"]))
        return make_session(db, account["id"], session["token"])

    db.execute(
        "INSERT OR IGNORE INTO accounts(phone, name) VALUES (?, ?)", (phone, "Пассажир")
    )
    identified = db.execute("SELECT id FROM accounts WHERE phone = ?", (phone,)).fetchone()
    if identified is None:
        raise InputError("Вход для этого номера недоступен.")
    return make_session(db, identified["id"], session["token"])


def delete_account(db, account_id):
    args = (account_id,)
    # The caller holds the write transaction while checking the trip and code.
    db.execute(
        """DELETE FROM sessions WHERE account_id = ? OR
           (account_id IS NULL AND challenge_phone = (SELECT phone FROM accounts WHERE id = ?))""",
        (account_id, account_id),
    )
    db.execute("DELETE FROM tickets WHERE passenger_id = ?", args)
    db.execute("DELETE FROM feedback WHERE order_id IN (SELECT id FROM orders WHERE passenger_id = ?)", args)
    db.execute("DELETE FROM orders WHERE passenger_id = ?", args)
    db.execute("DELETE FROM accounts WHERE id = ?", args)


def save_profile(db, session, account, data):
    name = field(data.get("name", ""), "Имя", 80)
    email = field(data.get("email", ""), "Электронная почта", 160, required=False)
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise InputError("Введите действительный адрес электронной почты.")
    payment = data.get("payment")
    if payment not in PAYMENTS:
        raise InputError("Выберите способ оплаты.")
    phone = normalize_phone(data.get("phone", ""))
    change_phone = phone != account["phone"]
    if change_phone:
        request_code(db, session, phone, account)
    else:
        db.execute(
            """UPDATE sessions SET challenge_phone = NULL, challenge_expires = NULL,
               challenge_digest = NULL, attempts = 0 WHERE token = ?""",
            (session["token"],),
        )
    db.execute("UPDATE accounts SET name = ?, email = ?, payment = ? WHERE id = ?", (name, email, payment, account["id"]))
    return change_phone
