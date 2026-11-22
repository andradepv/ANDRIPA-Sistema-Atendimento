"""Provisionamento de etiquetas NFC (criar mesa + gravar) e plantas do salão (templates)."""
from concurrent.futures import ThreadPoolExecutor

from conftest import PASSWORD, Actor, make_est, make_table, open_table, pg

UID = "04:A2:3B:1C:5D:6E:80"


def provision(admin: Actor, number: int = 7, secret: str = "1111", name: str | None = None):
    return admin.post("/api/v1/admin/tables/provision", json={"number": number, "name": name, "confirm_secret": secret})


def written(admin: Actor, tag: dict, uid: str = UID, url: str | None = None):
    admin.post(f"/api/v1/admin/tags/{tag['id']}/writing")
    return admin.post(f"/api/v1/admin/tags/{tag['id']}/written", json={"uid": uid, "read_url": url or tag["url"]})


def events(type_: str) -> list[dict]:
    with pg() as c:
        return [r[0] for r in c.execute("SELECT payload FROM outbox_events WHERE type = %s ORDER BY id", (type_,))]


# ----------------------------------------------------------------------------- permissões
def test_only_admin_provisions_tags_and_manages_layouts(world):
    tid = world["tables"][0][0]
    for who, secret in (("atendente", "3333"), ("caixa", "2222")):
        a: Actor = world[who]
        assert provision(a, secret=secret).status_code == 403
        assert a.post(f"/api/v1/admin/tables/{tid}/tag", json={"confirm_secret": secret}).status_code == 403
        assert a.get("/api/v1/admin/tags").status_code == 403
        assert a.get("/api/v1/admin/layouts").status_code == 403
        assert a.post("/api/v1/admin/layouts", json={"name": "Evento"}).status_code == 403
    # qualquer funcionário enxerga a planta ativa (o Salão depende dela)...
    assert world["atendente"].get("/api/v1/layouts/active").status_code == 200
    # ...mas não a altera.
    lay = world["admin"].get("/api/v1/layouts/active").json()
    r = world["atendente"].put(f"/api/v1/admin/layouts/{lay['id']}/items", json={"version": lay["version"], "items": []})
    assert r.status_code == 403
    assert world["atendente"].post(f"/api/v1/admin/layouts/{lay['id']}/activate").status_code == 403


# ----------------------------------------------------------------------------- provisionamento
def test_provision_creates_table_qr_tag_and_position(world):
    admin: Actor = world["admin"]
    r = provision(admin, 7, name="Varanda")
    assert r.status_code == 201, r.text
    body = r.json()
    t, tag = body["table"], body["tag"]
    assert t["number"] == 7 and t["name"] == "Varanda" and t["status"] == "LIVRE"
    assert tag["status"] == "PENDENTE" and tag["table_number"] == 7
    # A URL a gravar é a da mesa: nenhuma digitação humana.
    assert tag["url"] == t["public_url"] and tag["url"].startswith("https://app.test/m/")
    qr = admin.get(body["qr_svg_url"])
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml")
    # Entra na planta ativa sem ninguém posicionar.
    lay = admin.get("/api/v1/layouts/active").json()
    assert t["id"] in {i["table_id"] for i in lay["items"]}
    # A mesa já aparece com a situação da etiqueta.
    listed = {x["number"]: x for x in admin.get("/api/v1/tables").json()}
    assert listed[7]["tag"]["status"] == "PENDENTE"
    # Tempo real + auditoria.
    assert any(e["data"]["tag"]["table_number"] == 7 and e["data"]["tag"]["status"] == "PENDENTE"
               for e in events("tag.updated"))
    actions = [a["action"] for a in admin.get("/api/v1/admin/audit-logs?limit=200").json()["items"]]
    assert "tag.provision" in actions and "table.create" in actions
    # O endereço funciona: a mesa livre responde (bloqueada até abrirem).
    code = t["public_url"].rsplit("/", 1)[1]
    assert world["client"].get(f"/api/v1/public/tables/{code}").status_code == 200


def test_provision_requires_admin_credential_and_is_atomic(world):
    admin: Actor = world["admin"]
    r = provision(admin, 8, secret="0000")
    assert r.status_code == 403 and r.json()["error"]["code"] == "confirmation_failed"
    with pg() as c:
        assert c.execute("SELECT count(*) FROM tables WHERE number = 8").fetchone()[0] == 0
    assert provision(admin, 9, secret=PASSWORD).status_code == 201  # a senha também vale
    # Número repetido: nada é criado pela metade.
    r = provision(admin, 1)
    assert r.status_code == 409
    with pg() as c:
        assert c.execute("SELECT count(*) FROM table_tags").fetchone()[0] == 1


