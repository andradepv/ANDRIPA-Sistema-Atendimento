import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/http";
import type { AuditEntry, Establishment, Page, ProvisionOut, Role, Table, Tag, User } from "../../api/types";
import { Dialog, Field, useToast } from "../../components/ui";
import { dateTime, tableStatusLabel } from "../../lib/format";
import { useStaff } from "../staff/StaffData";
import { qrUrl, StartTagDialog, TagBadge, TagWizard, useTagOf, WritingNow } from "./TagWizard";

export function AdminTables() {
  const toast = useToast();
  const { tables, can } = useStaff();
  const provision = can("tables.provision");
  const [all, setAll] = useState<Table[]>([]);
  const [number, setNumber] = useState("");
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [qr, setQr] = useState<Table | null>(null);
  const [starting, setStarting] = useState<Table | null>(null);
  const [wizard, setWizard] = useState<Tag | null>(null);

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

  const reset = () => {
    setNumber("");
    setName("");
    setSecret("");
  };

  // Um clique: cria a mesa (endereço, QR Code, posição na planta) e abre a gravação da etiqueta.
  const createAndWrite = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const out = await api<ProvisionOut>("/admin/tables/provision", {
        body: { number: Number(number), name: name || null, confirm_secret: secret },
      });
      reset();
      await load();
      setWizard(out.tag);
    } catch (err) {
      toast(errorMessage(err), "error");
      setSecret("");
    } finally {
      setBusy(false);
    }
  };

  const createOnly = async () => {
    try {
      await api("/tables", { body: { number: Number(number), name: name || null } });
      reset();
      await load();
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };

  return (
    <section className="stack">
      <h1 className="s-h1">Mesas, QR Codes e etiquetas NFC</h1>

      {provision && <WritingNow onOpen={setWizard} />}

      <form className="inline" onSubmit={(e) => void createAndWrite(e)}>
        <Field label="Número">
          <input inputMode="numeric" value={number} onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} required />
        </Field>
        <Field label="Nome (opcional)">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Ex.: Varanda" />
        </Field>
        {provision && (
          <Field label="Seu PIN ou senha" hint="Confirma quem está criando a mesa.">
            <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" minLength={4} />
          </Field>
        )}
        {provision ? (
          <>
            <button className="btn btn--primary" disabled={busy || !number || secret.length < 4}>
              {busy ? "Criando…" : "Criar mesa e gravar etiqueta"}
            </button>
            <button type="button" className="btn btn--ghost" disabled={!number} onClick={() => void createOnly()}>
              Só cadastrar (sem etiqueta)
            </button>
          </>
        ) : (
          <button type="button" className="btn" disabled={!number} onClick={() => void createOnly()}>
            Cadastrar mesa
          </button>
        )}
      </form>

      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Mesa</th>
            <th scope="col">Situação</th>
            <th scope="col">Etiqueta NFC</th>
            <th scope="col">Endereço da mesa (QR e NFC)</th>
            <th scope="col">Ações</th>
          </tr>
        </thead>
        <tbody>
          {all.map((t) => (
            <TableRow key={t.id} t={t} provision={provision} onQr={setQr} onStart={setStarting} onPatch={patch} onChanged={load} />
          ))}
        </tbody>
      </table>

      <StartTagDialog
        table={starting}
        onClose={() => setStarting(null)}
        onStarted={(tag) => {
          setStarting(null);
          setWizard(tag);
        }}
      />
      <TagWizard initial={wizard} onClose={() => setWizard(null)} />

      <Dialog open={!!qr} title={qr ? `QR Code da mesa ${qr.number}` : ""} onClose={() => setQr(null)}>
        {qr && (
          <div className="qr-print">
            <img src={qrUrl(qr.id)} alt={`QR Code da mesa ${qr.number}`} width={280} height={280} />
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

function TableRow({
  t,
  provision,
  onQr,
  onStart,
  onPatch,
  onChanged,
}: {
  t: Table;
  provision: boolean;
  onQr: (t: Table) => void;
  onStart: (t: Table) => void;
  onPatch: (t: Table, body: Record<string, unknown>) => Promise<void>;
  onChanged: () => Promise<unknown>;
}) {
  const toast = useToast();
  const { status, live } = useTagOf(t);
  const hasTag = status === "GRAVADA" || status === "TRAVADA";
  return (
    <tr className={t.active ? "" : "is-cancelled"}>
      <td>
        <strong>{t.number}</strong> {t.name}
      </td>
      <td>{t.active ? tableStatusLabel[t.status] : "Desativada"}</td>
      <td>
        <TagBadge status={status} />
        {live?.status === "FALHA" && live.error && <div className="muted small">{live.error}</div>}
      </td>
      <td>
        <code className="url">{t.public_url}</code>
      </td>
      <td className="inline">
        {provision && t.active && (
          <button className="btn btn--small btn--primary" onClick={() => onStart(t)}>
            {hasTag ? "Regravar etiqueta" : "Gravar etiqueta"}
          </button>
        )}
        <button className="btn btn--small" onClick={() => onQr(t)}>
          QR Code
        </button>
        <button
          className="btn btn--small btn--ghost"
          onClick={() => navigator.clipboard.writeText(t.public_url).then(() => toast("Endereço copiado.", "ok"))}
        >
          Copiar endereço
        </button>
        <button
          className="btn btn--small btn--ghost"
          disabled={t.status !== "LIVRE"}
          onClick={() => {
            if (confirm(`Gerar novo endereço para a mesa ${t.number}? O QR Code e a etiqueta antigos deixam de funcionar.`))
              void api(`/tables/${t.id}/rotate-code`, { body: {} }).then(onChanged).catch((e) => toast(errorMessage(e), "error"));
          }}
        >
          Gerar novo endereço
        </button>
        <button className="btn btn--small btn--ghost" disabled={t.status !== "LIVRE"} onClick={() => void onPatch(t, { active: !t.active })}>
          {t.active ? "Desativar" : "Reativar"}
        </button>
      </td>
    </tr>
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
          <option value="session">Sessões</option>
          <option value="request">Chamados</option>
          <option value="user">Equipe</option>
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
            setEst(await api<Establishment>("/admin/establishment", { method: "PATCH", body: { name: est.name, timezone: est.timezone, join_code_required: est.join_code_required } }));
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
          <input type="checkbox" checked={est.join_code_required} onChange={(e) => setEst({ ...est, join_code_required: e.target.checked })} />
          <span>Exigir código de 4 números para entrar na mesa (o atendente informa ao cliente; impede uso do QR Code fora do salão)</span>
        </label>
        <button className="btn btn--primary">Salvar</button>
      </form>
    </section>
  );
}
