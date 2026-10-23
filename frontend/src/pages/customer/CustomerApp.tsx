import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, errorMessage, newIdempotencyKey } from "../../api/http";
import type {
  CouponValidation,
  CustomerSession,
  MenuCategory,
  Order,
  Product,
  Promotion,
  PublicTable,
  RealtimeEvent,
  ServiceRequest,
} from "../../api/types";
import { Dialog, useToast } from "../../components/ui";
import { clock, money, orderStatusLabel, requestStatusLabel } from "../../lib/format";
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
  | { kind: "join"; table: PublicTable }
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
      const tok = loadToken(code);
      if (tok) {
        setPhase({ kind: "active", token: tok });
        return;
      }
      if (t.join_code_required) setPhase({ kind: "join", table: t });
      else await join(undefined, t);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setPhase({ kind: "notfound" });
      else setPhase({ kind: "ended", table: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const join = async (joinCode: string | undefined, t: PublicTable) => {
    const r = await api<{ token: string }>(`/public/tables/${code}/join`, {
      body: joinCode ? { join_code: joinCode } : {},
    });
    saveToken(code, r.token);
    setPhase({ kind: "active", token: r.token });
    void t;
  };

  useEffect(() => {
    void check();
  }, [check]);

  const onEnded = useCallback(() => {
    saveToken(code, null);
    setPhase({ kind: "ended", table });
  }, [code, table]);

  if (phase.kind === "loading") return <Splash text="Abrindo a mesa…" />;
  if (phase.kind === "notfound")
    return <Splash title="Mesa não encontrada" text="Leia o QR Code de novo ou aproxime o celular da etiqueta da mesa." />;
  if (phase.kind === "unavailable")
    return (
      <Splash
        title={`Mesa ${phase.table.table_number}`}
        text="Esta mesa ainda não está aberta para atendimento digital. Peça a um atendente para abrir a mesa e leia o QR Code novamente."
        action={{ label: "Verificar de novo", onClick: () => void check() }}
        establishment={phase.table.establishment_name}
      />
    );
  if (phase.kind === "ended")
    return (
      <Splash
        title="Atendimento encerrado"
        text="A conta desta mesa foi fechada. Obrigado pela visita! Se você ainda está na mesa, peça para abri-la de novo."
        action={{ label: "Verificar de novo", onClick: () => void check() }}
        establishment={phase.table?.establishment_name}
      />
    );
  if (phase.kind === "join") return <JoinScreen table={phase.table} onJoin={(c) => join(c, phase.table)} />;
  return <ActiveSession token={phase.token} onEnded={onEnded} />;
}

function Splash(props: {
  title?: string;
  text: string;
  establishment?: string;
  action?: { label: string; onClick: () => void };
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
    </main>
  );
}

function JoinScreen({ table, onJoin }: { table: PublicTable; onJoin: (code: string) => Promise<void> }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <main className="c-shell c-center">
      <div className="tile-band" aria-hidden="true" />
      <p className="c-est">{table.establishment_name}</p>
      <h1 className="c-title">Mesa {table.table_number}</h1>
      <form
        className="join"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await onJoin(value);
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor="jc">Digite o código de 4 números que o atendente informou</label>
        <input
          id="jc"
          className="join__code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="\d{4}"
          maxLength={4}
          value={value}
          onChange={(e) => setValue(e.target.value.replace(/\D/g, ""))}
          aria-invalid={!!error}
          aria-describedby={error ? "jc-err" : undefined}
          required
        />
        {error && (
          <p id="jc-err" className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="btn btn--primary btn--block" disabled={busy || value.length !== 4}>
          {busy ? "Entrando…" : "Entrar na mesa"}
        </button>
      </form>
    </main>
  );
}

// ---------------------------------------------------------------------------------------------

type Tab = "mesa" | "cardapio" | "comanda" | "novidades";
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
  const [tab, setTab] = useState<Tab>("mesa");
  const [conn, setConn] = useState<SocketStatus>("connecting");
  const [menu, setMenu] = useState<MenuCategory[] | null>(null);
  const [cart, setCart] = useState<CartLine[]>([]);

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

  const loadMenu = useCallback(async () => {
    try {
      setMenu(await api<MenuCategory[]>("/public/menu", { bearer: token }));
    } catch (e) {
      ended(e);
    }
  }, [token, ended]);

  useEffect(() => {
    void refresh();
    void loadMenu();
  }, [refresh, loadMenu]);

  // Carrinho persistido por sessão de mesa (sobrevive a recarregar a página).
  useEffect(() => {
    if (!s) return;
    try {
      const raw = sessionStorage.getItem(`andripa:cart:${s.session_id}`);
      if (raw && menu) {
        const saved = JSON.parse(raw) as { productId: string; quantity: number; optionIds: string[]; notes: string; key: string }[];
        const products = new Map(menu.flatMap((c) => c.products).map((p) => [p.id, p]));
        setCart(saved.flatMap((x) => (products.get(x.productId) ? [{ ...x, product: products.get(x.productId)! }] : [])));
      }
    } catch {
      /* ignore */
    }
  }, [s?.session_id, menu]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!s) return;
    try {
      sessionStorage.setItem(
        `andripa:cart:${s.session_id}`,
        JSON.stringify(cart.map((l) => ({ key: l.key, productId: l.product.id, quantity: l.quantity, optionIds: l.optionIds, notes: l.notes }))),
      );
    } catch {
      /* ignore */
    }
  }, [cart, s?.session_id]); // eslint-disable-line react-hooks/exhaustive-deps

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
        } else if (ev.type === "order.updated") {
          const o = ev.data!.order as Order;
          setS((cur) => (cur ? { ...cur, orders: upsertVersioned(cur.orders, o) } : cur));
          void refresh(); // total da comanda
        } else if (ev.type === "menu.updated") void loadMenu();
      },
    });
  }, [token, refresh, loadMenu, onEnded]);

  if (!s) return <Splash text="Carregando…" />;

  const cartCount = cart.reduce((n, l) => n + l.quantity, 0);
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
              setTab("comanda");
              void refresh();
            }}
            onEnded={ended}
          />
        )}
        {tab === "comanda" && <BillTab s={s} />}
        {tab === "novidades" && <NewsTab s={s} token={token} />}
      </main>

      <nav className="c-nav" aria-label="Seções">
        {(
          [
            ["mesa", "Mesa"],
            ["cardapio", cartCount ? `Cardápio (${cartCount})` : "Cardápio"],
            ["comanda", "Comanda"],
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

function activeOf(s: CustomerSession, type: ServiceRequest["type"]): ServiceRequest | undefined {
  return s.requests.find((r) => r.type === type && ["PENDENTE", "ASSUMIDA", "EM_ATENDIMENTO"].includes(r.status));
}

function HomeTab(props: {
  s: CustomerSession;
  token: string;
  onChanged: () => Promise<void>;
  onEnded: (e: unknown) => boolean;
  goMenu: () => void;
}) {
  const { s } = props;
  const toast = useToast();
  const [confirm, setConfirm] = useState<null | "CHAMAR_ATENDENTE" | "PEDIR_CONTA">(null);
  const [busy, setBusy] = useState(false);
  const keyRef = useRef<string | null>(null);
  const call = activeOf(s, "CHAMAR_ATENDENTE");
  const bill = activeOf(s, "PEDIR_CONTA");
  const billRequested = !!bill || s.table_status === "ENCERRAMENTO_SOLICITADO";

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
          <span className="big-btn__title">{call ? "Atendente a caminho" : "Chamar atendente"}</span>
          <span className="big-btn__sub">
            {call ? `${requestStatusLabel[call.status]} · ${call.assigned_to_name ?? "aguardando"}` : "Um toque avisa a equipe"}
          </span>
        </button>
        <button className="big-btn big-btn--bill" onClick={() => setConfirm("PEDIR_CONTA")} disabled={billRequested}>
          <span className="big-btn__title">{billRequested ? "Conta solicitada" : "Pedir a conta"}</span>
          <span className="big-btn__sub">{billRequested ? "O caixa já foi avisado" : `Total até agora ${money(s.total_cents)}`}</span>
        </button>
        {s.orders_enabled && (
          <button className="btn btn--ghost btn--block" onClick={props.goMenu}>
            Ver cardápio e fazer pedido
          </button>
        )}
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
      {s.requests.filter((r) => r.type !== "NOVO_PEDIDO").length === 0 && s.orders.length === 0 ? (
        <p className="empty">Nada por aqui ainda. Seus chamados e pedidos aparecem aqui em tempo real.</p>
      ) : (
        <ul className="timeline">
          {[...s.requests.filter((r) => r.type !== "NOVO_PEDIDO"), ...s.orders]
            .sort((a, b) => b.created_at.localeCompare(a.created_at))
            .slice(0, 12)
            .map((x) =>
              "number" in x ? (
                <li key={x.id} className={`timeline__item st-${x.status}`}>
                  <span>Pedido nº {x.number}</span>
                  <span className="pill">{orderStatusLabel[x.status]}</span>
                  <time>{clock(x.created_at, s.timezone)}</time>
                </li>
              ) : (
                <li key={x.id} className={`timeline__item st-${x.status}`}>
                  <span>{x.type === "PEDIR_CONTA" ? "Conta" : "Chamado"}</span>
                  <span className="pill">{requestStatusLabel[x.status]}</span>
                  <time>{clock(x.created_at, s.timezone)}</time>
                </li>
              ),
            )}
        </ul>
      )}

      <Dialog open={!!confirm} title={confirm === "PEDIR_CONTA" ? "Pedir a conta?" : "Chamar um atendente?"} onClose={() => setConfirm(null)}>
        <p>
          {confirm === "PEDIR_CONTA"
            ? `O caixa receberá o pedido de fechamento da mesa ${s.table_number}. Você ainda pode chamar o atendente depois.`
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
      await api<Order>("/public/orders", {
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
      toast("Pedido recebido pela cozinha.", "ok");
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
          onClick={() => props.onAdd({ key: crypto.randomUUID(), product: p, quantity: qty, optionIds: opts, notes })}
        >
          Adicionar · {money(unit * qty)}
        </button>
      </div>
    </Dialog>
  );
}

function BillTab({ s }: { s: CustomerSession }) {
  const live = s.orders.filter((o) => o.status !== "CANCELADO");
  return (
    <section aria-labelledby="bill-h">
      <h2 id="bill-h" className="c-h2">
        Comanda da mesa {s.table_number}
      </h2>
      {s.orders.length === 0 ? (
        <p className="empty">Nenhum pedido feito pelo celular ainda. Itens pedidos ao atendente aparecem na conta do caixa.</p>
      ) : (
        <ul className="bill">
          {s.orders.map((o) => (
            <li key={o.id} className={`bill__order ${o.status === "CANCELADO" ? "is-cancelled" : ""}`}>
              <div className="bill__head">
                <span>
                  Pedido nº {o.number} · {clock(o.created_at, s.timezone)}
                </span>
                <span className={`pill st-${o.status}`}>{orderStatusLabel[o.status]}</span>
              </div>
              {o.items.map((i) => (
                <div key={i.id} className="bill__item">
                  <span>
                    {i.quantity}× {i.product_name}
                    {i.options.length > 0 && <span className="muted"> + {i.options.map((x) => x.name).join(", ")}</span>}
                  </span>
                  <span>{money(i.line_total_cents)}</span>
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}
      <p className="bill__total">
        Total dos pedidos <strong>{money(s.total_cents)}</strong>
      </p>
      {live.length > 0 && <p className="muted small">Cupons e formas de pagamento são aplicados pelo caixa no fechamento.</p>}
    </section>
  );
}

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function NewsTab({ s, token }: { s: CustomerSession; token: string }) {
  const toast = useToast();
  const [promos, setPromos] = useState<Promotion[] | null>(null);
  const [code, setCode] = useState("");
  const [coupon, setCoupon] = useState<CouponValidation | null>(null);
  const [pushState, setPushState] = useState<"unsupported" | "idle" | "on" | "denied" | "busy">("idle");

  useEffect(() => {
    api<Promotion[]>("/public/promotions", { bearer: token }).then(setPromos).catch(() => setPromos([]));
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
  }, [token, s.push_public_key]);

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
      {promos === null ? (
        <p className="empty">Carregando…</p>
      ) : promos.length === 0 ? (
        <p className="empty">Nenhuma promoção ou evento em vigor agora.</p>
      ) : (
        <ul className="promos">
          {promos.map((p) => (
            <li key={p.id} className={`promo promo--${p.kind.toLowerCase()}`}>
              {p.image_url && <img src={p.image_url} alt="" className="promo__img" loading="lazy" />}
              <strong className="promo__title">{p.title}</strong>
              {p.description && <p>{p.description}</p>}
              {p.conditions && <p className="muted small">{p.conditions}</p>}
              <p className="muted small">Válido até {new Date(p.ends_at).toLocaleString("pt-BR", { timeZone: s.timezone, dateStyle: "short", timeStyle: "short" })}</p>
            </li>
          ))}
        </ul>
      )}

      <form
        className="coupon"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            setCoupon(await api<CouponValidation>("/public/coupons/validate", { bearer: token, body: { code } }));
          } catch (err) {
            toast(errorMessage(err), "error");
          }
        }}
      >
        <label className="field">
          <span className="field__label">Tem um cupom?</span>
          <div className="inline">
            <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={32} placeholder="CÓDIGO" />
            <button className="btn" disabled={code.length < 3}>
              Verificar
            </button>
          </div>
        </label>
        {coupon && (
          <p role="status" className={coupon.valid ? "ok-text" : "form-error"}>
            {coupon.valid
              ? `Cupom válido${coupon.estimated_discount_cents ? `: desconto estimado de ${money(coupon.estimated_discount_cents)}` : ""}. Informe o código ao caixa no fechamento.`
              : coupon.reason}
          </p>
        )}
      </form>

      <div className="push-box">
        <h3 className="c-h3">Notificações</h3>
        {pushState === "unsupported" && (
          <p className="muted small">
            Este navegador não oferece notificações aqui. No iPhone, adicione esta página à tela de início para habilitá-las.
          </p>
        )}
        {pushState === "denied" && <p className="muted small">As notificações estão bloqueadas nas configurações do navegador.</p>}
        {(pushState === "idle" || pushState === "busy") && (
          <>
            <p className="small">Receba avisos de promoções e eventos deste estabelecimento. Você pode cancelar quando quiser.</p>
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
    </section>
  );
}
