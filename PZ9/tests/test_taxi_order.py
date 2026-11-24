"""Run taxi booking, vehicle allocation, cancellation, and trip completion."""

from itertools import product
import json
import unittest
from urllib.error import HTTPError

from workflow_fixture import DESTINATION, DESTINATION_POINT, PICKUP, PICKUP_POINT, ScenarioTest, form_value


class TaxiOrderTests(ScenarioTest):
    def test_guest_empty_trip_and_unknown_order(self):
        self.assert_page(self.client.request("/order.html"), "/index.html", "Войти по номеру")
        self.assert_api(self.client.api("POST", "/api/orders/quote"), 401)
        self.assert_api(self.client.api("POST", "/api/orders"), 401)
        self.assert_api(self.client.api("GET", "/api/orders/1"), 401)
        self.assert_api(self.client.api("GET", "/api/map/address?point=54.7348,55.9515"), 401)
        self.login()
        self.assert_page(self.client.request("/active.html"), "/active.html", "У вас пока нет поездок")
        self.assert_page(self.client.request("/history.html"), "/history.html", "Здесь появятся ваши заказы")
        self.assert_page(self.client.request("/quote.html"), "/order.html")
        self.assert_page(self.client.request("/active.html?id=999"), "/active.html", "Заказ не найден", status=404)
        self.assert_api(self.client.api("GET", "/api/orders/999"), 404)

    def test_quote_inputs_and_all_pickup_times_and_seat_counts(self):
        self.login()
        modes = (
            {},
            {"from": "", "to": "", "pickup_point": PICKUP_POINT, "dropoff_point": DESTINATION_POINT},
            {"from": "", "pickup_point": PICKUP_POINT},
            {"to": "", "dropoff_point": DESTINATION_POINT},
        )
        for mode, minutes, seats in product(modes, (0, 15, 30), (1, 2, 3, 4)):
            with self.subTest(mode=mode, pickup_minutes=minutes, seats=seats):
                quote = self.quote(pickup_minutes=minutes, seats=seats, **mode)
                self.assertEqual((quote["pickup"], quote["destination"]), (PICKUP, DESTINATION))
                self.assertEqual((quote["pickup_minutes"], quote["seats"]), (minutes, seats))
                self.assertEqual((quote["distance"], quote["duration"], quote["price"]), (72, 16, 349))
                self.assertEqual(len(quote["map"]["geometry"]), 2)
                self.assertEqual(quote["expires"] - self.clock(), 15 * 60)
        self.assertEqual(self.provider_calls, {"search": 2, "reverse": 2, "route": 1})
        self.assertEqual(
            self.assert_api(self.client.api("GET", f"/api/map/address?point={PICKUP_POINT}"), 200),
            {"label": PICKUP},
        )
        self.assertEqual(self.query("SELECT COUNT(*) FROM orders"), [(0,)])

    def test_invalid_routes_and_missing_geocoded_address(self):
        self.login()
        valid = {"from": PICKUP, "to": DESTINATION, "pickup_minutes": 0, "seats": 1}
        for change, message in (
            ({"from": ""}, "Укажите адрес"),
            ({"to": "Неизвестное место"}, "не найден"),
            ({"from": "Уфа, улица Ленина, 999"}, "Дом № 999"),
            ({"from": "x" * 141}, "до 140 символов"),
            ({"pickup_point": "95,56"}, "Укажите точку"),
            ({"pickup_point": "54.7,181"}, "Укажите точку"),
            ({"pickup_point": "NaN,56"}, "Укажите точку"),
            ({"pickup_point": "54.7"}, "Укажите точку"),
            ({"pickup_point": PICKUP_POINT, "dropoff_point": PICKUP_POINT}, "разные точки"),
            ({"pickup_minutes": 60}, "время подачи"),
            ({"seats": 0}, "число пассажиров"),
            ({"seats": 5}, "число пассажиров"),
        ):
            with self.subTest(change=change):
                self.assert_api(self.client.api("POST", "/api/orders/quote", {**valid, **change}), 422, message)
        self.assert_api(self.client.api("GET", "/api/map/address?point=bad"), 422, "Укажите точку")
        self.assertEqual(self.query("SELECT quote FROM sessions"), [(None,)])

    def test_routing_and_address_provider_failures_and_recovery(self):
        self.login()
        valid = {"from": PICKUP, "to": DESTINATION, "pickup_minutes": 0, "seats": 1}
        self.provider_reply("search", TimeoutError("geocoder timed out"))
        self.assert_api(self.client.api("POST", "/api/orders/quote", valid), 422, "Сервис адресов")
        for fault, message in (
            (HTTPError("https://router.invalid", 400, "NoSegment", None, None), "найти дорогу"),
            (TimeoutError("router timed out"), "Сервис маршрутов"),
            ({"code": "NoRoute"}, "найти дорогу"),
            ({"code": "Ok", "routes": []}, "не вернул маршрут"),
        ):
            with self.subTest(fault=fault):
                self.provider_reply("route", fault)
                data = {**valid, "pickup_point": PICKUP_POINT, "dropoff_point": DESTINATION_POINT}
                self.assert_api(self.client.api("POST", "/api/orders/quote", data), 422, message)

        self.provider_reply("reverse", TimeoutError("reverse lookup timed out"))
        self.assert_api(self.client.api("GET", f"/api/map/address?point={PICKUP_POINT}"), 422, "Сервис адресов")
        self.provider_responses.pop("route")
        self.clear_map_cache()
        quote = self.quote(**{"from": "", "to": "", "pickup_point": PICKUP_POINT, "dropoff_point": DESTINATION_POINT})
        self.assertEqual(quote["pickup"], "54.734800, 55.951500")
        self.assertEqual(quote["destination"], "54.743500, 55.961700")

    def test_quote_expires_is_replaced_and_confirmation_is_idempotent(self):
        self.login()
        self.assert_api(self.client.api("POST", "/api/orders", {"quote_token": "missing"}), 422, "Расчёт устарел")
        first = self.quote()
        second = self.quote()
        self.assertNotEqual(first["token"], second["token"])
        self.assert_api(self.client.api("POST", "/api/orders", {"quote_token": first["token"]}), 422, "Расчёт устарел")
        self.advance(15 * 60)
        self.assert_page(self.client.request("/quote.html"), "/order.html")
        self.assert_api(self.client.api("POST", "/api/orders", {"quote_token": second["token"]}), 422, "Расчёт устарел")
        current = self.quote()
        confirmation = {"quote_token": current["token"]}
        order = self.assert_api(self.client.api("POST", "/api/orders", confirmation), 201)
        self.advance(15 * 60)
        self.assertEqual(self.assert_api(self.client.api("POST", "/api/orders", confirmation), 200), order)
        another = self.quote()
        self.assert_api(self.client.api("POST", "/api/orders", {"quote_token": another["token"]}), 422, "активный заказ")
        self.assertEqual(self.query("SELECT COUNT(*) FROM orders"), [(1,)])

    def test_html_booking_and_cancellation_before_or_after_arrival(self):
        order_page = self.login()
        for arrive_first in (False, True):
            with self.subTest(arrive_first=arrive_first):
                quote_page = self.assert_page(self.client.form(order_page, "quote", **{
                    "from": PICKUP, "to": DESTINATION, "when": "15", "seats": "2",
                }), "/quote.html", "349 ₽")
                self.assertIn("Через 15 минут", quote_page)
                self.assertIn("2 пассажира", quote_page)
                token = form_value(quote_page, "quote")
                active = self.assert_page(self.client.form(quote_page, "confirm", quote=token),
                                          "/active.html", "Автомобиль №038")
                order_id = int(form_value(active, "order"))
                self.assertEqual(self.client.form(quote_page, "confirm", quote=token)[0:2], (200, "/active.html"))
                fields = self.query("SELECT pickup_minutes, seats, pickup_at, price, route_map FROM orders WHERE id = ?", order_id)
                self.assertEqual(fields[0][:4], (15, 2, self.clock() + 900, 349))
                self.assertEqual(len(json.loads(fields[0][4])["geometry"]), 2)
                if arrive_first:
                    active = self.assert_page(self.client.form(active, "arrive", order=order_id), "/arrived.html")
                self.assert_page(self.client.form(active, "cancel", order=order_id), "/cancel.html", "Заказ отменён")
                cancelled = self.assert_api(self.client.api("POST", f"/api/orders/{order_id}/cancel"), 200)
                self.assertEqual(cancelled["status"], "cancelled")
                self.assertEqual(self.query("SELECT payment_status FROM orders WHERE id = ?", order_id), [("void",)])
                self.assert_page(self.client.request("/history.html"), "/history.html", cancelled["code"])

    def test_trip_state_machine_for_normal_and_early_finish(self):
        page = self.login()
        for final_action in ("finish", "early_finish"):
            with self.subTest(final_action=final_action):
                order = self.place_order()
                path = f"/api/orders/{order['id']}"
                for action, expected_page, state, invalid_action in (
                    ("arrive", "/arrived.html", "arrived", "unlock"),
                    ("unlock", "/unlocked.html", "unlocked", "start"),
                    ("start", "/trip.html", "riding", "finish"),
                ):
                    self.assert_page(self.client.form(page, invalid_action, order=order["id"]),
                                     f"/action/{invalid_action}", "текущем этапе", status=422)
                    page = self.assert_page(self.client.form(page, action, order=order["id"]), expected_page)
                    self.assert_page(self.client.form(page, action, order=order["id"]), expected_page)
                    self.assertEqual(self.assert_api(self.client.api("GET", path), 200)["status"], state)
                self.assert_api(self.client.api("POST", path + "/cancel"), 409, "текущем этапе")
                confirmation = self.assert_page(self.client.request(f"/early_stop.html?id={order['id']}"),
                                                "/early_stop.html", "Завершить поездку раньше?")
                self.assert_page(self.client.request(f"/trip.html?id={order['id']}"), "/trip.html", "Вы в пути")
                if final_action == "early_finish":
                    page = confirmation
                completion_text = "Выполнена досрочная остановка" if final_action == "early_finish" else "Вы приехали!"
                page = self.assert_page(self.client.form(page, final_action, order=order["id"]),
                                        "/completed.html", completion_text)
                self.assert_page(self.client.form(page, final_action, order=order["id"]), "/completed.html")
                self.assert_page(self.client.request("/active.html"), "/completed.html", completion_text)
                self.assertEqual(self.query("SELECT status, payment_status, completion FROM orders WHERE id = ?", order["id"]),
                                 [("completed", "charged", final_action)])

    def test_feedback_is_validated_and_saved_once(self):
        page = self.login()
        order_id = self.place_order()["id"]
        self.assert_page(self.client.form(page, "feedback", order=order_id, rating=5),
                         "/action/feedback", "завершённую поездку", status=422)
        for action, path in (("arrive", "/arrived.html"), ("unlock", "/unlocked.html"),
                             ("start", "/trip.html"), ("finish", "/completed.html")):
            page = self.assert_page(self.client.form(page, action, order=order_id), path)
        self.assert_page(self.client.request(f"/thankyou.html?id={order_id}"), "/completed.html")
        for rating, comment, expected in (
            ("", "", "оценку"), ("0", "", "оценку"), ("6", "", "оценку"),
            ("1", "a" * 1001, "Комментарий"),
        ):
            with self.subTest(rating=rating, comment_length=len(comment)):
                self.assert_page(self.client.form(page, "feedback", order=order_id, rating=rating, comment=comment),
                                 "/action/feedback", expected, status=422)
        self.assert_page(self.client.form(page, "feedback", order=order_id, rating=1, comment="a" * 1000),
                         "/thankyou.html", "Спасибо за отзыв")
        self.assert_page(self.client.form(page, "feedback", order=order_id, rating=5), "/thankyou.html")
        self.assert_page(self.client.request(f"/completed.html?id={order_id}"), "/completed.html", "1 из 5")
        self.assertEqual(self.query("SELECT rating, length(comment) FROM feedback"), [(1, 1000)])

    def test_fleet_exhaustion_releases_vehicle_after_cancellation(self):
        fleet = self.query("SELECT id FROM vehicles ORDER BY id")
        booked = []
        for index, (vehicle,) in enumerate(fleet):
            client = self.new_client()
            self.login(client, f"+790000011{index:02}")
            order = self.place_order(client)
            self.assertEqual(order["vehicle_id"], vehicle)
            booked.append((client, order))
        self.login()
        quote = self.quote()
        request = {"quote_token": quote["token"]}
        self.assert_api(self.client.api("POST", "/api/orders", request), 422, "нет свободных автомобилей")
        owner, first = booked[0]
        self.assert_api(owner.api("POST", f"/api/orders/{first['id']}/cancel"), 200)
        reassigned = self.assert_api(self.client.api("POST", "/api/orders", request), 201)
        self.assertEqual(reassigned["vehicle_id"], first["vehicle_id"])

    def test_cannot_view_or_change_another_passengers_order(self):
        page = self.login()
        order = self.place_order()
        other = self.new_client()
        other_page = self.login(other, "+79000001002")
        path = f"/api/orders/{order['id']}"
        self.assert_api(other.api("GET", path), 404)
        self.assert_api(other.api("POST", path + "/cancel"), 404)
        self.assert_api(self.client.api("POST", "/api/orders/999/cancel"), 404)
        self.assert_page(other.request(f"/active.html?id={order['id']}"), "/active.html", "Заказ не найден", status=404)
        self.assert_page(other.form(other_page, "arrive", order=order["id"]), "/action/arrive", "Заказ не найден", status=404)
        self.assert_page(self.client.form(page, "arrive", csrf="wrong", order=order["id"]),
                         "/action/arrive", "Форма устарела", status=403)
        self.assertEqual(self.assert_api(self.client.api("GET", path), 200), order)


if __name__ == "__main__":
    unittest.main(verbosity=2)