def test_tag_lifecycle_write_verify_and_lock(world):
    admin: Actor = world["admin"]
    tag = provision(admin).json()["tag"]
    r = admin.post(f"/api/v1/admin/tags/{tag['id']}/writing")
    assert r.status_code == 200 and r.json()["status"] == "GRAVANDO"
    r = admin.post(f"/api/v1/admin/tags/{tag['id']}/written", json={"uid": UID.lower(), "read_url": tag["url"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "GRAVADA" and r.json()["uid"] == "04A23B1C5D6E80"
    # Travar exige antes a senha do administrador.
    assert admin.post(f"/api/v1/admin/tags/{tag['id']}/locked").json()["error"]["code"] == "lock_not_authorized"
    bad = admin.post(f"/api/v1/admin/tags/{tag['id']}/authorize-lock", json={"confirm_secret": "9999"})
    assert bad.status_code == 403
    assert admin.post(f"/api/v1/admin/tags/{tag['id']}/authorize-lock", json={"confirm_secret": "1111"}).status_code == 200
    r = admin.post(f"/api/v1/admin/tags/{tag['id']}/locked")
    assert r.status_code == 200 and r.json()["status"] == "TRAVADA" and r.json()["locked_at"]
    # Nada mais muda numa etiqueta travada.
    assert admin.post(f"/api/v1/admin/tags/{tag['id']}/writing").status_code == 409
    assert admin.post(f"/api/v1/admin/tags/{tag['id']}/failed", json={"reason": "x"}).status_code == 409
    statuses = [e["data"]["tag"]["status"] for e in events("tag.updated")]
    assert statuses == ["PENDENTE", "GRAVANDO", "GRAVADA", "GRAVADA", "TRAVADA"]  # 2º GRAVADA = lock autorizado
    actions = [a["action"] for a in admin.get("/api/v1/admin/audit-logs?limit=200").json()["items"]]
    assert {"tag.written", "tag.lock_authorized", "tag.locked"} <= set(actions)


def test_wrong_url_read_back_marks_failure_and_is_persisted(world):
    admin: Actor = world["admin"]
    tag = provision(admin).json()["tag"]
    r = written(admin, tag, url="https://outro-site.exemplo/m/abc")
    assert r.status_code == 422 and r.json()["error"]["code"] == "tag_url_mismatch"
    listed = {x["number"]: x for x in admin.get("/api/v1/tables").json()}
    assert listed[7]["tag"]["status"] == "FALHA" and "diferente" in listed[7]["tag"]["error"]
    # Uma falha não pode ser "aprovada" depois.
    assert admin.post(f"/api/v1/admin/tags/{tag['id']}/written",
                      json={"uid": UID, "read_url": tag["url"]}).status_code == 409
    # Nova tentativa: substitui a falha, mantém o mesmo endereço.
    again = admin.post(f"/api/v1/admin/tables/{listed[7]['id']}/tag", json={"confirm_secret": "1111"})
    assert again.status_code == 201 and again.json()["status"] == "PENDENTE" and again.json()["url"] == tag["url"]


def test_same_physical_tag_cannot_serve_two_tables(world):
    admin: Actor = world["admin"]
    assert written(admin, provision(admin, 7).json()["tag"]).status_code == 200
    second = provision(admin, 8).json()["tag"]
    r = written(admin, second)  # mesmo chip
    assert r.status_code == 409 and r.json()["error"]["code"] == "tag_uid_in_use"
    assert "mesa 7" in r.json()["error"]["message"]
    assert written(admin, admin.post(f"/api/v1/admin/tables/{provision(admin, 9).json()['table']['id']}/tag",
                                     json={"confirm_secret": "1111"}).json(), uid="04:11:22:33:44:55:66").status_code == 200


def test_replace_tag_rotates_address_and_needs_free_table(world):
    admin: Actor = world["admin"]
    body = provision(admin).json()
    tag, tid = body["tag"], body["table"]["id"]
    assert written(admin, tag).status_code == 200
    # Sem confirmar a substituição, não sobrescreve uma etiqueta gravada.
    r = admin.post(f"/api/v1/admin/tables/{tid}/tag", json={"confirm_secret": "1111"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "tag_exists"
    # Mesa ocupada: não troca o endereço debaixo dos clientes.
    open_table(world["atendente"], tid)
    r = admin.post(f"/api/v1/admin/tables/{tid}/tag", json={"confirm_secret": "1111", "replace": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "table_in_use"
    # Mesa livre: substitui e o endereço antigo (etiqueta/QR perdidos) morre.
    other = provision(admin, 12).json()
    r = admin.post(f"/api/v1/admin/tables/{other['table']['id']}/tag", json={"confirm_secret": "1111", "replace": True})
    assert r.status_code == 201  # etiqueta PENDENTE anterior é substituída sem rotacionar
    assert r.json()["url"] == other["tag"]["url"]
    old_code = other["tag"]["url"].rsplit("/", 1)[1]
    assert written(admin, r.json(), uid="04:AA:BB:CC:DD:EE:FF").status_code == 200
    r2 = admin.post(f"/api/v1/admin/tables/{other['table']['id']}/tag", json={"confirm_secret": "1111", "replace": True})
    assert r2.status_code == 201 and r2.json()["url"] != other["tag"]["url"]
    assert world["client"].get(f"/api/v1/public/tables/{old_code}").status_code == 404
    with pg() as c:
        st = [x[0] for x in c.execute("SELECT status FROM table_tags WHERE table_id = %s ORDER BY created_at",
                                      (other["table"]["id"],))]
    assert st == ["SUBSTITUIDA", "SUBSTITUIDA", "PENDENTE"]


def test_lock_authorization_expires(world):
    admin: Actor = world["admin"]
    tag = provision(admin).json()["tag"]
    assert written(admin, tag).status_code == 200
    assert admin.post(f"/api/v1/admin/tags/{tag['id']}/authorize-lock", json={"confirm_secret": "1111"}).status_code == 200
    with pg() as c:
        c.execute("UPDATE table_tags SET lock_authorized_at = now() - interval '5 minutes' WHERE id = %s", (tag["id"],))
    r = admin.post(f"/api/v1/admin/tags/{tag['id']}/locked")
    assert r.status_code == 409 and r.json()["error"]["code"] == "lock_not_authorized"


def test_tags_of_another_establishment_are_invisible(world):
    admin: Actor = world["admin"]
    tag = provision(admin).json()["tag"]
    est2 = make_est("Outro bar")
    from conftest import make_user
    other = Actor(world["client"], make_user(est2, "ADMIN", "admin2@teste.local", pin="4444"))
    assert other.post(f"/api/v1/admin/tags/{tag['id']}/writing").status_code == 404
    assert other.get("/api/v1/admin/tags").json() == []


# ----------------------------------------------------------------------------- plantas
def test_default_layout_is_created_once_even_under_concurrency(world):
    admin: Actor = world["admin"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda _: admin.get("/api/v1/layouts/active"), range(6)))
    assert all(r.status_code == 200 for r in res)
    assert len({r.json()["id"] for r in res}) == 1
    lay = res[0].json()
    assert lay["name"] == "Padrão" and lay["is_active"] and len(lay["items"]) == 3  # as 3 mesas de teste
    cells = {(i["x"], i["y"]) for i in lay["items"]}
    assert len(cells) == 3


def test_rearrange_tables_and_stale_version(world):
    admin: Actor = world["admin"]
    lay = admin.get("/api/v1/layouts/active").json()
    ids = [i["table_id"] for i in lay["items"]]
    items = [{"table_id": ids[0], "x": 10, "y": 5}, {"table_id": ids[1], "x": 0, "y": 0}]  # a 3ª fica sem posição
    r = admin.put(f"/api/v1/admin/layouts/{lay['id']}/items", json={"version": lay["version"], "items": items})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["version"] == lay["version"] + 1 and {(i["x"], i["y"]) for i in new["items"]} == {(10, 5), (0, 0)}
    # Quem tinha a versão antiga não sobrescreve a mudança dos outros.
    r = admin.put(f"/api/v1/admin/layouts/{lay['id']}/items", json={"version": lay["version"], "items": items})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_version"
    # Todos os painéis recebem a planta nova.
    assert events("layout.updated")[-1]["data"]["layout"]["version"] == new["version"]
    assert world["atendente"].get("/api/v1/layouts/active").json()["version"] == new["version"]


def test_layout_validation(world):
    admin: Actor = world["admin"]
    lay = admin.get("/api/v1/layouts/active").json()
    ids = [i["table_id"] for i in lay["items"]]
    url = f"/api/v1/admin/layouts/{lay['id']}/items"
    v = lay["version"]
    same_cell = [{"table_id": ids[0], "x": 1, "y": 1}, {"table_id": ids[1], "x": 1, "y": 1}]
    assert admin.put(url, json={"version": v, "items": same_cell}).json()["error"]["code"] == "cell_taken"
    twice = [{"table_id": ids[0], "x": 1, "y": 1}, {"table_id": ids[0], "x": 2, "y": 1}]
    assert admin.put(url, json={"version": v, "items": twice}).json()["error"]["code"] == "duplicate_table"
    assert admin.put(url, json={"version": v, "items": [{"table_id": ids[0], "x": 24, "y": 0}]}).status_code == 422
    assert admin.put(url, json={"version": v, "items": [{"table_id": ids[0], "x": 0, "y": 16}]}).status_code == 422
    est2 = make_est("Outro bar")
    foreign, _ = make_table(est2, 1)
    r = admin.put(url, json={"version": v, "items": [{"table_id": foreign, "x": 0, "y": 0}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_table"
    # Nada disso alterou a planta.
    assert admin.get("/api/v1/layouts/active").json()["version"] == v


def test_templates_copy_activate_and_delete(world):
    admin: Actor = world["admin"]
    base = admin.get("/api/v1/layouts/active").json()
    r = admin.post("/api/v1/admin/layouts", json={"name": "Evento", "copy_from": base["id"]})
    assert r.status_code == 201
    evt = r.json()
    assert not evt["is_active"] and len(evt["items"]) == len(base["items"])
    assert admin.post("/api/v1/admin/layouts", json={"name": "Evento"}).json()["error"]["code"] == "layout_name_taken"
    # Rearranja só o template (o salão ativo não muda).
    moved = [{**i, "x": 20 - n, "y": 14} for n, i in enumerate(evt["items"])]
    assert admin.put(f"/api/v1/admin/layouts/{evt['id']}/items", json={"version": evt["version"], "items": moved}).status_code == 200
    assert {(i["x"], i["y"]) for i in admin.get("/api/v1/layouts/active").json()["items"]} == {(i["x"], i["y"]) for i in base["items"]}
    # Não dá para excluir a planta ativa.
    assert admin.delete(f"/api/v1/admin/layouts/{base['id']}").json()["error"]["code"] == "layout_active"
    # Ativar troca o salão para todos, em tempo real.
    r = admin.post(f"/api/v1/admin/layouts/{evt['id']}/activate")
    assert r.status_code == 200 and r.json()["is_active"]
    seen = world["atendente"].get("/api/v1/layouts/active").json()
    assert seen["id"] == evt["id"] and {(i["x"], i["y"]) for i in seen["items"]} == {(20 - n, 14) for n in range(3)}
    assert events("layout.updated")[-1]["data"]["layout"]["id"] == evt["id"]
    listed = {x["name"]: x["is_active"] for x in admin.get("/api/v1/admin/layouts").json()}
    assert listed == {"Padrão": False, "Evento": True}
    assert admin.delete(f"/api/v1/admin/layouts/{base['id']}").status_code == 204


def test_concurrent_activations_leave_one_active(world):
    admin: Actor = world["admin"]
    base = admin.get("/api/v1/layouts/active").json()
    ids = [admin.post("/api/v1/admin/layouts", json={"name": f"T{n}"}).json()["id"] for n in range(4)] + [base["id"]]
    with ThreadPoolExecutor(max_workers=5) as ex:
        res = list(ex.map(lambda i: admin.post(f"/api/v1/admin/layouts/{i}/activate"), ids))
    assert all(r.status_code == 200 for r in res), [r.text for r in res]
    with pg() as c:
        assert c.execute("SELECT count(*) FROM floor_layouts WHERE is_active").fetchone()[0] == 1


def test_new_table_lands_on_free_cell_of_active_layout(world):
    admin: Actor = world["admin"]
    before = admin.get("/api/v1/layouts/active").json()
    r = admin.post("/api/v1/tables", json={"number": 20})
    assert r.status_code == 201
    after = admin.get("/api/v1/layouts/active").json()
    assert len(after["items"]) == len(before["items"]) + 1
    assert len({(i["x"], i["y"]) for i in after["items"]}) == len(after["items"])
    assert r.json()["id"] in {i["table_id"] for i in after["items"]}
