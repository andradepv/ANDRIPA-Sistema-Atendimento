import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/http";
import type { AuditEntry, Category, Establishment, Notice, Page, Product, Role, Table, User } from "../../api/types";
import { Dialog, Empty, Field, useToast } from "../../components/ui";
import { dateTime, money, tableStatusLabel } from "../../lib/format";
import { useStaff } from "../staff/StaffData";

// ===================================== Cardápio =====================================

interface GroupDraft {
  id?: string;
  name: string;
  min_select: number;
  max_select: number;
  options: { id?: string; name: string; price_cents: number; active: boolean }[];
}
interface ProductDraft {
  id?: string;
  category_id: string;
  name: string;
  description: string;
  price: string;
  image_url: string;
  available: boolean;
  active: boolean;
  position: number;
  option_groups: GroupDraft[];
}

const toCents = (v: string) => Math.round(Number(v.replace(",", ".")) * 100);
const fromCents = (c: number) => (c / 100).toFixed(2).replace(".", ",");

export function AdminMenu() {
  const toast = useToast();
  const { menuVersion } = useStaff();
  const [cats, setCats] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [newCat, setNewCat] = useState("");
  const [draft, setDraft] = useState<ProductDraft | null>(null);

  const load = useCallback(async () => {
    const [c, p] = await Promise.all([api<Category[]>("/menu/categories"), api<Product[]>("/menu/products")]);
    setCats(c);
    setProducts(p);
  }, []);
  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, toast, menuVersion]);

  const saveProduct = async () => {
    if (!draft) return;
    const body = {
      category_id: draft.category_id,
      name: draft.name,
      description: draft.description || null,
      price_cents: toCents(draft.price),
      image_url: draft.image_url || null,
      available: draft.available,
      active: draft.active,
      position: draft.position,
      option_groups: draft.option_groups.map((g) => ({
        ...(g.id ? { id: g.id } : {}),
        name: g.name,
        min_select: g.min_select,
        max_select: g.max_select,
        options: g.options.map((o) => ({ ...(o.id ? { id: o.id } : {}), name: o.name, price_cents: o.price_cents, active: o.active })),
      })),
    };
    try {
      if (draft.id) await api(`/menu/products/${draft.id}`, { method: "PATCH", body });
      else await api("/menu/products", { body });
      toast("Produto salvo.", "ok");
      setDraft(null);
      await load();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  const quick = async (p: Product, patch: Partial<Product>) => {
    try {
      await api(`/menu/products/${p.id}`, { method: "PATCH", body: patch });
      await load();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  return (
    <section className="stack">
      <h1 className="s-h1">Cardápio</h1>
      <form
        className="inline"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/menu/categories", { body: { name: newCat, position: cats.length + 1 } });
            setNewCat("");
            await load();
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <Field label="Nova categoria">
          <input value={newCat} onChange={(e) => setNewCat(e.target.value)} maxLength={80} required />
        </Field>
        <button className="btn">Criar categoria</button>
      </form>
      {cats.length === 0 && <Empty>Crie a primeira categoria (por exemplo, Bebidas) para começar a cadastrar produtos.</Empty>}
      {cats.map((c) => (
        <div key={c.id} className="admin-cat">
          <div className="admin-cat__head">
            <h2 className={c.active ? "s-h2" : "s-h2 muted"}>
              {c.name} {!c.active && "(oculta)"}
            </h2>
            <button className="btn btn--small btn--ghost" onClick={() => api(`/menu/categories/${c.id}`, { method: "PATCH", body: { active: !c.active } }).then(load)}>
              {c.active ? "Ocultar categoria" : "Mostrar categoria"}
            </button>
            <button
              className="btn btn--small"
              onClick={() =>
                setDraft({ category_id: c.id, name: "", description: "", price: "", image_url: "", available: true, active: true, position: 0, option_groups: [] })
              }
            >
              Novo produto
            </button>
          </div>
          <table className="data-table">
            <tbody>
              {products
                .filter((p) => p.category_id === c.id)
                .map((p) => (
                  <tr key={p.id} className={p.active ? "" : "is-cancelled"}>
                    <td>
                      <strong>{p.name}</strong>
                      {p.option_groups.length > 0 && <span className="muted small"> · {p.option_groups.length} grupo(s) de adicionais</span>}
                    </td>
                    <td className="num">{money(p.price_cents)}</td>
                    <td>
                      <label className="opt">
                        <input type="checkbox" checked={p.available} onChange={() => void quick(p, { available: !p.available })} />
                        <span>Disponível</span>
                      </label>
                    </td>
                    <td>
                      <button
                        className="btn btn--small btn--ghost"
                        onClick={() =>
                          setDraft({
                            id: p.id,
                            category_id: p.category_id,
                            name: p.name,
                            description: p.description ?? "",
                            price: fromCents(p.price_cents),
                            image_url: p.image_url ?? "",
                            available: p.available,
                            active: p.active,
                            position: p.position,
                            option_groups: p.option_groups.map((g) => ({ ...g, options: g.options.map((o) => ({ ...o })) })),
                          })
                        }
                      >
                        Editar
                      </button>
                      <button className="btn btn--small btn--ghost" onClick={() => void quick(p, { active: !p.active })}>
                        {p.active ? "Desativar" : "Reativar"}
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ))}

      <Dialog open={!!draft} title={draft?.id ? "Editar produto" : "Novo produto"} onClose={() => setDraft(null)} wide>
        {draft && (
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault();
              void saveProduct();
            }}
          >
            <div className="grid2">
              <Field label="Nome">
                <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} required maxLength={120} />
              </Field>
              <Field label="Preço (R$)">
                <input inputMode="decimal" value={draft.price} pattern="\d+([,.]\d{1,2})?" onChange={(e) => setDraft({ ...draft, price: e.target.value })} required />
              </Field>
              <Field label="Categoria">
                <select value={draft.category_id} onChange={(e) => setDraft({ ...draft, category_id: e.target.value })}>
                  {cats.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Imagem (URL https, opcional)">
                <input type="url" pattern="https://.*" value={draft.image_url} onChange={(e) => setDraft({ ...draft, image_url: e.target.value })} />
              </Field>
            </div>
            <Field label="Descrição">
              <textarea rows={2} value={draft.description} maxLength={1000} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            </Field>
            <h3 className="s-h2">Adicionais</h3>
            {draft.option_groups.map((g, gi) => (
              <fieldset key={gi} className="opt-editor">
                <legend>Grupo {gi + 1}</legend>
                <div className="grid3">
                  <Field label="Nome do grupo">
                    <input value={g.name} required onChange={(e) => setDraft(updGroup(draft, gi, { name: e.target.value }))} />
                  </Field>
                  <Field label="Mínimo">
                    <input type="number" min={0} max={20} value={g.min_select} onChange={(e) => setDraft(updGroup(draft, gi, { min_select: Number(e.target.value) }))} />
                  </Field>
                  <Field label="Máximo">
                    <input type="number" min={1} max={20} value={g.max_select} onChange={(e) => setDraft(updGroup(draft, gi, { max_select: Number(e.target.value) }))} />
                  </Field>
                </div>
                {g.options.map((o, oi) => (
                  <div key={oi} className="inline">
                    <input aria-label="Nome do adicional" value={o.name} required onChange={(e) => setDraft(updOpt(draft, gi, oi, { name: e.target.value }))} />
                    <input
                      aria-label="Preço do adicional (R$)"
                      inputMode="decimal"
                      value={fromCents(o.price_cents)}
                      onChange={(e) => setDraft(updOpt(draft, gi, oi, { price_cents: toCents(e.target.value) || 0 }))}
                    />
                    <label className="opt">
                      <input type="checkbox" checked={o.active} onChange={() => setDraft(updOpt(draft, gi, oi, { active: !o.active }))} />
                      <span>Ativo</span>
                    </label>
                  </div>
                ))}
                <div className="inline">
                  <button type="button" className="btn btn--small" onClick={() => setDraft(updGroup(draft, gi, { options: [...g.options, { name: "", price_cents: 0, active: true }] }))}>
                    Adicionar opção
                  </button>
                  <button type="button" className="btn btn--small btn--ghost" onClick={() => setDraft({ ...draft, option_groups: draft.option_groups.filter((_, i) => i !== gi) })}>
                    Remover grupo
                  </button>
                </div>
              </fieldset>
            ))}
            <button
              type="button"
              className="btn btn--small"
              onClick={() => setDraft({ ...draft, option_groups: [...draft.option_groups, { name: "", min_select: 0, max_select: 1, options: [] }] })}
            >
              Novo grupo de adicionais
            </button>
            <div className="dialog__actions">
              <button type="button" className="btn btn--ghost" onClick={() => setDraft(null)}>
                Cancelar
              </button>
              <button className="btn btn--primary">Salvar produto</button>
            </div>
          </form>
        )}
      </Dialog>
    </section>
  );
}

function updGroup(d: ProductDraft, gi: number, patch: Partial<GroupDraft>): ProductDraft {
  return { ...d, option_groups: d.option_groups.map((g, i) => (i === gi ? { ...g, ...patch } : g)) };
}
function updOpt(d: ProductDraft, gi: number, oi: number, patch: Partial<GroupDraft["options"][number]>): ProductDraft {
  return updGroup(d, gi, { options: d.option_groups[gi]!.options.map((o, i) => (i === oi ? { ...o, ...patch } : o)) });
}

// ===================================== Mesas =====================================

export function AdminTables() {
  const toast = useToast();
  const { tables } = useStaff();
  const [all, setAll] = useState<Table[]>([]);
  const [number, setNumber] = useState("");
  const [name, setName] = useState("");
  const [qr, setQr] = useState<Table | null>(null);

  const load = useCallback(() => api<Table[]>("/tables?include_inactive=true").then(setAll), []);
  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, toast, tables]);

  const patch = async (t: Table, body: Record<string, unknown>) => {
    try {
      await api(`/tables/${t.id}`, { method: "PATCH", body });
      await load();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  return (
    <section className="stack">
      <h1 className="s-h1">Mesas, QR Codes e etiquetas NFC</h1>
      <form
        className="inline"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/tables", { body: { number: Number(number), name: name || null } });
            setNumber("");
            setName("");
            await load();
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <Field label="Número">
          <input inputMode="numeric" value={number} onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} required />
        </Field>
        <Field label="Nome (opcional)">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Ex.: Varanda" />
        </Field>
        <button className="btn">Cadastrar mesa</button>
      </form>
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Mesa</th>
            <th scope="col">Situação</th>
            <th scope="col">Endereço da mesa (QR e NFC)</th>
            <th scope="col">Ações</th>
          </tr>
        </thead>
        <tbody>
          {all.map((t) => (
            <tr key={t.id} className={t.active ? "" : "is-cancelled"}>
              <td>
                <strong>{t.number}</strong> {t.name}
              </td>
              <td>{t.active ? tableStatusLabel[t.status] : "Desativada"}</td>
              <td>
                <code className="url">{t.public_url}</code>
              </td>
              <td className="inline">
                <button className="btn btn--small" onClick={() => setQr(t)}>
                  QR Code
                </button>
                <button
                  className="btn btn--small btn--ghost"
                  onClick={() => navigator.clipboard.writeText(t.public_url).then(() => toast("Endereço copiado. Grave-o na etiqueta NFC.", "ok"))}
                >
                  Copiar para NFC
                </button>
                <button
                  className="btn btn--small btn--ghost"
                  disabled={t.status !== "LIVRE"}
                  onClick={() => {
                    if (confirm(`Gerar novo endereço para a mesa ${t.number}? O QR Code e a etiqueta antigos deixam de funcionar.`))
                      void api(`/tables/${t.id}/rotate-code`, { body: {} }).then(load).catch((e) => toast(errorMessage(e), "error"));
                  }}
                >
                  Gerar novo endereço
                </button>
                <button className="btn btn--small btn--ghost" disabled={t.status !== "LIVRE"} onClick={() => void patch(t, { active: !t.active })}>
                  {t.active ? "Desativar" : "Reativar"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Dialog open={!!qr} title={qr ? `QR Code da mesa ${qr.number}` : ""} onClose={() => setQr(null)}>
        {qr && (
          <div className="qr-print">
            <img src={`/api/v1/tables/${qr.id}/qr.svg`} alt={`QR Code da mesa ${qr.number}`} width={280} height={280} />
            <p className="qr-print__label">Mesa {qr.number}</p>
            <p className="muted small">Aponte a câmera ou aproxime o celular da etiqueta</p>
            <button className="btn btn--primary no-print" onClick={() => window.print()}>
              Imprimir
            </button>
          </div>
        )}
      </Dialog>
    </section>
  );
}

// ===================================== Equipe =====================================

const ROLES: [Role, string][] = [
  ["ATENDENTE", "Atendente"],
  ["CAIXA", "Caixa"],
  ["ADMIN", "Administrador"],
];

export function AdminUsers() {
  const toast = useToast();
  const { me } = useStaff();
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState({ name: "", username: "", role: "ATENDENTE" as Role, pin: "" });
  const [reset, setReset] = useState<User | null>(null);
  const [newPin, setNewPin] = useState("");
  const digits = (v: string) => v.replace(/\D/g, "");
  const load = useCallback(() => api<User[]>("/admin/users").then(setUsers), []);
  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, toast]);

  const patch = async (u: User, body: Record<string, unknown>) => {
    try {
      await api(`/admin/users/${u.id}`, { method: "PATCH", body });
      toast("Pessoa atualizada.", "ok");
      await load();
      return true;
    } catch (e) {
      toast(errorMessage(e), "error");
      return false;
    }
  };

  return (
    <section className="stack">
      <h1 className="s-h1">Equipe</h1>
      <p className="muted">
        Cada pessoa entra no painel com <strong>usuário e PIN</strong>. O atendente só precisa do PIN: na página da mesa, toca em “Liberar mesa” e
        digita o PIN.
      </p>
      <form
        className="grid3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/admin/users", { body: form });
            setForm({ name: "", username: "", role: "ATENDENTE", pin: "" });
            toast("Pessoa adicionada à equipe.", "ok");
            await load();
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <Field label="Nome">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        </Field>
        <Field label="Usuário" hint="Letras minúsculas e números, ex.: joana">
          <input
            value={form.username}
            autoCapitalize="none"
            pattern="[a-z0-9._\-]{3,32}"
            onChange={(e) => setForm({ ...form, username: e.target.value.toLowerCase().replace(/\s/g, "") })}
            required
          />
        </Field>
        <Field label="Papel">
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {ROLES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label="PIN" hint="4 a 8 números, diferente do PIN das outras pessoas">
          <input inputMode="numeric" pattern="\d{4,8}" value={form.pin} onChange={(e) => setForm({ ...form, pin: digits(e.target.value) })} required />
        </Field>
        <div className="field field--end">
          <button className="btn btn--primary">Adicionar à equipe</button>
        </div>
      </form>
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Nome</th>
            <th scope="col">Usuário</th>
            <th scope="col">Papel</th>
            <th scope="col">Situação</th>
            <th scope="col">Ações</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={u.active ? "" : "is-cancelled"}>
              <td>{u.name}</td>
              <td>
                <code>{u.username}</code>
              </td>
              <td>
                <select aria-label={`Papel de ${u.name}`} value={u.role} disabled={u.id === me.user.id} onChange={(e) => void patch(u, { role: e.target.value })}>
                  {ROLES.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </td>
              <td>{u.active ? "Ativo" : "Desativado"}</td>
              <td className="inline">
                <button className="btn btn--small btn--ghost" disabled={u.id === me.user.id} onClick={() => void patch(u, { active: !u.active })}>
                  {u.active ? "Desativar" : "Reativar"}
                </button>
                <button className="btn btn--small btn--ghost" onClick={() => setReset(u)}>
                  Trocar PIN
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Dialog open={!!reset} title={`Novo PIN para ${reset?.name ?? ""}`} onClose={() => setReset(null)}>
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault();
            if (reset && (await patch(reset, { pin: newPin }))) {
              setNewPin("");
              setReset(null);
            }
          }}
        >
          <Field label="Novo PIN" hint="A pessoa será desconectada do painel em todos os aparelhos.">
            <input inputMode="numeric" pattern="\d{4,8}" value={newPin} onChange={(e) => setNewPin(digits(e.target.value))} required />
          </Field>
          <button className="btn btn--primary">Salvar PIN</button>
        </form>
      </Dialog>
    </section>
  );
}

// ===================================== Notificações (avisos aos clientes) =====================================

export function AdminNotices() {
  const toast = useToast();
  const { me } = useStaff();
  const [notices, setNotices] = useState<Notice[] | null>(null);
  const [push, setPush] = useState<{ enabled: boolean; subscribers: number } | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [sendPush, setSendPush] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [n, p] = await Promise.all([api<Notice[]>("/admin/notices"), api<{ enabled: boolean; subscribers: number }>("/admin/push/stats")]);
    setNotices(n);
    setPush(p);
  }, []);
  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, toast]);

  const act = async (path: string, method: string, body?: unknown) => {
    try {
      await api(path, { method, body });
      await load();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  return (
    <section className="stack s-narrow">
      <h1 className="s-h1">Notificações aos clientes</h1>
      <p className="muted">
        Avise sobre promoções, eventos ou novidades. O aviso aparece na aba <strong>Novidades</strong> do celular de quem está nas mesas, com um botão
        para chamar um atendente — é assim que o cliente sabe mais ou aproveita.
      </p>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            const r = await api<{ push: { sent: number; targeted: number } | null }>("/admin/notices", {
              body: { title, message: message || null, send_push: sendPush },
            });
            toast(r.push ? `Aviso publicado e enviado para ${r.push.sent} de ${r.push.targeted} celular(es).` : "Aviso publicado.", "ok");
            setTitle("");
            setMessage("");
            setSendPush(false);
            await load();
          } catch (err) {
            toast(errorMessage(err), "error");
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Título" hint="Ex.: Happy hour até as 20h">
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} required />
        </Field>
        <Field label="Mensagem (opcional)">
          <textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500} />
        </Field>
        {push?.enabled && (
          <label className="opt">
            <input type="checkbox" checked={sendPush} onChange={(e) => setSendPush(e.target.checked)} />
            <span>Também enviar como notificação no celular ({push.subscribers} cliente(s) aceitaram receber)</span>
          </label>
        )}
        <button className="btn btn--primary" disabled={busy}>
          {busy ? "Publicando…" : "Publicar aviso"}
        </button>
      </form>
      {notices === null ? (
        <p className="empty">Carregando…</p>
      ) : notices.length === 0 ? (
        <Empty>Nenhum aviso publicado.</Empty>
      ) : (
        <ul className="promos">
          {notices.map((n) => (
            <li key={n.id} className={`promo${n.active ? "" : " is-cancelled"}`}>
              <strong className="promo__title">{n.title}</strong>
              {n.message && <p>{n.message}</p>}
              <p className="muted small">
                {dateTime(n.created_at, me.establishment.timezone)} · {n.active ? "Visível para os clientes" : "Oculto"}
              </p>
              <div className="inline">
                <button className="btn btn--small btn--ghost" onClick={() => void act(`/admin/notices/${n.id}`, "PATCH", { active: !n.active })}>
                  {n.active ? "Ocultar" : "Mostrar"}
                </button>
                <button
                  className="btn btn--small btn--ghost"
                  onClick={() => {
                    if (confirm(`Excluir o aviso “${n.title}”?`)) void act(`/admin/notices/${n.id}`, "DELETE");
                  }}
                >
                  Excluir
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ===================================== Auditoria =====================================

export function AdminAudit() {
  const toast = useToast();
  const { me } = useStaff();
  const [page, setPage] = useState<Page<AuditEntry> | null>(null);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    const q = new URLSearchParams({ limit: "50", offset: String(offset) });
    if (filter) q.set("action", filter);
    api<Page<AuditEntry>>(`/admin/audit-logs?${q}`).then(setPage).catch((e) => toast(errorMessage(e), "error"));
  }, [offset, filter, toast]);
  return (
    <section className="stack">
      <h1 className="s-h1">Auditoria</h1>
      <Field label="Filtrar por ação">
        <select value={filter} onChange={(e) => { setFilter(e.target.value); setOffset(0); }}>
          <option value="">Todas</option>
          <option value="auth">Login e acesso</option>
          <option value="table">Mesas</option>
          <option value="session">Contas finalizadas</option>
          <option value="order">Pedidos</option>
          <option value="request">Chamados</option>
          <option value="notice">Avisos</option>
          <option value="user">Equipe</option>
          <option value="product">Cardápio</option>
          <option value="settings">Configurações</option>
        </select>
      </Field>
      {!page ? <p className="empty">Carregando…</p> : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Quando</th>
                <th scope="col">Quem</th>
                <th scope="col">Ação</th>
                <th scope="col">Detalhes</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((a) => (
                <tr key={a.id}>
                  <td>{dateTime(a.created_at, me.establishment.timezone)}</td>
                  <td>{a.actor_name ?? (a.actor_kind === "CLIENTE" ? "Cliente (mesa)" : "Sistema")}</td>
                  <td>
                    <code>{a.action}</code>
                  </td>
                  <td className="small">{Object.keys(a.details).length ? JSON.stringify(a.details) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button className="btn btn--small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>
              Anteriores
            </button>
            <span className="muted">{page.total} registros</span>
            <button className="btn btn--small" disabled={offset + 50 >= page.total} onClick={() => setOffset(offset + 50)}>
              Próximos
            </button>
          </div>
        </>
      )}
    </section>
  );
}

// ===================================== Configurações =====================================

export function AdminSettings() {
  const toast = useToast();
  const [est, setEst] = useState<Establishment | null>(null);
  useEffect(() => {
    api<Establishment>("/admin/establishment").then(setEst).catch((e) => toast(errorMessage(e), "error"));
  }, [toast]);
  if (!est) return <p className="empty">Carregando…</p>;
  return (
    <section className="stack s-narrow">
      <h1 className="s-h1">Configurações do estabelecimento</h1>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            setEst(await api<Establishment>("/admin/establishment", { method: "PATCH", body: { name: est.name, timezone: est.timezone, orders_enabled: est.orders_enabled } }));
            toast("Configurações salvas. Recarregue os painéis para aplicar o novo nome.", "ok");
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <Field label="Nome">
          <input value={est.name} onChange={(e) => setEst({ ...est, name: e.target.value })} required maxLength={120} />
        </Field>
        <Field label="Fuso horário" hint="Ex.: America/Manaus, America/Sao_Paulo">
          <input value={est.timezone} onChange={(e) => setEst({ ...est, timezone: e.target.value })} required />
        </Field>
        <label className="opt">
          <input type="checkbox" checked={est.orders_enabled} onChange={(e) => setEst({ ...est, orders_enabled: e.target.checked })} />
          <span>Clientes podem fazer pedidos pelo celular</span>
        </label>
        <button className="btn btn--primary">Salvar</button>
      </form>
    </section>
  );
}
