import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage, newIdempotencyKey } from "../../api/http";
import type { CustomerSession, MenuCategory, Notice, Product, PublicTable, RealtimeEvent, ServiceRequest } from "../../api/types";
import { Dialog, useToast } from "../../components/ui";
import { clock, money, orderSummary, requestStatusLabel, requestTitle } from "../../lib/format";
import { navigate } from "../../lib/router";
import { openSocket, upsertVersioned, type SocketStatus } from "../../realtime/socket";

const tokenKey = (code: string) => `andripa:tok:${code}`;
function loadToken(code: string): string | null {
  try {
    return localStorage.getItem(tokenKey(code));
  } catch {
    return null;
  }
}
function saveToken(code: string, tok: string | null): void {
  try {
    if (tok) localStorage.setItem(tokenKey(code), tok);
    else localStorage.removeItem(tokenKey(code));
  } catch {
    /* modo privado: o token fica só em memória */
  }
}

type Phase =
  | { kind: "loading" }
  | { kind: "notfound" }
  | { kind: "unavailable"; table: PublicTable }
  | { kind: "ended"; table: PublicTable | null }
  | { kind: "active"; token: string };

export function CustomerApp({ code }: { code: string }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [table, setTable] = useState<PublicTable | null>(null);

  const check = useCallback(async () => {
    try {
      const t = await api<PublicTable>(`/public/tables/${code}`);
      setTable(t);
      document.title = `Mesa ${t.table_number} · ${t.establishment_name}`;
      if (!t.available) {
        saveToken(code, null);
        setPhase({ kind: "unavailable", table: t });
        return;
      }
      let tok = loadToken(code);
      if (!tok) {
        tok = (await api<{ token: string }>(`/public/tables/${code}/join`, { body: {} })).token;
        saveToken(code, tok);
      }
      setPhase({ kind: "active", token: tok });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setPhase({ kind: "notfound" });
      else setPhase({ kind: "ended", table: null });
    }
  }, [code]);

  useEffect(() => {
    void check();
  }, [check]);

  const onEnded = useCallback(() => {
    saveToken(code, null);
    setPhase({ kind: "ended", table });
  }, [code, table]);

  const back = () => navigate(`/m/${code}`);
  if (phase.kind === "loading") return <Splash text="Abrindo a mesa…" />;
  if (phase.kind === "notfound")
    return <Splash title="Mesa não encontrada" text="Leia o QR Code de novo ou aproxime o celular da etiqueta da mesa." />;
  if (phase.kind === "unavailable") return <NotOpen table={phase.table} onBack={back} onRetry={() => void check()} />;
  if (phase.kind === "ended")
    return (
      <Splash
        title="Atendimento encerrado"
        text="A conta desta mesa foi finalizada. Obrigado pela visita!"
        action={{ label: "Voltar ao início da mesa", onClick: back }}
        establishment={phase.table?.establishment_name}
      />
    );
  return <ActiveSession token={phase.token} onEnded={onEnded} />;
}

export function Splash(props: {
  title?: string;
  text: string;
  establishment?: string;
  action?: { label: string; onClick: () => void };
  secondary?: { label: string; onClick: () => void };
}) {
  return (
    <main className="c-shell c-center">
      <div className="tile-band" aria-hidden="true" />
      {props.establishment && <p className="c-est">{props.establishment}</p>}
      {props.title && <h1 className="c-title">{props.title}</h1>}
      <p className="c-lead">{props.text}</p>
      {props.action && (
        <button className="btn btn--primary" onClick={props.action.onClick}>
          {props.action.label}
        </button>
      )}
      {props.secondary && (
        <button className="btn btn--ghost" onClick={props.secondary.onClick}>
          {props.secondary.label}
        </button>
      )}
    </main>
  );
}

/** Mesa ainda não liberada pela equipe. */
export function NotOpen({ table, onBack, onRetry }: { table: PublicTable; onBack: () => void; onRetry: () => void }) {
  return (
    <Splash
      title={`Mesa ${table.table_number}`}
      text="Esta mesa ainda não foi liberada. Peça a um atendente para liberar a mesa e tente de novo."
      establishment={table.establishment_name}
      action={{ label: "Tentar de novo", onClick: onRetry }}
      secondary={{ label: "Voltar", onClick: onBack }}
    />
  );
}

