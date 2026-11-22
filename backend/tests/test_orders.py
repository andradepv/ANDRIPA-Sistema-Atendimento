from concurrent.futures import ThreadPoolExecutor

from conftest import Customer, close_table, open_table, pg


def _setup(world, client):
    tid, code = world["tables"][0]
    open_table(world["atendente"], tid)
    return tid, Customer(client, code)


def test_customer_menu_and_order(client, world, menu):
    """Cenário D."""
    _, c = _setup(world, client)
    m = c.get("/api/v1/public/menu").json()
    assert m[0]["name"] == "Lanches" and {p["name"] for p in m[0]["products"]} == {"X-Burguer", "Água"}
    bacon = menu["burger"]["option_groups"][0]["options"][0]["id"]
    r = c.post("/api/v1/public/orders", json={"items": [
        {"product_id": menu["burger"]["id"], "quantity": 2, "option_ids": [bacon], "notes": "sem cebola"},
        {"product_id": menu["agua"]["id"], "quantity": 1},
    ]})
    assert r.status_code == 201, r.text
    req = r.json()
    o = req["order"]
    assert req["type"] == "NOVO_PEDIDO" and req["status"] == "PENDENTE"
    assert o["total_cents"] == 2 * (2500 + 500) + 500
    assert o["items"][0]["options"][0]["name"] == "Bacon"
    staff = world["atendente"].get("/api/v1/service-requests").json()
    assert staff["total"] == 1 and staff["items"][0]["table_number"] == 1
    assert staff["items"][0]["order"]["id"] == o["id"]
    assert world["atendente"].get("/api/v1/tables").json()[0]["pending_orders"] == 1


def test_price_manipulation_rejected(client, world, menu):
    _, c = _setup(world, client)
    r = c.post("/api/v1/public/orders", json={"items": [
        {"product_id": menu["burger"]["id"], "quantity": 1, "price_cents": 1}]})
    assert r.status_code == 422  # campos desconhecidos são proibidos
    r = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["burger"]["id"], "quantity": 1}],
                                             "total_cents": 1})
    assert r.status_code == 422
    for q in (0, -1, 51, 10**9):
        assert c.post("/api/v1/public/orders", json={"items": [
            {"product_id": menu["burger"]["id"], "quantity": q}]}).status_code == 422


def test_price_comes_from_catalog_at_confirmation(client, world, menu):
    _, c = _setup(world, client)
    world["admin"].patch(f"/api/v1/menu/products/{menu['agua']['id']}", json={"price_cents": 700})
    o = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]}).json()
    assert o["order"]["total_cents"] == 700
    # Alteração posterior não muda pedido histórico.
    world["admin"].patch(f"/api/v1/menu/products/{menu['agua']['id']}", json={"price_cents": 900})
    again = world["caixa"].get("/api/v1/service-requests").json()["items"][0]
    assert again["order"]["total_cents"] == 700


def test_invalid_options_and_unavailable(client, world, menu):
    _, c = _setup(world, client)
    opts = [o["id"] for o in menu["burger"]["option_groups"][0]["options"]]
    foreign = menu["agua"]["id"]
    assert c.post("/api/v1/public/orders", json={"items": [
        {"product_id": menu["agua"]["id"], "quantity": 1, "option_ids": [opts[0]]}]}).status_code == 422
    assert c.post("/api/v1/public/orders", json={"items": [
        {"product_id": menu["burger"]["id"], "quantity": 1, "option_ids": [opts[0], opts[0]]}]}).status_code == 422
    assert c.post("/api/v1/public/orders", json={"items": [
        {"product_id": menu["burger"]["id"], "quantity": 1, "option_ids": [foreign]}]}).status_code == 422
    world["admin"].patch(f"/api/v1/menu/products/{menu['agua']['id']}", json={"available": False})
    r = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]})
    assert r.status_code == 422 and "indisponível" in r.json()["error"]["message"]
    menu_now = c.get("/api/v1/public/menu").json()
    agua = next(p for p in menu_now[0]["products"] if p["name"] == "Água")
    assert agua["available"] is False


