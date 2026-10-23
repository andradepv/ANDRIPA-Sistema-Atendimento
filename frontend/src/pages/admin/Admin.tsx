import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/http";
import type { AuditEntry, Category, Coupon, Establishment, Page, Product, Promotion, Role, Table, User } from "../../api/types";
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
  const [form, setForm] = useState({ name: "", email: "", role: "ATENDENTE" as Role, password: "", pin: "" });
  const [reset, setReset] = useState<User | null>(null);
  const [newPw, setNewPw] = useState("");
  const load = useCallback(() => api<User[]>("/admin/users").then(setUsers), []);
  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, toast]);

  const patch = async (u: User, body: Record<string, unknown>) => {
    try {
      await api(`/admin/users/${u.id}`, { method: "PATCH", body });
      toast("Usuário atualizado. As sessões dele foram encerradas quando necessário.", "ok");
      await load();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  return (
    <section className="stack">
      <h1 className="s-h1">Equipe</h1>
      <form
        className="grid3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/admin/users", { body: { ...form, pin: form.pin || null } });
            setForm({ name: "", email: "", role: "ATENDENTE", password: "", pin: "" });
            toast("Usuário criado.", "ok");
            await load();
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <Field label="Nome">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        </Field>
        <Field label="E-mail">
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
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
        <Field label="Senha inicial" hint="Mínimo de 10 caracteres">
          <input type="password" minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required autoComplete="new-password" />
        </Field>
        <Field label="PIN (opcional)" hint="4 a 8 números">
          <input inputMode="numeric" pattern="\d{4,8}" value={form.pin} onChange={(e) => setForm({ ...form, pin: e.target.value.replace(/\D/g, "") })} />
        </Field>
        <div className="field field--end">
          <button className="btn btn--primary">Adicionar à equipe</button>
        </div>
      </form>
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Nome</th>
            <th scope="col">E-mail</th>
            <th scope="col">Papel</th>
            <th scope="col">Situação</th>
            <th scope="col">Ações</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={u.active ? "" : "is-cancelled"}>
              <td>{u.name}</td>
              <td>{u.email}</td>
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
                  Redefinir senha
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Dialog open={!!reset} title={`Nova senha para ${reset?.name ?? ""}`} onClose={() => setReset(null)}>
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault();
            if (reset) await patch(reset, { password: newPw });
            setNewPw("");
            setReset(null);
          }}
        >
          <Field label="Nova senha" hint="A pessoa será desconectada de todos os aparelhos.">
            <input type="password" minLength={10} value={newPw} onChange={(e) => setNewPw(e.target.value)} required autoComplete="new-password" />
          </Field>
          <button className="btn btn--primary">Redefinir senha</button>
        </form>
      </Dialog>
    </section>
  );
}

// ===================================== Promoções e cupons =====================================

