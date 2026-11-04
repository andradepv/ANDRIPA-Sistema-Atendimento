// Página que abre ao ler o QR Code / NFC da mesa. Serve ao cliente e ao atendente:
//  · “Cliente” (destaque): entra no atendimento — ou avisa que a mesa ainda não foi liberada.
//  · “Liberar mesa” (discreto): o atendente digita o PIN e pronto.
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "../../api/http";
import type { PublicTable } from "../../api/types";
import { Dialog } from "../../components/ui";
import { navigate } from "../../lib/router";
import { NotOpen, Splash } from "./CustomerApp";

export function TableLanding({ code }: { code: string }) {
  const [table, setTable] = useState<PublicTable | null>(null);
  const [error, setError] = useState<"notfound" | "offline" | null>(null);
  const [notOpen, setNotOpen] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);
  const [justOpened, setJustOpened] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const t = await api<PublicTable>(`/public/tables/${code}`);
      setTable(t);
      setError(null);
      document.title = `Mesa ${t.table_number} · ${t.establishment_name}`;
      return t;
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? "notfound" : "offline");
      return null;
    }
  }, [code]);

  useEffect(() => {
    void load();
  }, [load]);

  const goCustomer = async () => {
    setBusy(true);
    const t = await load(); // confere na hora: a mesa pode ter sido liberada agora há pouco
    setBusy(false);
    if (!t) return;
    if (t.available) navigate(`/m/${code}/cliente`);
    else setNotOpen(true);
  };

  if (error === "notfound")
    return <Splash title="Mesa não encontrada" text="Leia o QR Code de novo ou aproxime o celular da etiqueta da mesa." />;
  if (error === "offline")
    return <Splash title="Sem conexão" text="Não foi possível falar com o servidor." action={{ label: "Tentar de novo", onClick: () => void load() }} />;
  if (!table) return <Splash text="Abrindo a mesa…" />;
  if (notOpen) return <NotOpen table={table} onBack={() => setNotOpen(false)} onRetry={() => void goCustomer()} />;

  return (
    <main className="c-shell c-center landing">
      <div className="tile-band" aria-hidden="true" />
      <p className="c-est">{table.establishment_name}</p>
      <h1 className="c-title">
        Mesa {table.table_number}
        {table.table_name ? <span className="c-table__name"> {table.table_name}</span> : null}
      </h1>
      {justOpened && (
        <p className="ok-text" role="status">
          Mesa liberada! Os clientes já podem usar o atendimento.
        </p>
      )}
      <button className="big-btn big-btn--call landing__main" onClick={() => void goCustomer()} disabled={busy}>
        <span className="big-btn__title">Cliente</span>
        <span className="big-btn__sub">Chamar atendente, ver o cardápio e pedir a conta</span>
      </button>
      <button className="btn btn--ghost landing__staff" onClick={() => setPinOpen(true)}>
        Liberar mesa
      </button>
      <PinDialog
        open={pinOpen}
        code={code}
        table={table}
        onClose={() => setPinOpen(false)}
        onOpened={(t) => {
          setTable(t);
          setPinOpen(false);
          setJustOpened(true);
        }}
      />
    </main>
  );
}

function PinDialog(props: {
  open: boolean;
  code: string;
  table: PublicTable;
  onClose: () => void;
  onOpened: (t: PublicTable) => void;
}) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (props.open) {
      setPin("");
      setError(null);
    }
  }, [props.open]);

  if (props.table.available)
    return (
      <Dialog open={props.open} title={`Mesa ${props.table.table_number}`} onClose={props.onClose}>
        <p>Esta mesa já está liberada. Os clientes podem tocar em “Cliente” para usar o atendimento.</p>
        <div className="dialog__actions">
          <button className="btn btn--primary" onClick={props.onClose}>
            Entendi
          </button>
        </div>
      </Dialog>
    );

  return (
    <Dialog open={props.open} title={`Liberar a mesa ${props.table.table_number}`} onClose={props.onClose}>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            props.onOpened(await api<PublicTable>(`/public/tables/${props.code}/open`, { body: { pin } }));
          } catch (err) {
            setError(errorMessage(err));
            setPin("");
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor="pin">PIN do atendente</label>
        <input
          id="pin"
          className="join__code"
          type="password"
          inputMode="numeric"
          autoComplete="off"
          pattern="\d{4,8}"
          maxLength={8}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
          aria-invalid={!!error}
          aria-describedby={error ? "pin-err" : undefined}
          data-autofocus
          required
        />
        {error && (
          <p id="pin-err" className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="btn btn--primary btn--block" disabled={busy || pin.length < 4}>
          {busy ? "Liberando…" : "Liberar mesa"}
        </button>
      </form>
    </Dialog>
  );
}