def test_order_forwarded_to_kitchen(client, world, menu):
    """O pedido só precisa ser repassado à cozinha; o cliente vê o horário em que isso aconteceu."""
    tid, c = _setup(world, client)
    o = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]}).json()
    r = world["atendente"].post(f"/api/v1/service-requests/{o['id']}/complete")
    assert r.status_code == 200 and r.json()["status"] == "CONCLUIDA"
    assert world["atendente"].post(f"/api/v1/service-requests/{o['id']}/complete").status_code == 409
    mine = c.get("/api/v1/public/session").json()["requests"][0]
    assert mine["type"] == "NOVO_PEDIDO" and mine["status"] == "CONCLUIDA" and mine["completed_at"]
    assert mine["order"]["items"][0]["product_name"] == "Água"
    assert world["atendente"].get("/api/v1/tables").json()[0]["pending_orders"] == 0
    # Vários pedidos podem estar aguardando ao mesmo tempo.
    for _ in range(2):
        assert c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"],
                                                                "quantity": 1}]}).status_code == 201
    assert world["atendente"].get("/api/v1/tables").json()[0]["pending_orders"] == 2


def test_closed_session_rejects_orders(client, world, menu):
    tid, c = _setup(world, client)
    c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["burger"]["id"], "quantity": 2}]})
    assert close_table(world["caixa"], tid).status_code == 200
    after = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]})
    assert after.status_code == 401


def test_orders_disabled(client, world, menu):
    _, c = _setup(world, client)
    assert world["admin"].patch("/api/v1/admin/establishment", json={"orders_enabled": False}).status_code == 200
    r = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "orders_disabled"


def test_order_idempotent_under_retries(client, world, menu):
    """Repetição da mesma operação (ex.: rede instável) não duplica o pedido."""
    _, c = _setup(world, client)
    body = {"items": [{"product_id": menu["agua"]["id"], "quantity": 3}]}
    h = {"idempotency-key": "pedido-retry-0001"}
    with ThreadPoolExecutor(max_workers=6) as ex:
        rs = list(ex.map(lambda _: c.post("/api/v1/public/orders", json=body, headers=h), range(6)))
    assert all(r.status_code == 201 for r in rs)
    assert len({r.json()["id"] for r in rs}) == 1
    with pg() as cn:
        assert cn.execute("SELECT count(*) FROM orders").fetchone()[0] == 1


def test_order_vs_close_race(client, world, menu):
    """Pedido concorrente ao encerramento: ou entra antes (e fica no histórico) ou é rejeitado."""
    tid, c = _setup(world, client)
    sid = c.get("/api/v1/public/session").json()["session_id"]
    body = {"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]}

    def order():
        return c.post("/api/v1/public/orders", json=body)

    def close():
        return close_table(world["caixa"], tid)

    with ThreadPoolExecutor(max_workers=2) as ex:
        fo, fc = ex.submit(order), ex.submit(close)
        ro, rc = fo.result(), fc.result()
    with pg() as cn:
        n_orders = cn.execute("SELECT count(*) FROM orders WHERE session_id=%s", (sid,)).fetchone()[0]
        status = cn.execute("SELECT status FROM table_sessions WHERE id=%s", (sid,)).fetchone()[0]
    assert rc.status_code == 200 and status == "CLOSED"
    if ro.status_code == 201:
        assert n_orders == 1  # entrou antes do encerramento e ficou registrado no histórico
        detail = world["caixa"].get(f"/api/v1/table-sessions/{sid}").json()
        assert [r["type"] for r in detail["requests"]] == ["NOVO_PEDIDO"]
    else:
        assert ro.status_code == 401 and n_orders == 0


def test_menu_admin_validation(world):
    a = world["admin"]
    cat = a.post("/api/v1/menu/categories", json={"name": "Bebidas"}).json()
    assert a.post("/api/v1/menu/categories", json={"name": "Bebidas"}).status_code == 409
    bad = [
        {"category_id": cat["id"], "name": "", "price_cents": 100},
        {"category_id": cat["id"], "name": "X", "price_cents": -1},
        {"category_id": cat["id"], "name": "X", "price_cents": 100, "image_url": "javascript:alert(1)"},
        {"category_id": "00000000-0000-0000-0000-000000000000", "name": "X", "price_cents": 100},
        {"category_id": cat["id"], "name": "X", "price_cents": 100,
         "option_groups": [{"name": "G", "min_select": 3, "max_select": 1}]},
    ]
    assert [a.post("/api/v1/menu/products", json=b).status_code for b in bad] == [422] * 5
    # Desativar em vez de excluir preserva o histórico.
    p = a.post("/api/v1/menu/products", json={"category_id": cat["id"], "name": "Chá", "price_cents": 600}).json()
    assert a.patch(f"/api/v1/menu/products/{p['id']}", json={"active": False}).json()["active"] is False
