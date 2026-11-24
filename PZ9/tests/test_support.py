"""Run passenger support submissions, readback, validation, and access control."""

import json
import unittest

from workflow_fixture import ScenarioTest, form_value


class SupportTests(ScenarioTest):
    def test_guest_and_empty_support(self):
        for page in ("/support.html", "/contact.html", "/ticket.html?id=1"):
            self.assert_page(self.client.request(page), "/index.html", "Войти по номеру")
        login = self.assert_page(self.client.request("/index.html"), "/index.html")
        self.assert_page(self.client.form(login, "ticket", topic="car", message="Проверка"), "/index.html")
        self.assert_api(self.client.api("POST", "/api/tickets", {"topic": "car", "message": "Проверка"}), 401)
        self.assert_api(self.client.api("GET", "/api/tickets/1"), 401)

        self.login()
        support = self.assert_page(self.client.request("/support.html"), "/support.html", "Написать в поддержку")
        self.assertNotIn("Мои обращения", support)
        for text in ("Как найти свой автомобиль?", "Как открыть двери?", "Журнал действий"):
            self.assertIn(text, support)
        contact = self.assert_page(self.client.request("/contact.html"), "/contact.html", "Обращение без заказа")
        self.assertEqual(form_value(contact, "order"), "")
        self.assertEqual(self.query("SELECT COUNT(*) FROM tickets"), [(0,)])

    def test_form_without_order_saves_and_escapes_message(self):
        self.login()
        form = self.assert_page(self.client.request("/contact.html"), "/contact.html")
        message = "<b>Не вижу машину</b>"
        card = self.assert_page(self.client.form(form, "ticket", topic="car", message=f"  {message} \n", order=""),
                                "/ticket.html", "Обращение сохранено")
        self.assertIn("SUP-0842", card)
        self.assertIn("Обращение без заказа", card)
        self.assertIn("&lt;b&gt;Не вижу машину&lt;/b&gt;", card)
        self.assertNotIn(message, card)

        ticket = self.assert_api(self.client.api("GET", "/api/tickets/1"), 200)
        self.assertEqual(ticket["message"], message)
        self.assertEqual(ticket["topic_label"], "Не могу найти автомобиль")
        self.assertIsNone(ticket["order_id"])
        self.assertIsNone(ticket["order_code"])
        self.assertEqual(self.query("SELECT passenger_id, order_id, topic, message FROM tickets"),
                         [(ticket["passenger_id"], None, "car", message)])
        self.assert_page(self.client.request("/support.html"), "/support.html", "SUP-0842")
        self.assert_page(self.client.request("/ticket.html?id=1"), "/ticket.html", "SUP-0842")

    def test_ticket_for_order_round_trips_between_form_api_and_database(self):
        self.login()
        order = self.place_order()
        form = self.assert_page(self.client.request("/contact.html"), "/contact.html", order["code"])
        self.assertEqual(form_value(form, "order"), str(order["id"]))
        self.assert_page(self.client.form(form, "ticket", topic="ride", message="Где машина?", order=order["id"]),
                         "/ticket.html", order["code"])
        first = self.assert_api(self.client.api("GET", "/api/tickets/1"), 200)
        self.assertEqual(first["order_id"], order["id"])
        self.assertEqual(first["order_code"], order["code"])
        self.assertEqual(first["passenger_id"], order["passenger_id"])

        self.assert_api(self.client.api("POST", f"/api/orders/{order['id']}/cancel"), 200)
        form = self.assert_page(self.client.request("/contact.html"), "/contact.html", order["code"])
        self.assertEqual(form_value(form, "order"), str(order["id"]))
        second = self.assert_api(self.client.api("POST", "/api/tickets", {
            "topic": "payment", "message": "Вопрос о стоимости", "order_id": order["id"],
        }), 201)
        self.assertEqual(self.assert_api(self.client.api("GET", f"/api/tickets/{second['id']}"), 200), second)
        self.assert_page(self.client.request(f"/ticket.html?id={second['id']}"), "/ticket.html", second["message"])
        page = self.assert_page(self.client.request("/support.html"), "/support.html", second["code"])
        self.assertLess(page.index(second["code"]), page.index(first["code"]))
        self.assertEqual(self.query("SELECT order_id, topic FROM tickets ORDER BY id"),
                         [(order["id"], "ride"), (order["id"], "payment")])

    def test_all_topic_labels_and_exact_message_limit(self):
        self.login()
        labels = {
            "car": "Не могу найти автомобиль",
            "ride": "Проблема с поездкой",
            "payment": "Вопрос по оплате",
            "other": "Другое",
        }
        for topic, label in labels.items():
            with self.subTest(topic=topic):
                message = "Я" * 2000
                result = self.assert_api(self.client.api("POST", "/api/tickets", {"topic": topic, "message": message}), 201)
                self.assertEqual(result["topic_label"], label)
                self.assertEqual(result["message"], message)
                self.assertIsNone(result["order_id"])
                self.assert_page(self.client.request(f"/ticket.html?id={result['id']}"), "/ticket.html", label)
        self.assertEqual(self.query("SELECT length(message) FROM tickets"), [(2000,)] * 4)

    def test_invalid_form_and_json_never_create_ticket(self):
        self.login()
        form = self.assert_page(self.client.request("/contact.html"), "/contact.html")
        for topic, text, expected in (
            ("unknown", "Вопрос", "Выберите тему"),
            ("car", " \n ", "Заполните поле"),
            ("car", "a" * 2001, "до 2000 символов"),
            ("car", "a\x00b", "Проверьте значение"),
        ):
            with self.subTest(topic=topic, msg_size=len(text)):
                self.assert_page(self.client.form(form, "ticket", topic=topic, message=text),
                                 "/action/ticket", expected, status=422)
                self.assert_api(self.client.api("POST", "/api/tickets", {"topic": topic, "message": text}), 422, expected)
        self.assert_page(self.client.form(form, "ticket", csrf="", topic="car", message="Вопрос"),
                         "/action/ticket", "Форма устарела", status=403)
        for payload in (
            {}, {"topic": "car", "message": 123}, {"topic": "car", "message": "Вопрос", "order_id": "1"},
            {"topic": "car", "message": "Вопрос", "passenger_id": 2},
        ):
            with self.subTest(payload=payload):
                self.assert_api(self.client.api("POST", "/api/tickets", payload), 422)
        invalid_input = self.client.request("/api/tickets", b"{", method="POST", headers={"Content-Type": "application/json"})
        self.assertEqual(invalid_input[0], 400)
        self.assertIn("Некорректный запрос", json.loads(invalid_input[2])["error"])
        wrong_type = self.client.request("/api/tickets", b"message=x", method="POST")
        self.assertEqual(wrong_type[0], 415)
        self.assertEqual(self.query("SELECT COUNT(*) FROM tickets"), [(0,)])

    def test_ownership_missing_ticket_and_rejected_foreign_associations(self):
        self.login()
        order = self.place_order()
        ticket = self.assert_api(self.client.api("POST", "/api/tickets", {
            "topic": "car", "message": "Только для владельца", "order_id": order["id"],
        }), 201)
        other = self.new_client()
        self.login(other, "+79000001002")
        for identifier in (str(ticket["id"]), "999", "bad"):
            with self.subTest(identifier=identifier):
                self.assert_api(other.api("GET", f"/api/tickets/{identifier}"), 404)
                self.assert_page(other.request(f"/ticket.html?id={identifier}"),
                                 "/ticket.html", "Обращение не найдено", status=404)
        page = self.assert_page(other.request("/support.html"), "/support.html")
        self.assertNotIn(ticket["code"], page)
        self.assertNotIn(ticket["message"], page)
        for foreign_id in (order["id"], 999):
            self.assert_api(other.api("POST", "/api/tickets", {
                "topic": "car", "message": "Чужой заказ", "order_id": foreign_id,
            }), 404, "Заказ не найден")
        self.assertEqual(self.query("SELECT COUNT(*) FROM tickets"), [(1,)])

        form = self.assert_page(other.request("/contact.html"), "/contact.html", "Обращение без заказа")
        card = self.assert_page(other.form(form, "ticket", topic="car", message="Через форму", order=order["id"]),
                                "/ticket.html", "Обращение без заказа")
        self.assertIn("Через форму", card)
        self.assertEqual(self.query("SELECT order_id FROM tickets ORDER BY id"), [(order["id"],), (None,)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