const toLocalInput = (iso: string) => {
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const fromLocalInput = (v: string) => new Date(v).toISOString();

export function AdminPromotions() {
  const toast = useToast();
  const { me } = useStaff();
  const tz = me.establishment.timezone;
  const [promos, setPromos] = useState<Promotion[]>([]);
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const now = new Date();
  const inAWeek = new Date(now.getTime() + 7 * 864e5);
  const [p, setP] = useState({ kind: "BANNER", title: "", description: "", conditions: "", starts: toLocalInput(now.toISOString()), ends: toLocalInput(inAWeek.toISOString()) });
  const [c, setC] = useState({ code: "", description: "", discount_type: "PERCENT", value: "10", min: "", max_uses: "", starts: toLocalInput(now.toISOString()), ends: toLocalInput(inAWeek.toISOString()) });

  const load = useCallback(async () => {
    const [a, b] = await Promise.all([api<Promotion[]>("/admin/promotions"), api<Coupon[]>("/admin/coupons")]);
    setPromos(a);
    setCoupons(b);
  }, []);
  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, toast]);

  const vigente = (s: string, e: string, active: boolean) => active && new Date(s) <= now && now < new Date(e);

  return (
    <section className="stack">
      <h1 className="s-h1">Promoções e eventos</h1>
      <form
        className="grid3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/admin/promotions", {
              body: { kind: p.kind, title: p.title, description: p.description || null, conditions: p.conditions || null, starts_at: fromLocalInput(p.starts), ends_at: fromLocalInput(p.ends) },
            });
            setP({ ...p, title: "", description: "", conditions: "" });
            await load();
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <Field label="Tipo">
          <select value={p.kind} onChange={(e) => setP({ ...p, kind: e.target.value })}>
            <option value="BANNER">Promoção</option>
            <option value="EVENTO">Evento</option>
            <option value="CAMPANHA">Campanha</option>
          </select>
        </Field>
        <Field label="Título">
          <input value={p.title} onChange={(e) => setP({ ...p, title: e.target.value })} required maxLength={120} />
        </Field>
        <Field label="Descrição">
          <input value={p.description} onChange={(e) => setP({ ...p, description: e.target.value })} maxLength={1000} />
        </Field>
        <Field label="Condições">
          <input value={p.conditions} onChange={(e) => setP({ ...p, conditions: e.target.value })} maxLength={500} placeholder="Ex.: válido de segunda a quinta" />
        </Field>
        <Field label="Começa em">
          <input type="datetime-local" value={p.starts} onChange={(e) => setP({ ...p, starts: e.target.value })} required />
        </Field>
        <Field label="Termina em">
          <input type="datetime-local" value={p.ends} onChange={(e) => setP({ ...p, ends: e.target.value })} required />
        </Field>
        <div className="field field--end">
          <button className="btn btn--primary">Publicar</button>
        </div>
      </form>
      {promos.length === 0 ? <Empty>Nenhuma promoção cadastrada.</Empty> : (
        <table className="data-table">
          <tbody>
            {promos.map((x) => (
              <tr key={x.id}>
                <td>
                  <strong>{x.title}</strong> <span className="muted small">{x.kind === "BANNER" ? "Promoção" : x.kind === "EVENTO" ? "Evento" : "Campanha"}</span>
                </td>
                <td>
                  {dateTime(x.starts_at, tz)} até {dateTime(x.ends_at, tz)}
                </td>
                <td>{vigente(x.starts_at, x.ends_at, x.active) ? "Visível aos clientes" : x.active ? "Fora do período" : "Desativada"}</td>
                <td>
                  <button
                    className="btn btn--small btn--ghost"
                    onClick={() =>
                      api(`/admin/promotions/${x.id}`, {
                        method: "PUT",
                        body: { kind: x.kind, title: x.title, description: x.description, image_url: x.image_url, conditions: x.conditions, starts_at: x.starts_at, ends_at: x.ends_at, active: !x.active },
                      })
                        .then(load)
                        .catch((e) => toast(errorMessage(e), "error"))
                    }
                  >
                    {x.active ? "Desativar" : "Reativar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 className="s-h1">Cupons</h2>
      <p className="muted">O cliente pode conferir o cupom pelo celular; o desconto é aplicado pelo caixa no fechamento da conta.</p>
      <form
        className="grid3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/admin/coupons", {
              body: {
                code: c.code,
                description: c.description || null,
                discount_type: c.discount_type,
                value: c.discount_type === "PERCENT" ? Number(c.value) : toCents(c.value),
                min_order_cents: c.min ? toCents(c.min) : 0,
                max_uses: c.max_uses ? Number(c.max_uses) : null,
                starts_at: fromLocalInput(c.starts),
                ends_at: fromLocalInput(c.ends),
              },
            });
            setC({ ...c, code: "", description: "" });
            await load();
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <Field label="Código">
          <input value={c.code} onChange={(e) => setC({ ...c, code: e.target.value.toUpperCase() })} pattern="[A-Za-z0-9_\-]{3,32}" required />
        </Field>
        <Field label="Tipo de desconto">
          <select value={c.discount_type} onChange={(e) => setC({ ...c, discount_type: e.target.value })}>
            <option value="PERCENT">Percentual (%)</option>
            <option value="FIXED">Valor fixo (R$)</option>
          </select>
        </Field>
        <Field label={c.discount_type === "PERCENT" ? "Desconto (%)" : "Desconto (R$)"}>
          <input inputMode="decimal" value={c.value} onChange={(e) => setC({ ...c, value: e.target.value })} required />
        </Field>
        <Field label="Conta mínima (R$, opcional)">
          <input inputMode="decimal" value={c.min} onChange={(e) => setC({ ...c, min: e.target.value })} />
        </Field>
        <Field label="Limite de usos (opcional)">
          <input inputMode="numeric" value={c.max_uses} onChange={(e) => setC({ ...c, max_uses: e.target.value.replace(/\D/g, "") })} />
        </Field>
        <Field label="Descrição">
          <input value={c.description} onChange={(e) => setC({ ...c, description: e.target.value })} maxLength={280} />
        </Field>
        <Field label="Começa em">
          <input type="datetime-local" value={c.starts} onChange={(e) => setC({ ...c, starts: e.target.value })} required />
        </Field>
        <Field label="Termina em">
          <input type="datetime-local" value={c.ends} onChange={(e) => setC({ ...c, ends: e.target.value })} required />
        </Field>
        <div className="field field--end">
          <button className="btn btn--primary">Criar cupom</button>
        </div>
      </form>
      {coupons.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Código</th>
              <th scope="col">Desconto</th>
              <th scope="col">Usos</th>
              <th scope="col">Validade</th>
              <th scope="col">Situação</th>
            </tr>
          </thead>
          <tbody>
            {coupons.map((x) => (
              <tr key={x.id}>
                <td>
                  <code>{x.code}</code>
                </td>
                <td>{x.discount_type === "PERCENT" ? `${x.value}%` : money(x.value)}</td>
                <td>
                  {x.uses_count}
                  {x.max_uses != null && ` de ${x.max_uses}`}
                </td>
                <td>
                  {dateTime(x.starts_at, tz)} até {dateTime(x.ends_at, tz)}
                </td>
                <td>{vigente(x.starts_at, x.ends_at, x.active) ? "Vigente" : x.active ? "Fora do período" : "Desativado"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ===================================== Push =====================================

export function AdminPush() {
  const toast = useToast();
  const [stats, setStats] = useState<{ enabled: boolean; subscribers: number } | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<{ enabled: boolean; subscribers: number }>("/admin/push/stats").then(setStats), []);
  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, toast]);
  if (!stats) return <p className="empty">Carregando…</p>;
  return (
    <section className="stack s-narrow">
      <h1 className="s-h1">Notificações para clientes</h1>
      {!stats.enabled ? (
        <p className="warn-box">
          O envio de notificações não está configurado neste servidor. Gere as chaves VAPID com <code>python -m app.cli gen-vapid</code> e configure
          ANDRIPA_VAPID_PUBLIC_KEY e ANDRIPA_VAPID_PRIVATE_KEY.
        </p>
      ) : (
        <>
          <p>
            {stats.subscribers} cliente(s) aceitaram receber novidades. Só recebe quem deu consentimento, e cada um pode cancelar a qualquer momento.
          </p>
          <form
            className="stack"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                const r = await api<{ targeted: number; sent: number; failed: number; removed: number }>("/admin/push/broadcast", { body: { title, body, url: "/" } });
                toast(`Enviado para ${r.sent} de ${r.targeted}. ${r.removed} inscrição(ões) expirada(s) removida(s).`, "ok");
                setTitle("");
                setBody("");
                await load();
              } catch (err) {
                toast(errorMessage(err), "error");
              } finally {
                setBusy(false);
              }
            }}
          >
            <Field label="Título">
              <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80} required />
            </Field>
            <Field label="Mensagem">
              <textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)} maxLength={240} required />
            </Field>
            <button className="btn btn--primary" disabled={busy || stats.subscribers === 0}>
              {busy ? "Enviando…" : "Enviar notificação"}
            </button>
          </form>
        </>
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
          <option value="session">Contas</option>
          <option value="order">Pedidos</option>
          <option value="request">Chamados</option>
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
            setEst(await api<Establishment>("/admin/establishment", { method: "PATCH", body: { name: est.name, timezone: est.timezone, join_code_required: est.join_code_required, orders_enabled: est.orders_enabled } }));
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
        <label className="opt">
          <input type="checkbox" checked={est.join_code_required} onChange={(e) => setEst({ ...est, join_code_required: e.target.checked })} />
          <span>Exigir código de 4 números para entrar na mesa (o atendente informa ao cliente; impede uso do QR Code fora do salão)</span>
        </label>
        <button className="btn btn--primary">Salvar</button>
      </form>
    </section>
  );
}
