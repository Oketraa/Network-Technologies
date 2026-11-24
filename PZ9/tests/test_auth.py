"""Run the passenger sign-in, session, profile, and account-removal scenario."""

import unittest

from workflow_fixture import PHONE, ScenarioTest, accounts, form_value


class AuthorizationTests(ScenarioTest):
    def test_guest_and_form_protection(self):
        for page in ("order", "profile", "support", "code_sent"):
            with self.subTest(page=page):
                self.assert_page(self.client.request(f"/{page}.html"), "/index.html", "Войти по номеру")
        login = self.assert_page(self.client.request("/index.html"), "/index.html")
        self.assertEqual(form_value(login, "phone"), "")
        self.assert_page(self.client.form(login, "request_code", csrf="other-token", phone=PHONE),
                         "/action/request_code", "Форма устарела", status=403)
        self.assert_api(self.client.api("GET", "/api/me"), 401)
        self.assert_api(self.client.api("POST", "/api/auth/verify-code", {"code": "123456"}), 422, "Запросите новый код")
        self.assertEqual(self.mail, [])

    def test_html_sign_in_rotates_cookie_and_reuses_passenger_after_logout(self):
        login = self.assert_page(self.client.request("/index.html"), "/index.html")
        guest = self.client.session_cookie()
        self.assertTrue(guest.has_nonstandard_attr("HttpOnly"))
        self.assertEqual(guest.get_nonstandard_attr("SameSite"), "Strict")
        self.assertEqual(guest.path, "/")
        page = self.assert_page(self.client.form(login, "request_code", phone="+7 (900) 000-10-01"),
                                "/code_sent.html", "Код отправлен")
        code = self.received_code()
        self.assertNotIn(code, page)
        self.assertIn("5 минут", self.inbox()[0].get_content())
        digest, passenger = self.query("SELECT challenge_digest, account_id FROM sessions")[0]
        self.assertNotEqual(digest, code)
        self.assertIsNone(passenger)
        self.assert_page(self.client.form(page, "verify_code", code=code), "/order.html")
        token = self.client.session_cookie().value
        self.assertNotEqual(token, guest.value)
        self.assertEqual(self.query("SELECT token, challenge_digest FROM sessions"), [(token, None)])
        profile = self.assert_api(self.client.api("GET", "/api/me"), 200)
        self.assertEqual(profile["phone"], PHONE)

        profile_page = self.assert_page(self.client.request("/profile.html"), "/profile.html", profile["name"])
        self.assert_page(self.client.form(profile_page, "signout"), "/index.html")
        self.assert_api(self.client.api("GET", "/api/me", cookie=f"robotaxi_session={token}"), 401)
        self.login()
        self.assertEqual(self.assert_api(self.client.api("GET", "/api/me"), 200), profile)
        self.assertEqual(self.query("SELECT COUNT(*) FROM accounts"), [(1,)])

    def test_phone_formats_and_bad_form_values(self):
        for value in ("", "123", "+1 900 000 1001", "900ABC1001", "+799900010001"):
            with self.subTest(phone=value):
                page = self.assert_page(self.client.request("/index.html"), "/index.html")
                self.assert_page(self.client.form(page, "request_code", phone=value),
                                 "/action/request_code", "Введите российский номер", status=422)
        self.assertEqual(self.mail, [])
        for value in ("9000001001", "8 (900) 000-10-01", PHONE):
            with self.subTest(phone=value):
                client = self.new_client()
                body = self.assert_api(client.api("POST", "/api/auth/request-code", {"phone": value}), 202)
                self.assertEqual(body["phone"], PHONE)
                self.assert_api(client.api("POST", "/api/auth/verify-code", {"code": self.received_code()}), 200)
        self.assertEqual(self.query("SELECT phone FROM accounts"), [(PHONE,)])

    def test_wrong_codes_attempt_limit_and_resend_boundary(self):
        login = self.assert_page(self.client.request("/index.html"), "/index.html")
        page = self.assert_page(self.client.form(login, "request_code", phone=PHONE), "/code_sent.html")
        first_code = self.received_code()
        self.assert_page(self.client.form(login, "request_code", phone=PHONE), "/code_sent.html")
        self.assertEqual(len(self.inbox()), 1)
        for wrong_code in ("abc", "000000", "000000", "000000", "000000"):
            self.assert_page(self.client.form(page, "verify_code", code=wrong_code), "/action/verify_code",
                             "Неверный код", status=422)
        self.assertEqual(self.query("SELECT attempts FROM sessions"), [(accounts.MAX_ATTEMPTS,)])
        self.assert_page(self.client.form(page, "verify_code", code=first_code), "/action/verify_code",
                         "Попытки исчерпаны", status=422)
        self.advance(accounts.RESEND_DELAY - 1)
        self.assert_page(self.client.form(page, "resend_code"), "/action/resend_code", "45 секунд", status=422)
        self.advance(1)
        page = self.assert_page(self.client.form(page, "resend_code"), "/code_sent.html")
        second_code = self.received_code()
        self.assertNotEqual(first_code, second_code)
        self.assertEqual(self.query("SELECT attempts FROM sessions"), [(0,)])
        self.assert_page(self.client.form(page, "verify_code", code=first_code), "/action/verify_code",
                         "Неверный код", status=422)
        self.assert_page(self.client.form(page, "verify_code", code=second_code), "/order.html")

    def test_api_code_cannot_be_used_in_another_session_and_expires(self):
        request = {"phone": PHONE}
        self.assert_api(self.client.api("POST", "/api/auth/request-code", request), 202)
        code = self.received_code()
        token = self.client.session_cookie().value
        second = self.new_client()
        self.assert_api(second.api("POST", "/api/auth/verify-code", {"code": code}), 401)
        self.assert_api(second.api("POST", "/api/auth/request-code", request), 202)
        self.assert_api(second.api("POST", "/api/auth/verify-code", {"code": code}), 422, "Неверный код")
        self.assert_api(self.client.api("POST", "/api/auth/request-code", request), 422, "45 секунд")
        self.advance(accounts.CODE_AGE)
        self.assert_api(self.client.api("POST", "/api/auth/verify-code", {"code": code}), 422, "истёк")
        self.assert_api(self.client.api("POST", "/api/auth/request-code", request), 202)
        self.assert_api(self.client.api("POST", "/api/auth/verify-code", {"code": self.received_code()}), 200)
        self.assert_api(second.api("GET", "/api/me", cookie=f"robotaxi_session={token}"), 401)
        self.assert_api(self.client.api("POST", "/api/auth/verify-code", {"code": self.received_code()}), 409)
        self.assert_api(self.client.api("POST", "/api/auth/request-code", request), 409)
        self.advance(accounts.SESSION_AGE)
        self.assert_api(self.client.api("GET", "/api/me"), 401)
        self.assert_page(self.client.request("/profile.html"), "/index.html")

    def test_api_validation_and_mailpit_failure(self):
        endpoint = "/api/auth/request-code"
        self.assert_api(self.client.api("POST", endpoint, {"phone": PHONE}, origin="https://other.invalid"), 403)
        for payload in ({}, {"phone": 9000001001}, {"phone": "8999"}, {"phone": PHONE, "code": "123456"}):
            with self.subTest(payload=payload):
                self.assert_api(self.client.api("POST", endpoint, payload), 422)
        self.assertEqual(self.mail, [])
        self.smtp.side_effect = OSError("SMTP unavailable")
        self.assert_api(self.client.api("POST", endpoint, {"phone": PHONE}), 422, "Не удалось отправить код")
        self.assertEqual(self.query("SELECT COUNT(*) FROM sessions"), [(0,)])
        self.smtp.side_effect = None
        self.assert_api(self.client.api("POST", endpoint, {"phone": PHONE}), 202)

    def test_profile_changes_and_confirmed_phone_replacement(self):
        self.login()
        other_phone = "+79000001002"
        new_phone = "+79000001003"
        self.login(self.new_client(), other_phone)
        page = self.assert_page(self.client.request("/profile_edit.html"), "/profile_edit.html")
        profile = {"name": "Анна <b>Иванова</b>", "phone": PHONE, "email": "anna@example.test", "payment": "wallet"}
        for update, message in (
            ({"name": " "}, "Имя"),
            ({"email": "not-an-email"}, "адрес электронной почты"),
            ({"payment": "unknown"}, "способ оплаты"),
            ({"phone": other_phone}, "уже используется"),
        ):
            with self.subTest(update=update):
                self.assert_page(self.client.form(page, "profile", **{**profile, **update}),
                                 "/action/profile", message, status=422)

        saved = self.assert_page(self.client.form(page, "profile", **profile), "/profile.html", "Профиль сохранён.")
        self.assertIn("Анна &lt;b&gt;Иванова&lt;/b&gt;", saved)
        self.assertIn("Электронный кошелёк", saved)
        self.assertEqual(len(self.inbox()), 1)

        page = self.assert_page(self.client.request("/profile_edit.html"), "/profile_edit.html")
        code_page = self.assert_page(self.client.form(page, "profile", **{**profile, "phone": new_phone}),
                                     "/phone_code.html", "Код отправлен")
        self.assertEqual(self.assert_api(self.client.api("GET", "/api/me"), 200)["phone"], PHONE)
        previous = self.client.session_cookie().value
        self.assert_page(self.client.form(code_page, "verify_code", code="000000"),
                         "/action/verify_code", "Неверный код", status=422)
        self.assert_page(self.client.form(code_page, "verify_code", code=self.received_code(new_phone)),
                         "/profile.html", "Профиль сохранён.")
        self.assertEqual(self.assert_api(self.client.api("GET", "/api/me"), 200)["phone"], new_phone)
        self.assertNotEqual(self.client.session_cookie().value, previous)
        self.assertEqual(self.query("SELECT COUNT(*) FROM accounts WHERE phone = ?", PHONE), [(0,)])

    def test_delete_requires_own_code_and_removes_dependent_records(self):
        profile = self.login()
        passenger = self.assert_api(self.client.api("GET", "/api/me"), 200)
        second_session = self.new_client()
        self.login(second_session)
        other = self.new_client()
        self.login(other, "+79000001002")
        self.assert_api(other.api("POST", "/api/tickets", {"topic": "other", "message": "Обращение другого пассажира"}), 201)
        self.assert_api(self.new_client().api("DELETE", "/api/me"), 401)
        self.assert_api(self.client.api("DELETE", "/api/me", confirmation=self.received_code()), 422, "истёк")

        order = self.place_order()
        self.assert_api(self.client.api("POST", "/api/me/deletion-code"), 409, "активный заказ")
        self.assert_api(self.client.api("DELETE", "/api/me"), 409, "активный заказ")
        self.assertEqual(self.inbox(deletion=True), [])
        self.assert_api(self.client.api("POST", "/api/tickets", {
            "topic": "ride", "message": "Обращение по поездке", "order_id": order["id"],
        }), 201)
        page = profile
        for action, path in (("arrive", "/arrived.html"), ("unlock", "/unlocked.html"),
                             ("start", "/trip.html"), ("finish", "/completed.html")):
            page = self.assert_page(self.client.form(page, action, order=order["id"]), path)
        self.assert_page(self.client.form(page, "feedback", order=order["id"], rating="5"), "/thankyou.html")
        self.assertEqual(self.query("SELECT COUNT(*) FROM feedback"), [(1,)])

        self.assert_api(self.client.api("POST", "/api/me/deletion-code"), 202)
        old_code = self.received_code(deletion=True)
        self.assert_api(second_session.api("DELETE", "/api/me", confirmation=old_code), 422)
        self.assert_api(self.client.api("DELETE", "/api/me", confirmation="000000"), 422, "Неверный код")
        self.advance(accounts.CODE_AGE)
        self.assert_api(self.client.api("DELETE", "/api/me", confirmation=old_code), 422, "истёк")
        self.assert_api(self.client.api("POST", "/api/me/deletion-code"), 202)
        self.assertIsNone(self.assert_api(
            self.client.api("DELETE", "/api/me", confirmation=self.received_code(deletion=True)), 204
        ))
        self.assert_api(self.client.api("GET", "/api/me"), 401)
        self.assert_api(second_session.api("GET", "/api/me"), 401)
        self.assert_api(other.api("GET", "/api/me"), 200)
        self.assertEqual(self.query("SELECT id FROM accounts WHERE id = ?", passenger["id"]), [])
        self.assertEqual(self.query("SELECT COUNT(*) FROM orders"), [(0,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM feedback"), [(0,)])
        self.assertEqual(self.query("SELECT message FROM tickets"), [("Обращение другого пассажира",)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
