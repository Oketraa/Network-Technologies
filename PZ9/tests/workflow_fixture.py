"""Shared HTTP fixture for the three passenger scenarios."""

from collections import Counter
from contextlib import redirect_stderr
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from io import BytesIO, StringIO
from itertools import count
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

# Running a scenario by filename places tests/ on Python's import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import Handler
from robotaxi import accounts, application, maps, notifications, orders, storage, support, views


PHONE = "+79000001001"
PICKUP = "Уфа, улица Ленина, 18"
DESTINATION = "Уфа, Революционная улица, 45"
PICKUP_POINT = "54.7348,55.9515"
DESTINATION_POINT = "54.7435,55.9617"

ROUTE = {
    "code": "Ok",
    "routes": [{
        "distance": 7200, "duration": 960,
        "geometry": {"coordinates": [[55.9515, 54.7348], [55.9617, 54.7435]]},
    }],
}


class Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            attributes = dict(attrs)
            if "name" in attributes:
                self.values.setdefault(attributes["name"], attributes.get("value", ""))


def form_value(page, name):
    inputs = Inputs()
    inputs.feed(page)
    if name not in inputs.values:
        raise AssertionError(f"Missing field {name} in HTML form")
    return inputs.values[name]


class Client:
    def __init__(self, base_url):
        self.base_url = base_url
        self.cookies = CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))

    def request(self, path, payload=None, *, method=None, headers=None):
        request = Request(self.base_url + path, data=payload, method=method, headers=headers or {})
        try:
            response = self.opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            url = urlsplit(response.url)
            return response.status, url.path, response.read().decode("utf-8")

    def api(self, method, path, data=None, *, confirmation=None, origin=None, cookie=None):
        headers = {"Origin": self.base_url if origin is None else origin}
        if confirmation is not None:
            headers["X-Confirmation-Code"] = confirmation
        if cookie is not None:
            headers["Cookie"] = cookie
        payload = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(data).encode("utf-8")
        status, _, body = self.request(path, payload, method=method, headers=headers)
        return status, json.loads(body) if body else None

    def form(self, page, action, **fields):
        data = {"csrf": form_value(page, "csrf"), **fields}
        return self.request(f"/action/{action}", urlencode(data).encode())

    def session_cookie(self):
        return next(cookie for cookie in self.cookies if cookie.name == "robotaxi_session")


class ScenarioTest(unittest.TestCase):
    def setUp(self):
        self.timestamp = 1_800_000_000
        for module in (accounts, application, orders, support, views):
            self.enterContext(patch.object(module, "now", side_effect=self.clock))
        codes = count(271_142)
        self.enterContext(patch.object(accounts.secrets, "randbelow", side_effect=lambda _: next(codes)))
        self.mail = []
        self.smtp = self.enterContext(patch.object(notifications.smtplib, "SMTP"))
        self.smtp.return_value.__enter__.return_value.send_message.side_effect = self.mail.append

        self.provider_calls = Counter()
        self.provider_responses = {}
        self.enterContext(patch.object(maps, "urlopen", side_effect=self.map_provider))
        self.enterContext(patch.object(maps, "sleep"))
        self.enterContext(patch.object(maps, "GEOCODER", "https://geocoder.invalid"))
        self.enterContext(patch.object(maps, "ROUTER", "https://router.invalid/route/v1/driving"))
        self.clear_map_cache()
        self.addCleanup(self.clear_map_cache)

        directory = self.enterContext(TemporaryDirectory())
        self.db_path = Path(directory) / "scenario.sqlite3"
        storage.initialize(self.db_path)
        self.connect = storage.connect
        self.enterContext(patch.object(storage, "connect", side_effect=self.connect_server))
        self.enterContext(redirect_stderr(StringIO()))

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_port}"
        self.client = self.new_client()

    def connect_server(self, **kwargs):
        return self.connect(self.db_path, **kwargs)

    def clock(self):
        return self.timestamp

    def advance(self, seconds):
        self.timestamp += seconds

    def new_client(self):
        return Client(self.url)

    def inbox(self, phone=PHONE, *, deletion=False):
        subject = "Удаление аккаунта RoboTaxi" if deletion else "Код подтверждения RoboTaxi"
        return [message for message in self.mail
                if str(message["To"]) == f"{phone.lstrip('+')}@robotaxi.test" and str(message["Subject"]) == subject]

    def received_code(self, phone=PHONE, *, deletion=False):
        message = self.inbox(phone, deletion=deletion)[-1].get_content()
        return re.search(r"\b[0-9]{6}\b", message)[0]

    def query(self, sql, *parameters):
        with self.connect(self.db_path) as db:
            return [tuple(row) for row in db.execute(sql, parameters).fetchall()]

    def assert_page(self, response, path, text=None, *, status=200):
        actual_status, actual_path, body = response
        self.assertEqual((actual_status, actual_path), (status, path), body[:1200])
        if text is not None:
            self.assertIn(text, body)
        self.assertNotIn("{{!", body)
        return body

    def assert_api(self, response, status, text=None):
        actual_status, body = response
        self.assertEqual(actual_status, status, str(body)[:1200])
        if text is not None:
            self.assertIn(text, body["error"])
        return body

    def login(self, client=None, phone=PHONE):
        client = self.client if client is None else client
        page = self.assert_page(client.request("/index.html"), "/index.html")
        code_page = self.assert_page(client.form(page, "request_code", phone=phone), "/code_sent.html")
        return self.assert_page(
            client.form(code_page, "verify_code", code=self.received_code(phone)), "/order.html"
        )

    def quote(self, client=None, **overrides):
        client = self.client if client is None else client
        data = {"from": PICKUP, "to": DESTINATION, "pickup_minutes": 0, "seats": 1, **overrides}
        return self.assert_api(client.api("POST", "/api/orders/quote", data), 200)

    def place_order(self, client=None):
        client = self.client if client is None else client
        quote = self.quote(client)
        return self.assert_api(client.api("POST", "/api/orders", {"quote_token": quote["token"]}), 201)

    @staticmethod
    def clear_map_cache():
        maps._query_address.cache_clear()
        maps.road_route.cache_clear()

    def provider_reply(self, service, response):
        self.provider_responses[service] = response
        self.clear_map_cache()

    def map_provider(self, request, *, timeout):
        url = urlsplit(request.full_url)
        params = parse_qs(url.query)
        if url.hostname == "router.invalid":
            service = "route"
        elif url.hostname == "geocoder.invalid":
            service = url.path.lstrip("/")
        else:
            raise AssertionError(f"Unexpected external request to {url.hostname}")
        self.provider_calls[service] += 1
        if service in self.provider_responses:
            data = self.provider_responses[service]
        elif service == "route":
            data = ROUTE
        elif service == "search":
            address = params["q"][0]
            data = [self.address(True)] if "Ленина" in address else (
                [self.address(False)] if "Революционная" in address else []
            )
        elif service == "reverse":
            data = self.address(float(params["lat"][0]) < 54.74)
        else:
            raise AssertionError(f"Unexpected map service {service}")
        if isinstance(data, Exception):
            raise data
        return BytesIO(json.dumps(data).encode("utf-8"))

    @staticmethod
    def address(pickup):
        return {
            "lat": "54.7348" if pickup else "54.7435",
            "lon": "55.9515" if pickup else "55.9617",
            "address": {
                "city": "Уфа",
                "road": "улица Ленина" if pickup else "Революционная улица",
                "house_number": "18" if pickup else "45",
            },
        }
