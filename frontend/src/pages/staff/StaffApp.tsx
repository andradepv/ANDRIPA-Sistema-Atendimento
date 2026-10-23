import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage, setUnauthorizedHandler } from "../../api/http";
import type { Me } from "../../api/types";
import { ConnectionBadge, Field, useToast } from "../../components/ui";
import { Link, navigate } from "../../lib/router";
import { AdminAudit, AdminMenu, AdminPromotions, AdminPush, AdminSettings, AdminTables, AdminUsers } from "../admin/Admin";
import { CashPanel, History } from "./Cash";
import { OpsBoard } from "./OpsBoard";
import { OrdersBoard } from "./OrdersBoard";
import { StaffDataProvider, useStaff } from "./StaffData";

export function StaffApp({ path }: { path: string }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    api<Me>("/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  const ended = useCallback(() => {
    setMe(null);
    navigate("/login", true);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(ended);
    return () => setUnauthorizedHandler(null);
  }, [ended]);

  if (me === undefined) return <div className="s-loading">Carregando…</div>;
  if (me === null || path === "/login") return <Login onLogin={(m) => { setMe(m); navigate("/painel", true); }} already={me} />;
  return (
    <StaffDataProvider me={me} onSessionEnded={ended}>
      <Layout path={path} onLogout={ended} />
    </StaffDataProvider>
  );
}

function Login({ onLogin, already }: { onLogin: (m: Me) => void; already: Me | null }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (already) navigate("/painel", true);
  }, [already]);
  return (
    <main className="login">
      <div className="login__card">
        <div className="tile-band tile-band--thin" aria-hidden="true" />
        <h1 className="login__brand">Andripa</h1>
        <p className="muted">Painel da equipe</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
              onLogin(await api<Me>("/auth/login", { body: { email, password } }));
            } catch (err) {
              setError(errorMessage(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="E-mail">
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </Field>
          <Field label="Senha">
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn--primary btn--block" disabled={busy}>
            {busy ? "Entrando…" : "Entrar"}
          </button>
        </form>
      </div>
    </main>
  );
}

const NAV: { to: string; label: string; perm: string }[] = [
  { to: "/painel", label: "Salão", perm: "tables.view" },
  { to: "/pedidos", label: "Pedidos", perm: "orders.view" },
  { to: "/caixa", label: "Caixa", perm: "cash.view" },
  { to: "/historico", label: "Histórico", perm: "history.view" },
  { to: "/admin/cardapio", label: "Cardápio", perm: "menu.manage" },
  { to: "/admin/mesas", label: "Mesas", perm: "tables.manage" },
  { to: "/admin/usuarios", label: "Equipe", perm: "users.manage" },
  { to: "/admin/promocoes", label: "Promoções", perm: "promotions.manage" },
  { to: "/admin/notificacoes", label: "Notificações", perm: "push.send" },
  { to: "/admin/auditoria", label: "Auditoria", perm: "audit.view" },
  { to: "/admin/configuracoes", label: "Configurações", perm: "settings.manage" },
];

function Layout({ path, onLogout }: { path: string; onLogout: () => void }) {
  const { me, conn, can, requests } = useStaff();
  const toast = useToast();
  const pending = requests.filter((r) => r.status === "PENDENTE").length;
  const items = NAV.filter((n) => can(n.perm));
  const current = items.find((n) => path.startsWith(n.to));
  useEffect(() => {
    if (!current && path !== "/conta") navigate(items[0]?.to ?? "/painel", true);
  }, [current, path, items]);

  const logout = async () => {
    try {
      await api("/auth/logout", { body: {} });
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) toast(errorMessage(e), "error");
    }
    onLogout();
  };

  return (
    <div className="s-shell">
      <header className="s-top">
        <div className="s-top__brand">
          <span className="s-logo" aria-hidden="true" />
          <span>{me.establishment.name}</span>
        </div>
        <ConnectionBadge status={conn} />
        <div className="s-top__user">
          <Link to="/conta" className="s-top__me">
            {me.user.name} <span className="muted">({roleLabel[me.user.role]})</span>
          </Link>
          <button className="btn btn--ghost btn--small" onClick={() => void logout()}>
            Sair
          </button>
        </div>
      </header>
      <nav className="s-nav" aria-label="Painéis">
        {items.map((n) => (
          <Link key={n.to} to={n.to} className="s-nav__item" aria-current={current?.to === n.to ? "page" : undefined}>
            {n.label}
            {n.to === "/painel" && pending > 0 && <span className="badge" aria-label={`${pending} pendentes`}>{pending}</span>}
          </Link>
        ))}
      </nav>
      <main className="s-main">
        {path.startsWith("/painel") && <OpsBoard />}
        {path.startsWith("/pedidos") && <OrdersBoard />}
        {path.startsWith("/caixa") && <CashPanel />}
        {path.startsWith("/historico") && <History />}
        {path.startsWith("/admin/cardapio") && <AdminMenu />}
        {path.startsWith("/admin/mesas") && <AdminTables />}
        {path.startsWith("/admin/usuarios") && <AdminUsers />}
        {path.startsWith("/admin/promocoes") && <AdminPromotions />}
        {path.startsWith("/admin/notificacoes") && <AdminPush />}
        {path.startsWith("/admin/auditoria") && <AdminAudit />}
        {path.startsWith("/admin/configuracoes") && <AdminSettings />}
        {path === "/conta" && <MyAccount />}
      </main>
    </div>
  );
}

const roleLabel = { ADMIN: "Administrador", CAIXA: "Caixa", ATENDENTE: "Atendente" } as const;

function MyAccount() {
  const toast = useToast();
  const { me } = useStaff();
  const [current, setCurrent] = useState("");
  const [pw, setPw] = useState("");
  const [pin, setPin] = useState("");
  return (
    <section className="s-section s-narrow">
      <h1 className="s-h1">Minha conta</h1>
      <p className="muted">
        {me.user.email} · PIN {me.user.has_pin ? "configurado" : "não configurado (a abertura de mesa pedirá sua senha)"}
      </p>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/auth/credentials", {
              body: { current_password: current, new_password: pw || null, new_pin: pin || null },
            });
            toast("Credenciais atualizadas.", "ok");
            setCurrent("");
            setPw("");
            setPin("");
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <Field label="Senha atual">
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoComplete="current-password" />
        </Field>
        <Field label="Nova senha" hint="Mínimo de 10 caracteres. Deixe em branco para manter.">
          <input type="password" value={pw} minLength={10} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" />
        </Field>
        <Field label="Novo PIN pessoal" hint="4 a 8 números, usado para confirmar a abertura de mesas.">
          <input inputMode="numeric" value={pin} pattern="\d{4,8}" onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} />
        </Field>
        <button className="btn btn--primary" disabled={!current || (!pw && !pin)}>
          Salvar
        </button>
      </form>
    </section>
  );
}
