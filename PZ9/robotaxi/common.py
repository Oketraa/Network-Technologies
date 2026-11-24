"""Validation shared by application components."""

from datetime import datetime
import re
import time


class InputError(Exception):
    pass


def now():
    return int(time.time())


def display_time(epoch, layout="%d.%m.%Y, %H:%M"):
    return datetime.fromtimestamp(epoch).strftime(layout)


def field(value, label, limit, *, required=True):
    value = value.strip()
    if required and not value:
        raise InputError(f"Заполните поле «{label}».")
    if len(value) > limit or "\x00" in value:
        raise InputError(f"Проверьте значение поля «{label}» (до {limit} символов).")
    return value


def integer(value, fallback=None):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value):
        return int(value)
    return fallback
