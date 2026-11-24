"""Start the standalone RoboTaxi server on the loopback interface."""

import argparse
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
from urllib.parse import parse_qs, urlsplit

from robotaxi import accounts, api, application, storage

STATIC = storage.ROOT / "static"
COOKIE = "robotaxi_session"
CSP = (
    "default-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'"
)
LOG = logging.getLogger("robotaxi")


def read_fields(text):
    return {key: values[-1] for key, values in parse_qs(text, keep_blank_values=True, max_num_fields=24).items()}


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_DELETE(self):
        self.handle_request()

    def handle_request(self):
        accepted_hosts = {"127.0.0.1", "localhost"}
        host_name = self.headers.get("Host", "").split(":", maxsplit=1)[0].lower()
        if host_name not in accepted_hosts:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        url = urlsplit(self.path)
        if self.command in ("GET", "HEAD") and url.path.startswith("/static/"):
            self.serve_static(url.path.removeprefix("/static/"))
            return
        try:
            if url.path.startswith("/api/"):
                self.handle_api(url)
                return
            if self.command in ("GET", "HEAD"):
                if url.path == "/docs":
                    self.serve_static("docs.html")
                    return
                if url.path == "/openapi.json":
                    self.send_json(200, api.openapi())
                    return
            if self.command == "DELETE":
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
                return
            self.send_page(self.route(url))
        except (UnicodeError, ValueError):
            if url.path.startswith("/api/"):
                self.send_json(400, {"error": "Некорректный запрос. Проверьте JSON или параметры."})
            else:
                self.send_page(application.error_page(400, "Некорректный запрос", "Проверьте введённые данные."))
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            LOG.exception("Request failed")
            if url.path.startswith("/api/"):
                self.send_json(500, {"error": "Ошибка приложения. Повторите действие позже."})
            else:
                self.send_page(application.error_page(500, "Ошибка приложения", "Повторите действие позже."))

    def handle_api(self, url):
        token = self.session_cookie()
        if self.command in ("GET", "HEAD"):
            with storage.connect() as db:
                session = accounts.get_session(db, token)
                status, data = api.read_resource(db, session, url.path, read_fields(url.query))
            self.send_json(status, data)
            return

        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{self.headers.get('Host')}":
            self.send_json(403, {"error": "Запрос пришёл с другого сайта."})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 <= length <= 64_000:
            self.send_json(413, {"error": "Сократите тело запроса."})
            return
        if length and self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "Отправьте данные в формате application/json."})
            return
        data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if not isinstance(data, dict) or len(data) > 24:
            self.send_json(400, {"error": "Тело запроса должно быть JSON-объектом."})
            return
        confirmation = self.headers.get("X-Confirmation-Code", "")
        # A route calculation contacts external services and takes its write lock only when saving.
        with storage.connect(write=url.path != "/api/orders/quote") as db:
            session = accounts.get_session(db, token)
            result = api.write_resource(db, session, self.command, url.path, data, confirmation)
        self.send_json(result.status, result.body, cookie=result.cookie)

    def route(self, url):
        token = self.session_cookie()
        if self.command == "POST":
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 64_000:
                return application.error_page(413, "Слишком большой запрос", "Сократите введённый текст.")
            if self.headers.get_content_type() != "application/x-www-form-urlencoded":
                return application.error_page(415, "Формат запроса не поддерживается", "Отправьте данные через форму.")
            data = read_fields(self.rfile.read(length).decode("utf-8"))
            operation = url.path.removeprefix("/action/") if url.path.startswith("/action/") else ""
            # Route lookup happens before SQLite takes a write lock.
            with storage.connect(write=operation != "quote") as db:
                session = accounts.get_session(db, token)
                return application.post_action(db, operation, data, session)
        page = "index" if url.path == "/" else url.path.removeprefix("/").removesuffix(".html")
        with storage.connect() as db:
            session = accounts.get_session(db, token)
            return application.get_page(db, page, read_fields(url.query), session)

    def session_cookie(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        value = cookies.get(COOKIE)
        return value.value if value else None

    def headers_for(self, status, content_type, length):
        self.send_response(status)
        if content_type is not None:
            self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")

    def send_session_cookie(self, value):
        if value is not None:
            age = accounts.SESSION_AGE if value else 0
            self.send_header("Set-Cookie", f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}")

    def send_page(self, response):
        payload = response.html.encode("utf-8")
        self.headers_for(response.status, "text/html; charset=utf-8", len(payload))
        self.send_header("Cache-Control", "no-store")
        if response.location:
            self.send_header("Location", response.location)
        self.send_session_cookie(response.cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def serve_static(self, resource):
        path = (STATIC / resource).resolve()
        if not path.is_relative_to(STATIC) or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        payload = path.read_bytes()
        self.headers_for(200, media_type, len(payload))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def send_json(self, status, data, *, cookie=None):
        empty = status == 204
        payload = b"" if empty else json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.headers_for(status, None if empty else "application/json; charset=utf-8", None if empty else len(payload))
        self.send_header("Cache-Control", "no-store")
        self.send_session_cookie(cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000, help="local port (default: 8000)")
    args = parser.parse_args()
    storage.initialize()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        host, port = server.server_address
        print(f"RoboTaxi: http://{host}:{port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
