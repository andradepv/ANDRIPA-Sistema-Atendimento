from concurrent.futures import ThreadPoolExecutor

from conftest import Customer, open_table, pg


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
    o = r.json()
    assert o["status"] == "RECEBIDO" and o["total_cents"] == 2 * (2500 + 500) + 500
    assert o["items"][0]["options"][0]["name"] == "Bacon"
    staff = world["atendente"].get("/api/v1/orders?active=true").json()
    assert staff["total"] == 1 and staff["items"][0]["table_number"] == 1
    reqs = world["atendente"].get("/api/v1/service-requests").json()["items"]
    assert reqs[0]["type"] == "NOVO_PEDIDO" and reqs[0]["order_id"] == o["id"]


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
    assert o["total_cents"] == 700
    # Alteração posterior não muda pedido histórico.
    world["admin"].patch(f"/api/v1/menu/products/{menu['agua']['id']}", json={"price_cents": 900})
    again = world["caixa"].get("/api/v1/orders").json()["items"][0]
    assert again["total_cents"] == 700


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


def test_order_status_transitions_and_permissions(client, world, menu):
    _, c = _setup(world, client)
    o = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]}).json()
    att = world["atendente"]
    url = f"/api/v1/orders/{o['id']}/status"
    assert att.post(url, json={"status": "EM_PREPARO"}).json()["status"] == "EM_PREPARO"
    assert att.post(url, json={"status": "CANCELADO", "reason": "x"}).status_code == 403
    assert att.post(url, json={"status": "RECEBIDO"}).status_code == 409
    assert att.post(url, json={"status": "PRONTO", "expected_version": 1}).status_code == 409  # versão velha
    assert att.post(url, json={"status": "PRONTO"}).status_code == 200
    assert att.post(url, json={"status": "ENTREGUE"}).json()["status"] == "ENTREGUE"
    assert att.post(url, json={"status": "EM_PREPARO"}).status_code == 409
    state = c.get("/api/v1/public/session").json()
    assert state["orders"][0]["status"] == "ENTREGUE"
    assert all(r["status"] == "CONCLUIDA" for r in state["requests"] if r["type"] == "NOVO_PEDIDO")
    with pg() as cn:
        hist = cn.execute("SELECT to_status FROM order_status_history WHERE order_id=%s ORDER BY created_at",
                          (o["id"],)).fetchall()
    assert [h[0] for h in hist] == ["RECEBIDO", "EM_PREPARO", "PRONTO", "ENTREGUE"]


def test_close_blocked_by_pending_orders(client, world, menu):
    _, c = _setup(world, client)
    o = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["burger"]["id"], "quantity": 1}]}).json()
    sid = o["session_id"]
    r = world["caixa"].post(f"/api/v1/table-sessions/{sid}/close", json={"payment_method": "PIX"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "pending_orders"
    assert world["caixa"].post(f"/api/v1/table-sessions/{sid}/close",
                               json={"payment_method": "PIX", "pending_orders_policy": "cancel_pending"}).status_code == 422
    r = world["caixa"].post(f"/api/v1/table-sessions/{sid}/close",
                            json={"payment_method": "PIX", "pending_orders_policy": "cancel_pending",
                                  "note": "cliente desistiu"})
    assert r.status_code == 200 and r.json()["total_cents"] == 0
    assert r.json()["orders"][0]["status"] == "CANCELADO"


def test_bill_total_and_closed_session_rejects_orders(client, world, menu):
    tid, c = _setup(world, client)
    o = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["burger"]["id"], "quantity": 2}]}).json()
    world["atendente"].post(f"/api/v1/orders/{o['id']}/status", json={"status": "ENTREGUE"})
    detail = world["caixa"].get(f"/api/v1/table-sessions/{o['session_id']}").json()
    assert detail["subtotal_cents"] == 5000 and detail["pending_orders"] == 0
    r = world["caixa"].post(f"/api/v1/table-sessions/{o['session_id']}/close",
                            json={"payment_method": "CARTAO_CREDITO", "expected_version": detail["version"]})
    assert r.status_code == 200 and r.json()["total_cents"] == 5000
    after = c.post("/api/v1/public/orders", json={"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]})
    assert after.status_code == 401


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
    """Pedido concorrente ao encerramento: ou entra antes (e bloqueia o fechamento) ou é rejeitado."""
    _, c = _setup(world, client)
    sid = c.get("/api/v1/public/session").json()["session_id"]
    body = {"items": [{"product_id": menu["agua"]["id"], "quantity": 1}]}

    def order():
        return c.post("/api/v1/public/orders", json=body)

    def close():
        return world["caixa"].post(f"/api/v1/table-sessions/{sid}/close", json={"payment_method": "PIX"})

    with ThreadPoolExecutor(max_workers=2) as ex:
        fo, fc = ex.submit(order), ex.submit(close)
        ro, rc = fo.result(), fc.result()
    with pg() as cn:
        n_orders = cn.execute("SELECT count(*) FROM orders WHERE session_id=%s", (sid,)).fetchone()[0]
        status = cn.execute("SELECT status FROM table_sessions WHERE id=%s", (sid,)).fetchone()[0]
    if ro.status_code == 201:
        assert rc.status_code == 409 and status == "OPEN" and n_orders == 1  # nenhum pedido perdido
    else:
        assert ro.status_code == 401 and rc.status_code == 200 and n_orders == 0


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
