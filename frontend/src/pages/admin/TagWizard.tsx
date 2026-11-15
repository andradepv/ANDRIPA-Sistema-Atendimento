// Assistente de gravação de etiqueta NFC: o servidor entrega a URL, o celular grava, lê de volta e o servidor confere.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage } from "../../api/http";
import type { Table, Tag, TagStatus } from "../../api/types";
import { Dialog, Field, useNow, useToast } from "../../components/ui";
import { elapsed, tagStatusLabel } from "../../lib/format";
import { lockTag, NfcError, nfcLockSupported, nfcSupported, readTag, withTimeout, writeUrl } from "../../lib/nfc";
import { useStaff } from "../staff/StaffData";

export const qrUrl = (tableId: string) => `/api/v1/tables/${tableId}/qr.svg`;

const TONE: Record<TagStatus, string> = {
  PENDENTE: "tag--wait",
  GRAVANDO: "tag--busy",
  GRAVADA: "tag--ok",
  TRAVADA: "tag--ok",
  FALHA: "tag--fail",
  SUBSTITUIDA: "tag--wait",
};

export function TagBadge({ status }: { status: TagStatus | null | undefined }) {
  if (!status) return <span className="tag tag--none">Sem etiqueta</span>;
  return <span className={`tag ${TONE[status]}`}>{tagStatusLabel[status]}</span>;
}

/** Etiqueta mais recente de uma mesa: junta o que veio do REST com o que chegou em tempo real. */
export function useTagOf(table: Pick<Table, "id" | "tag">): { status: TagStatus | null; live: Tag | null } {
  const { tags } = useStaff();
  const live = tags.find((g) => g.table_id === table.id && g.status !== "SUBSTITUIDA") ?? null;
  return { status: live?.status ?? table.tag?.status ?? null, live };
}

