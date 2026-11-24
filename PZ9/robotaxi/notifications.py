"""Send login notifications to the local SMTP capture inbox."""

from email.message import EmailMessage
import os
import smtplib

from .common import InputError

SMTP_PORT = int(os.environ.get("ROBOTAXI_SMTP_PORT", "1025"))
INBOX_URL = "http://127.0.0.1:" + str(int(os.environ.get("ROBOTAXI_INBOX_PORT", "8025")))


def send_code(phone, code):
    _send_code(phone, code, "Код подтверждения RoboTaxi", "для входа или подтверждения номера")


def send_deletion_code(phone, code):
    _send_code(phone, code, "Удаление аккаунта RoboTaxi", "для удаления аккаунта")


def _send_code(phone, code, subject, purpose):
    message = EmailMessage()
    message["From"] = "RoboTaxi <login@robotaxi.test>"
    message["To"] = f"{phone.lstrip('+')}@robotaxi.test"
    message["Subject"] = subject
    message.set_content(
        f"Код подтверждения для номера {phone}: {code}\n"
        f"Код действует 5 минут. Используйте его {purpose}.\n"
    )
    try:
        # Mailpit accepts mail locally. The reserved .test addresses identify inbox entries by phone.
        with smtplib.SMTP("127.0.0.1", SMTP_PORT, timeout=2) as smtp:
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise InputError("Не удалось отправить код. Попробуйте ещё раз.") from exc