// ---------------------------------------------------------------------------------------------

type Tab = "mesa" | "cardapio" | "novidades";
interface CartLine {
  key: string;
  product: Product;
  quantity: number;
  optionIds: string[];
  notes: string;
}

function lineUnit(l: CartLine): number {
  const opts = l.product.option_groups.flatMap((g) => g.options).filter((o) => l.optionIds.includes(o.id));
  return l.product.price_cents + opts.reduce((s, o) => s + o.price_cents, 0);
}

function ActiveSession({ token, onEnded }: { token: string; onEnded: () => void }) {
  const toast = useToast();
  const [s, setS] = useState<CustomerSession | null>(null);
  const [conn, setConn] = useState<SocketStatus>("connecting");
  const [menu, setMenu] = useState<MenuCategory[] | null>(null);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [noticesVersion, setNoticesVersion] = useState(0);

  const ended = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) {
        onEnded();
        return true;
      }
      return false;
    },
    [onEnded],
  );

  const refresh = useCallback(async () => {
    try {
      setS(await api<CustomerSession>("/public/session", { bearer: token }));
    } catch (e) {
      if (!ended(e)) toast(errorMessage(e), "error");
    }
  }, [token, ended, toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    return openSocket({
      path: "/api/v1/ws/customer",
      authToken: token,
      onStatus: setConn,
      onOpen: () => void refresh(),
      onEnded: () => onEnded(),
      onEvent: (ev: RealtimeEvent) => {
        if (ev.type === "session.closed") onEnded();
        else if (ev.type === "request.updated") {
          const r = ev.data!.request as ServiceRequest;
          setS((cur) => (cur ? { ...cur, requests: upsertVersioned(cur.requests, r) } : cur));
        } else if (ev.type === "menu.updated") void loadMenu();
        else if (ev.type === "notices.updated") setNoticesVersion((v) => v + 1);
      },
    });
  }, [token, refresh, onEnded]);

  if (!s) return <Splash text="Carregando…" />;

  return (
    <div className="c-shell">
      <header className="c-head">
        <div className="tile-band tile-band--thin" aria-hidden="true" />
        <div className="c-head__row">
          <div>
            <p className="c-est">{s.establishment_name}</p>
            <h1 className="c-table">
              Mesa {s.table_number}
              {s.table_name ? <span className="c-table__name"> {s.table_name}</span> : null}
            </h1>
          </div>
          {conn !== "online" && <span className="c-offline">{conn === "connecting" ? "Conectando…" : "Sem conexão"}</span>}
        </div>
      </header>
      <main className="c-main">
        {tab === "mesa" && <HomeTab s={s} token={token} onChanged={refresh} onEnded={ended} goMenu={() => setTab("cardapio")} />}
        {tab === "cardapio" && (
          <MenuTab
            s={s}
            menu={menu}
            cart={cart}
            setCart={setCart}
            token={token}
            onSent={() => {
              setCart([]);
              setTab("mesa");
              void refresh();
            }}
            onEnded={ended}
          />
        )}
        {tab === "novidades" && <NewsTab s={s} token={token} noticesVersion={noticesVersion} onEnded={ended} />}
      </main>

      <nav className="c-nav" aria-label="Seções">
        {(
          [
            ["mesa", "Mesa"],
            ["cardapio", cartCount ? `Cardápio (${cartCount})` : "Cardápio"],
            ["novidades", "Novidades"],
          ] as [Tab, string][]
        ).map(([k, label]) => (
          <button key={k} className="c-nav__btn" aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </nav>
    </div>
  );
}

function pendingOf(s: CustomerSession, type: ServiceRequest["type"]): ServiceRequest | undefined {
  return s.requests.find((r) => r.type === type && r.status === "PENDENTE");
}

function HomeTab(props: {
  s: CustomerSession;
  token: string;
  onChanged: () => Promise<void>;
  onEnded: (e: unknown) => boolean;
}) {
  const { s } = props;
  const toast = useToast();
  const [confirm, setConfirm] = useState<null | "CHAMAR_ATENDENTE" | "PEDIR_CONTA">(null);
  const [busy, setBusy] = useState(false);
  const keyRef = useRef<string | null>(null);
  const call = pendingOf(s, "CHAMAR_ATENDENTE");
  const billRequested = !!pendingOf(s, "PEDIR_CONTA");

  const send = async () => {
    if (!confirm) return;
    setBusy(true);
    keyRef.current ??= newIdempotencyKey("req");
    try {
      await api("/public/service-requests", { body: { type: confirm }, bearer: props.token, idempotencyKey: keyRef.current });
      keyRef.current = null;
      toast(confirm === "PEDIR_CONTA" ? "Pedido de conta enviado ao caixa." : "Chamado enviado. Um atendente já foi avisado.", "ok");
      setConfirm(null);
      await props.onChanged();
    } catch (e) {
      if (!props.onEnded(e)) toast(errorMessage(e), "error"); // mantém a mesma chave: repetir é seguro
    } finally {
      setBusy(false);
    }
  };

  const cancelCall = async () => {
    if (!call) return;
    try {
      await api(`/public/service-requests/${call.id}/cancel`, { body: {}, bearer: props.token });
      await props.onChanged();
    } catch (e) {
      if (!props.onEnded(e)) toast(errorMessage(e), "error");
    }
  };

  return (
    <section aria-labelledby="home-h">
      <h2 id="home-h" className="sr-only">
        Atendimento
      </h2>
      <div className="big-actions">
        <button className="big-btn big-btn--call" onClick={() => setConfirm("CHAMAR_ATENDENTE")} disabled={!!call}>
          <span className="big-btn__title">{call ? "Atendente avisado" : "Chamar atendente"}</span>
          <span className="big-btn__sub">{call ? `Chamado às ${clock(call.created_at, s.timezone)}` : "Um toque avisa a equipe"}</span>
        </button>
        <button className="big-btn big-btn--bill" onClick={() => setConfirm("PEDIR_CONTA")} disabled={billRequested}>
          <span className="big-btn__title">{billRequested ? "Conta solicitada" : "Pedir a conta"}</span>
          <span className="big-btn__sub">{billRequested ? "O caixa já foi avisado" : "Avisa o caixa para fechar a mesa"}</span>
        </button>
      </div>

      {call?.status === "PENDENTE" && (
        <p className="c-note">
          Chamou por engano?{" "}
          <button className="link-btn" onClick={() => void cancelCall()}>
            Cancelar chamado
          </button>
        </p>
      )}

      <h3 className="c-h3">Acompanhamento</h3>
      {s.requests.length === 0 ? (
        <p className="empty">Nada por aqui ainda. Seus chamados e pedidos aparecem aqui em tempo real.</p>
      ) : (
        <ul className="timeline">
          {s.requests.slice(0, 20).map((r) => (
            <li key={r.id} className={`timeline__item st-${r.status}`}>
              <span>
                {requestTitle(r)}
                {r.order && <span className="muted small timeline__sub">{orderSummary(r)}</span>}
              </span>
              <span className="pill">{requestStatusLabel(r)}</span>
              <time>
                {clock(r.created_at, s.timezone)}
                {r.completed_at && r.status === "CONCLUIDA" && ` → ${clock(r.completed_at, s.timezone)}`}
              </time>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={!!confirm} title={confirm === "PEDIR_CONTA" ? "Pedir a conta?" : "Chamar um atendente?"} onClose={() => setConfirm(null)}>
        <p>
          {confirm === "PEDIR_CONTA"
            ? `O caixa será avisado para fechar a conta da mesa ${s.table_number}.`
            : `Um atendente virá até a mesa ${s.table_number}.`}
        </p>
        <div className="dialog__actions">
          <button className="btn btn--ghost" onClick={() => setConfirm(null)}>
            Voltar
          </button>
          <button className="btn btn--primary" onClick={() => void send()} disabled={busy}>
            {busy ? "Enviando…" : confirm === "PEDIR_CONTA" ? "Pedir a conta" : "Chamar atendente"}
          </button>
        </div>
      </Dialog>
    </section>
  );
}

function MenuTab(props: {
  s: CustomerSession;
  menu: MenuCategory[] | null;
  cart: CartLine[];
  setCart: (f: (c: CartLine[]) => CartLine[]) => void;
  token: string;
  onSent: () => void;
  onEnded: (e: unknown) => boolean;
}) {
  const toast = useToast();
  const [picking, setPicking] = useState<Product | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [sending, setSending] = useState(false);
  const keyRef = useRef<string | null>(null);
  const total = props.cart.reduce((s, l) => s + lineUnit(l) * l.quantity, 0);

  if (!props.menu) return <p className="empty">Carregando cardápio…</p>;
  if (props.menu.length === 0) return <p className="empty">O cardápio ainda não foi publicado. Chame o atendente.</p>;

  const send = async () => {
    setSending(true);
    keyRef.current ??= newIdempotencyKey("ord");
    try {
      await api<ServiceRequest>("/public/orders", {
        bearer: props.token,
        idempotencyKey: keyRef.current,
        body: {
          items: props.cart.map((l) => ({
            product_id: l.product.id,
            quantity: l.quantity,
            option_ids: l.optionIds,
            notes: l.notes || null,
          })),
        },
      });
      keyRef.current = null;
      toast("Pedido enviado! A equipe vai repassá-lo à cozinha.", "ok");
      setReviewing(false);
      props.onSent();
    } catch (e) {
      if (!props.onEnded(e)) toast(errorMessage(e), "error");
    } finally {
      setSending(false);
    }
  };

  return (
    <section aria-labelledby="menu-h">
      <h2 id="menu-h" className="sr-only">
        Cardápio
      </h2>
      <nav className="cat-jump" aria-label="Categorias">
        {props.menu.map((c) => (
          <a key={c.id} href={`#cat-${c.id}`}>
            {c.name}
          </a>
        ))}
      </nav>
      {props.menu.map((c) => (
        <div key={c.id} id={`cat-${c.id}`} className="cat">
          <h3 className="cat__title">{c.name}</h3>
          <ul className="products">
            {c.products.map((p) => (
              <li key={p.id} className={p.available ? "product" : "product product--off"}>
                {p.image_url && <img src={p.image_url} alt="" loading="lazy" className="product__img" />}
                <div className="product__text">
                  <span className="product__name">{p.name}</span>
                  {p.description && <span className="product__desc">{p.description}</span>}
                  <span className="product__price">{p.available ? money(p.price_cents) : "Indisponível agora"}</span>
                </div>
                {props.s.orders_enabled && p.available && (
                  <button className="btn btn--small" onClick={() => setPicking(p)} aria-label={`Adicionar ${p.name}`}>
                    Adicionar
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}

      {props.cart.length > 0 && (
        <div className="cart-bar">
          <button className="btn btn--primary btn--block" onClick={() => setReviewing(true)}>
            Revisar pedido · {money(total)}
          </button>
        </div>
      )}

      <ProductDialog
        product={picking}
        onClose={() => setPicking(null)}
        onAdd={(line) => {
          props.setCart((c) => [...c, line]);
          setPicking(null);
          toast(`${line.product.name} no carrinho.`, "info");
        }}
      />

      <Dialog open={reviewing} title="Seu pedido" onClose={() => setReviewing(false)}>
        <ul className="cart">
          {props.cart.map((l) => (
            <li key={l.key} className="cart__line">
              <div>
                <strong>{l.product.name}</strong>
                {l.optionIds.length > 0 && (
                  <span className="muted">
                    {" "}
                    + {l.product.option_groups.flatMap((g) => g.options).filter((o) => l.optionIds.includes(o.id)).map((o) => o.name).join(", ")}
                  </span>
                )}
                {l.notes && <span className="muted"> · “{l.notes}”</span>}
              </div>
              <div className="qty">
                <button
                  className="icon-btn"
                  aria-label={`Diminuir ${l.product.name}`}
                  onClick={() => props.setCart((c) => c.flatMap((x) => (x.key === l.key ? (x.quantity > 1 ? [{ ...x, quantity: x.quantity - 1 }] : []) : [x])))}
                >
                  −
                </button>
                <span aria-live="polite">{l.quantity}</span>
                <button
                  className="icon-btn"
                  aria-label={`Aumentar ${l.product.name}`}
                  onClick={() => props.setCart((c) => c.map((x) => (x.key === l.key ? { ...x, quantity: Math.min(50, x.quantity + 1) } : x)))}
                >
                  +
                </button>
              </div>
              <span className="cart__price">{money(lineUnit(l) * l.quantity)}</span>
            </li>
          ))}
        </ul>
        <p className="cart__total">
          Total estimado <strong>{money(total)}</strong>
        </p>
        <p className="muted small">O valor final é confirmado pelo estabelecimento com os preços do cardápio no momento do envio.</p>
        <div className="dialog__actions">
          <button className="btn btn--ghost" onClick={() => setReviewing(false)}>
            Continuar escolhendo
          </button>
          <button className="btn btn--primary" disabled={sending || props.cart.length === 0} onClick={() => void send()}>
            {sending ? "Enviando…" : "Enviar pedido"}
          </button>
        </div>
      </Dialog>
    </section>
  );
}

function ProductDialog(props: { product: Product | null; onClose: () => void; onAdd: (l: CartLine) => void }) {
  const p = props.product;
  const [qty, setQty] = useState(1);
  const [opts, setOpts] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  useEffect(() => {
    setQty(1);
    setOpts([]);
    setNotes("");
  }, [p?.id]);
  const problems = useMemo(() => {
    if (!p) return [];
    return p.option_groups.flatMap((g) => {
      const n = g.options.filter((o) => opts.includes(o.id)).length;
      return n < g.min_select ? [`Escolha pelo menos ${g.min_select} em ${g.name}`] : [];
    });
  }, [p, opts]);
  if (!p) return <Dialog open={false} title="" onClose={props.onClose}>{null}</Dialog>;
  const unit = p.price_cents + p.option_groups.flatMap((g) => g.options).filter((o) => opts.includes(o.id)).reduce((s, o) => s + o.price_cents, 0);
  return (
    <Dialog open title={p.name} onClose={props.onClose}>
      {p.description && <p className="muted">{p.description}</p>}
      {p.option_groups.map((g) => {
        const chosen = g.options.filter((o) => opts.includes(o.id)).length;
        const single = g.max_select === 1;
        return (
          <fieldset key={g.id} className="opt-group">
            <legend>
              {g.name}{" "}
              <span className="muted small">
                {g.min_select > 0 ? `obrigatório, ` : ""}até {g.max_select}
              </span>
            </legend>
            {g.options.map((o) => {
              const checked = opts.includes(o.id);
              return (
                <label key={o.id} className="opt">
                  <input
                    type={single ? "radio" : "checkbox"}
                    name={`g-${g.id}`}
                    checked={checked}
                    disabled={!checked && !single && chosen >= g.max_select}
                    onChange={() =>
                      setOpts((cur) => {
                        const others = single ? cur.filter((id) => !g.options.some((x) => x.id === id)) : cur;
                        return checked ? cur.filter((id) => id !== o.id) : [...others, o.id];
                      })
                    }
                  />
                  <span>{o.name}</span>
                  {o.price_cents > 0 && <span className="muted">+ {money(o.price_cents)}</span>}
                </label>
              );
            })}
          </fieldset>
        );
      })}
      <label className="field">
        <span className="field__label">Observação (opcional)</span>
        <input value={notes} maxLength={280} onChange={(e) => setNotes(e.target.value)} placeholder="Ex.: sem cebola" />
      </label>
      <div className="qty qty--big">
        <button className="icon-btn" onClick={() => setQty((q) => Math.max(1, q - 1))} aria-label="Diminuir quantidade">
          −
        </button>
        <span aria-live="polite">{qty}</span>
        <button className="icon-btn" onClick={() => setQty((q) => Math.min(50, q + 1))} aria-label="Aumentar quantidade">
          +
        </button>
      </div>
      {problems.map((x) => (
        <p key={x} className="form-error">
          {x}
        </p>
      ))}
      <div className="dialog__actions">
        <button
          className="btn btn--primary btn--block"
          disabled={problems.length > 0}
          // crypto.randomUUID só existe em HTTPS; getRandomValues (usado aqui) funciona também na rede local.
          onClick={() => props.onAdd({ key: newIdempotencyKey("item"), product: p, quantity: qty, optionIds: opts, notes })}
        >
          Adicionar · {money(unit * qty)}
        </button>
      </div>
    </Dialog>
  );
}

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function NewsTab(props: { s: CustomerSession; token: string; noticesVersion: number; onEnded: (e: unknown) => boolean }) {
  const { s, token, onEnded } = props;
  const toast = useToast();
  const [notices, setNotices] = useState<Notice[] | null>(null);
  const [pushState, setPushState] = useState<"unsupported" | "idle" | "on" | "denied" | "busy">("idle");
  const [calling, setCalling] = useState(false);
  const keyRef = useRef<string | null>(null);
  const called = !!pendingOf(s, "CHAMAR_ATENDENTE");

  useEffect(() => {
    api<Notice[]>("/public/notices", { bearer: token }).then(setNotices).catch(() => setNotices([]));
  }, [token, props.noticesVersion]);

  useEffect(() => {
    const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window && !!s.push_public_key;
    if (!supported) {
      setPushState("unsupported");
      return;
    }
    if (Notification.permission === "denied") setPushState("denied");
    navigator.serviceWorker.ready
      .then((r) => r.pushManager.getSubscription())
      .then((sub) => sub && setPushState("on"))
      .catch(() => undefined);
  }, [s.push_public_key]);

  const call = async () => {
    setCalling(true);
    keyRef.current ??= newIdempotencyKey("req");
    try {
      await api("/public/service-requests", { body: { type: "CHAMAR_ATENDENTE" }, bearer: token, idempotencyKey: keyRef.current });
      keyRef.current = null;
      toast("Chamado enviado. Um atendente já foi avisado.", "ok");
    } catch (e) {
      if (!onEnded(e)) toast(errorMessage(e), "error");
    } finally {
      setCalling(false);
    }
  };

  const subscribe = async () => {
    setPushState("busy");
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        setPushState(perm === "denied" ? "denied" : "idle");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(s.push_public_key!) });
      await api("/public/push/subscribe", { bearer: token, body: { subscription: sub.toJSON(), consent_marketing: true } });
      setPushState("on");
      toast("Pronto! Você vai receber novidades deste estabelecimento.", "ok");
    } catch (e) {
      setPushState("idle");
      toast(errorMessage(e), "error");
    }
  };

  const unsubscribe = async () => {
    setPushState("busy");
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await api("/public/push/unsubscribe", { body: { endpoint: sub.endpoint } });
        await sub.unsubscribe();
      }
      setPushState("idle");
      toast("Você não receberá mais notificações.", "ok");
    } catch (e) {
      setPushState("on");
      toast(errorMessage(e), "error");
    }
  };

  return (
    <section aria-labelledby="news-h">
      <h2 id="news-h" className="c-h2">
        Novidades
      </h2>
      {notices === null ? (
        <p className="empty">Carregando…</p>
      ) : notices.length === 0 ? (
        <p className="empty">Nenhuma novidade no momento.</p>
      ) : (
        <>
          <ul className="promos">
            {notices.map((n) => (
              <li key={n.id} className="promo">
                <strong className="promo__title">{n.title}</strong>
                {n.message && <p>{n.message}</p>}
              </li>
            ))}
          </ul>
          <div className="news-cta">
            <p className="muted">Quer saber mais ou aproveitar? Chame um atendente.</p>
            <button className="btn btn--primary btn--block" onClick={() => void call()} disabled={calling || called}>
              {called ? "Atendente avisado" : calling ? "Chamando…" : "Chamar atendente"}
            </button>
          </div>
        </>
      )}

      {pushState !== "unsupported" && (
        <div className="push-box">
          <h3 className="c-h3">Notificações</h3>
          {pushState === "denied" && <p className="muted small">As notificações estão bloqueadas nas configurações do navegador.</p>}
          {(pushState === "idle" || pushState === "busy") && (
            <>
              <p className="small">Receba avisos de novidades deste estabelecimento. Você pode cancelar quando quiser.</p>
              <button className="btn" onClick={() => void subscribe()} disabled={pushState === "busy"}>
                Quero receber novidades
              </button>
            </>
          )}
          {pushState === "on" && (
            <>
              <p className="small">Você recebe novidades deste estabelecimento.</p>
              <button className="btn btn--ghost" onClick={() => void unsubscribe()}>
                Parar de receber
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