// ------------------------------------------------------------------ "gravando agora" (tempo real)
export function WritingNow({ onOpen }: { onOpen: (t: Tag) => void }) {
  const { tags } = useStaff();
  const now = useNow(5000);
  const active = tags.filter(
    (g) => (g.status === "PENDENTE" || g.status === "GRAVANDO") && now - new Date(g.updated_at).getTime() < 30 * 60_000,
  );
  return (
    <section className="writing-now" aria-live="polite" aria-label="Gravações em andamento">
      <h2 className="s-h2">Gravando agora</h2>
      {active.length === 0 ? (
        <p className="muted">Nenhuma etiqueta em gravação neste momento.</p>
      ) : (
        <ul className="stack">
          {active.map((g) => (
            <li key={g.id} className={`writing-now__item ${g.status === "GRAVANDO" ? "is-busy" : ""}`}>
              <strong>Mesa {g.table_number}</strong>
              {g.table_name && <span className="muted"> {g.table_name}</span>}
              <TagBadge status={g.status} />
              <span className="muted small">
                por {g.started_by_name} · {elapsed(g.updated_at, now)}
              </span>
              <button className="btn btn--small" onClick={() => onOpen(g)}>
                Abrir assistente
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ iniciar gravação de mesa existente
export function StartTagDialog({
  table,
  onClose,
  onStarted,
}: {
  table: Table | null;
  onClose: () => void;
  onStarted: (tag: Tag) => void;
}) {
  const toast = useToast();
  const [secret, setSecret] = useState("");
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const hasTag = table?.tag && (table.tag.status === "GRAVADA" || table.tag.status === "TRAVADA");
  useEffect(() => {
    setSecret("");
    setReplace(false);
  }, [table?.id]);
  return (
    <Dialog open={!!table} title={table ? `Gravar etiqueta da mesa ${table.number}` : ""} onClose={onClose}>
      {table && (
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              const tag = await api<Tag>(`/admin/tables/${table.id}/tag`, { body: { confirm_secret: secret, replace: !!hasTag && replace } });
              onStarted(tag);
            } catch (err) {
              toast(errorMessage(err), "error");
            } finally {
              setBusy(false);
            }
          }}
        >
          <p className="muted">O endereço da mesa é preenchido pelo sistema. Você só precisa encostar a etiqueta no celular.</p>
          {hasTag && (
            <label className="check">
              <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
              <span>
                Esta mesa já tem etiqueta {table.tag?.status === "TRAVADA" ? "travada" : "gravada"}. Substituir gera um <strong>novo endereço</strong>:
                a etiqueta e o QR Code antigos deixam de funcionar. A mesa precisa estar livre.
              </span>
            </label>
          )}
          <Field label="Seu PIN ou senha" hint="Confirma que é você, administrador, quem está gravando.">
            <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" required minLength={4} />
          </Field>
          <button className="btn btn--primary" disabled={busy || secret.length < 4 || (!!hasTag && !replace)}>
            {busy ? "Preparando…" : "Continuar"}
          </button>
        </form>
      )}
    </Dialog>
  );
}

// ------------------------------------------------------------------ assistente
export function TagWizard({ initial, onClose }: { initial: Tag | null; onClose: () => void }) {
  const toast = useToast();
  const { tags, resync } = useStaff();
  const [current, setCurrent] = useState<Tag | null>(initial);
  const [phase, setPhase] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockSecret, setLockSecret] = useState("");
  const cancel = useRef<(() => void) | null>(null);

  useEffect(() => {
    setCurrent(initial);
    setPhase(null);
    setError(null);
    setLockSecret("");
  }, [initial?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // A cópia em tempo real vence quando é mais nova (outro administrador pode ter mexido).
  const live = current ? tags.find((g) => g.id === current.id) : undefined;
  const tag = live && current && live.version > current.version ? live : current;
  const busy = phase !== null;

  const run = async (fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(errorMessage(e));
      } else if (e instanceof NfcError) {
        setError(e.message);
        if (tag && e.code !== "wrong_tag") {
          // Avisa o servidor (e os outros painéis) de que esta tentativa falhou.
          await api<Tag>(`/admin/tags/${tag.id}/failed`, { body: { reason: e.message.slice(0, 270) } })
            .then(setCurrent)
            .catch(() => undefined);
        }
      } else {
        setError("Algo deu errado. Tente novamente.");
      }
      void resync();
    } finally {
      cancel.current = null;
      setPhase(null);
    }
  };

  const write = () =>
    run(async () => {
      if (!tag) return;
      setPhase("Aproxime a etiqueta da parte de trás do celular e mantenha-a encostada…");
      setCurrent(await api<Tag>(`/admin/tags/${tag.id}/writing`, { body: {} }));
      const w = withTimeout(60_000, (s) => writeUrl(tag.url, s));
      cancel.current = w.cancel;
      await w.promise;
      setPhase("Gravado. Afaste e aproxime a etiqueta de novo para o sistema conferir a leitura…");
      const r = withTimeout(60_000, (s) => readTag(s));
      cancel.current = r.cancel;
      const seen = await r.promise;
      if (!seen.url) throw new NfcError("io", "Não foi possível ler o endereço de volta da etiqueta. Grave novamente.");
      setPhase("Conferindo com o servidor…");
      setCurrent(await api<Tag>(`/admin/tags/${tag.id}/written`, { body: { uid: seen.uid, read_url: seen.url } }));
      toast(`Etiqueta da mesa ${tag.table_number} gravada e conferida.`, "ok");
    });

  const lock = () =>
    run(async () => {
      if (!tag?.uid) return;
      setPhase("Confirmando sua senha…");
      setCurrent(await api<Tag>(`/admin/tags/${tag.id}/authorize-lock`, { body: { confirm_secret: lockSecret } }));
      setLockSecret("");
      setPhase("Aproxime a etiqueta que acabou de gravar para travá-la…");
      const l = withTimeout(60_000, (s) => lockTag(tag.uid ?? "", s));
      cancel.current = l.cancel;
      await l.promise;
      setCurrent(await api<Tag>(`/admin/tags/${tag.id}/locked`, { body: {} }));
      toast(`Etiqueta da mesa ${tag.table_number} travada.`, "ok");
    });

  const close = () => {
    cancel.current?.();
    onClose();
  };

  const written = tag?.status === "GRAVADA" || tag?.status === "TRAVADA";
  return (
    <Dialog open={!!initial} title={tag ? `Mesa ${tag.table_number}${tag.table_name ? ` · ${tag.table_name}` : ""}` : ""} onClose={close} wide>
      {tag && (
        <div className="wizard">
          <ol className="steps">
            <li className="step is-done">
              <h3>1 · Mesa e endereço criados</h3>
              <p className="muted small">O sistema gerou o endereço e o QR Code desta mesa. Ninguém precisa digitar nada.</p>
              <div className="wizard__addr">
                <code className="url">{tag.url}</code>
                <div className="qr-print">
                  <img src={qrUrl(tag.table_id)} alt={`QR Code da mesa ${tag.table_number}`} width={132} height={132} />
                  <button type="button" className="btn btn--small btn--ghost no-print" onClick={() => window.print()}>
                    Imprimir QR
                  </button>
                </div>
              </div>
            </li>

            <li className={`step ${written ? "is-done" : "is-current"}`}>
              <h3>
                2 · Gravar a etiqueta NFC <TagBadge status={tag.status} />
              </h3>
              {tag.status === "GRAVANDO" && !busy && (
                <p className="muted small">Gravando agora em outro aparelho: {tag.started_by_name}.</p>
              )}
              {!nfcSupported() && !written && (
                <p className="notice notice--warn">
                  Este navegador não grava NFC. Abra este painel no <strong>Chrome do Android</strong> (com NFC ligado) para gravar. O endereço e o QR Code
                  acima já funcionam sem a etiqueta.
                </p>
              )}
              {tag.status === "FALHA" && tag.error && <p className="notice notice--error">{tag.error}</p>}
              {written ? (
                <p>
                  Etiqueta <code>{tag.uid}</code> gravada e conferida: o que foi lido de volta é exatamente o endereço da mesa.
                </p>
              ) : (
                <div className="inline">
                  <button className="btn btn--primary" onClick={() => void write()} disabled={busy || !nfcSupported()}>
                    {tag.status === "FALHA" ? "Tentar de novo" : "Gravar etiqueta agora"}
                  </button>
                  {busy && (
                    <button className="btn btn--ghost" onClick={() => cancel.current?.()}>
                      Cancelar
                    </button>
                  )}
                </div>
              )}
            </li>

            <li className={`step ${tag.status === "TRAVADA" ? "is-done" : tag.status === "GRAVADA" ? "is-current" : "is-todo"}`}>
              <h3>3 · Travar a etiqueta (opcional)</h3>
              {tag.status === "TRAVADA" ? (
                <p>Etiqueta travada: ninguém consegue regravá-la, nem pelo celular de um administrador.</p>
              ) : (
                <>
                  <p className="muted small">
                    Travar torna a etiqueta somente leitura <strong>para sempre</strong>. Impede que alguém regrave o endereço com um aplicativo qualquer. Se precisar mudar,
                    troque a etiqueta (o sistema gera um novo endereço).
                  </p>
                  {tag.status === "GRAVADA" && !nfcLockSupported() && (
                    <p className="notice notice--warn">Este navegador não consegue travar etiquetas. A etiqueta continua funcionando, mas pode ser regravada.</p>
                  )}
                  {tag.status === "GRAVADA" && nfcLockSupported() && (
                    <form
                      className="inline"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void lock();
                      }}
                    >
                      <Field label="Seu PIN ou senha de administrador">
                        <input type="password" value={lockSecret} onChange={(e) => setLockSecret(e.target.value)} autoComplete="off" minLength={4} required />
                      </Field>
                      <button className="btn btn--danger" disabled={busy || lockSecret.length < 4}>
                        Travar para sempre
                      </button>
                    </form>
                  )}
                </>
              )}
            </li>
          </ol>

          {phase && (
            <p className="notice notice--busy" role="status">
              {phase}
            </p>
          )}
          {error && (
            <p className="notice notice--error" role="alert">
              {error}
            </p>
          )}
          <div className="inline">
            <button className="btn" onClick={close}>
              {written ? "Concluir" : "Fechar"}
            </button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
