// Editor das plantas (templates) do salão. Só administradores: rearranjar mesas, criar variações e ativar uma planta.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, errorMessage } from "../../api/http";
import type { Layout, LayoutItem, Table } from "../../api/types";
import { Dialog, Empty, Field, useToast } from "../../components/ui";
import { tableStatusLabel } from "../../lib/format";
import { useStaff } from "../staff/StaffData";

type Pos = { x: number; y: number };
type Draft = Record<string, Pos>; // table_id -> célula

const toDraft = (items: LayoutItem[]): Draft => Object.fromEntries(items.map((i) => [i.table_id, { x: i.x, y: i.y }]));
const sameDraft = (a: Draft, b: Draft) => {
  const ka = Object.keys(a);
  return ka.length === Object.keys(b).length && ka.every((k) => b[k] && a[k]?.x === b[k]?.x && a[k]?.y === b[k]?.y);
};

export function AdminFloor() {
  const toast = useToast();
  const { tables, layout: activeLive } = useStaff();
  const [layouts, setLayouts] = useState<Layout[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [picked, setPicked] = useState<string | null>(null);
  const [extra, setExtra] = useState({ cols: 12, rows: 8 });
  const [newOpen, setNewOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [copy, setCopy] = useState(true);
  const [busy, setBusy] = useState(false);

  const selected = layouts.find((l) => l.id === selectedId) ?? null;
  const saved = useMemo(() => (selected ? toDraft(selected.items) : {}), [selected]);
  const dirty = !!selected && !sameDraft(draft, saved);
  const byId = useMemo(() => new Map(tables.map((t) => [t.id, t])), [tables]);

  const load = useCallback(
    async (keep?: string | null) => {
      const list = await api<Layout[]>("/admin/layouts");
      setLayouts(list);
      setSelectedId((cur) => {
        const want = keep ?? cur;
        return list.find((l) => l.id === want)?.id ?? list.find((l) => l.is_active)?.id ?? list[0]?.id ?? null;
      });
    },
    [],
  );
  useEffect(() => {
    load().catch((e) => toast(errorMessage(e), "error"));
  }, [load, toast]);

  // Quando a planta ativa muda por outro administrador e eu não estou no meio de uma edição, recarrega.
  useEffect(() => {
    if (activeLive && !dirty) void load().catch(() => undefined);
  }, [activeLive?.id, activeLive?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  // Trocar de planta (ou recarregar) reinicia o rascunho e dimensiona a grade.
  useEffect(() => {
    if (!selected) return;
    setDraft(toDraft(selected.items));
    setPicked(null);
    const maxX = Math.max(-1, ...selected.items.map((i) => i.x));
    const maxY = Math.max(-1, ...selected.items.map((i) => i.y));
    setExtra({ cols: Math.min(selected.cols, Math.max(12, maxX + 3)), rows: Math.min(selected.rows, Math.max(8, maxY + 3)) });
  }, [selected?.id, selected?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeTables = tables.filter((t) => t.active);
  const unplaced = activeTables.filter((t) => !draft[t.id]);
  const occupant = (x: number, y: number) => Object.entries(draft).find(([, p]) => p.x === x && p.y === y)?.[0] ?? null;

  /** Coloca (ou move) uma mesa numa célula; se houver outra mesa lá, as duas trocam de lugar. */
  const place = (id: string, x: number, y: number) => {
    setDraft((cur) => {
      const next = { ...cur };
      const from = cur[id];
      const other = Object.entries(cur).find(([k, p]) => k !== id && p.x === x && p.y === y)?.[0];
      if (other) {
        if (from) next[other] = from;
        else delete next[other];
      }
      next[id] = { x, y };
      return next;
    });
    setPicked(null);
  };
  const unplace = (id: string) => {
    setDraft((cur) => {
      const next = { ...cur };
      delete next[id];
      return next;
    });
    setPicked(null);
  };

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toast(errorMessage(e), "error");
      if (e instanceof ApiError && e.code === "stale_version") await load().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    act(async () => {
      if (!selected) return;
      const items = Object.entries(draft).map(([table_id, p]) => ({ table_id, x: p.x, y: p.y }));
      await api(`/admin/layouts/${selected.id}/items`, { method: "PUT", body: { version: selected.version, items } });
      await load(selected.id);
      toast("Posições salvas.", "ok");
    });

  const activate = () =>
    act(async () => {
      if (!selected) return;
      await api(`/admin/layouts/${selected.id}/activate`, { body: {} });
      await load(selected.id);
      toast(`“${selected.name}” agora é a planta do salão, para toda a equipe.`, "ok");
    });

  const create = () =>
    act(async () => {
      const made = await api<Layout>("/admin/layouts", { body: { name: newName, copy_from: copy && selected ? selected.id : null } });
      setNewOpen(false);
      setNewName("");
      await load(made.id);
    });

  const rename = () =>
    act(async () => {
      if (!selected) return;
      const name = prompt("Novo nome da planta", selected.name)?.trim();
      if (!name || name === selected.name) return;
      await api(`/admin/layouts/${selected.id}`, { method: "PATCH", body: { name } });
      await load(selected.id);
    });

  const remove = () =>
    act(async () => {
      if (!selected || !confirm(`Excluir a planta “${selected.name}”? As mesas não são afetadas.`)) return;
      await api(`/admin/layouts/${selected.id}`, { method: "DELETE" });
      setSelectedId(null);
      await load();
    });

  if (!selected) return <Empty>Carregando plantas…</Empty>;

  const cells: { x: number; y: number }[] = [];
  for (let y = 0; y < extra.rows; y++) for (let x = 0; x < extra.cols; x++) cells.push({ x, y });

  return (
    <section className="stack">
      <h1 className="s-h1">Planta do salão</h1>
      <p className="muted">
        Arraste as mesas para onde elas estão no salão (ou toque na mesa e depois na posição). Cada planta é um modelo: crie uma para o evento, a
        varanda aberta ou o dia de movimento, e ative quando precisar. A planta ativa aparece para toda a equipe, na hora.
      </p>

      <div className="inline floor-bar">
        <Field label="Planta">
          <select
            value={selected.id}
            onChange={(e) => {
              if (dirty && !confirm("Descartar as mudanças não salvas desta planta?")) return;
              setSelectedId(e.target.value);
            }}
          >
            {layouts.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
                {l.is_active ? " (ativa)" : ""}
              </option>
            ))}
          </select>
        </Field>
        <button className="btn btn--primary" onClick={() => void save()} disabled={busy || !dirty}>
          Salvar posições
        </button>
        <button className="btn btn--ghost" onClick={() => setDraft(saved)} disabled={!dirty}>
          Descartar
        </button>
        <button className="btn" onClick={() => void activate()} disabled={busy || selected.is_active || dirty} title={dirty ? "Salve antes de ativar" : ""}>
          {selected.is_active ? "Planta ativa" : "Usar esta planta"}
        </button>
        <button className="btn btn--ghost" onClick={() => setNewOpen(true)}>
          Novo modelo
        </button>
        <button className="btn btn--ghost" onClick={() => void rename()} disabled={busy}>
          Renomear
        </button>
        <button className="btn btn--ghost" onClick={() => void remove()} disabled={busy || selected.is_active}>
          Excluir
        </button>
      </div>
      {dirty && <p className="notice notice--warn">Há mudanças não salvas nesta planta.</p>}

      <div className="floor-wrap">
        <div
          className="floor-grid"
          style={{ gridTemplateColumns: `repeat(${extra.cols}, var(--cell))`, gridTemplateRows: `repeat(${extra.rows}, var(--cell))` }}
          role="grid"
          aria-label="Planta do salão"
        >
          {cells.map(({ x, y }) => {
            const id = occupant(x, y);
            const t = id ? byId.get(id) : undefined;
            return (
              <div
                key={`${x}-${y}`}
                role="gridcell"
                className={`floor-cell ${id ? "has-table" : ""} ${picked && !id ? "is-target" : ""}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const dragged = e.dataTransfer.getData("text/plain");
                  if (dragged) place(dragged, x, y);
                }}
                onClick={() => {
                  if (picked) place(picked, x, y);
                }}
                style={{ gridColumn: x + 1, gridRow: y + 1 }}
              >
                {t && (
                  <button
                    className={`floor-tile tt-${t.status} ${picked === t.id ? "is-picked" : ""}`}
                    draggable
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", t.id)}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (picked && picked !== t.id) place(picked, x, y);
                      else setPicked(picked === t.id ? null : t.id);
                    }}
                    title={`Mesa ${t.number}${t.name ? ` · ${t.name}` : ""} · ${tableStatusLabel[t.status]}`}
                  >
                    <strong>{t.number}</strong>
                    {t.name && <span>{t.name}</span>}
                  </button>
                )}
              </div>
            );
          })}
        </div>
        <div className="inline floor-size">
          <button className="btn btn--small btn--ghost" disabled={extra.cols >= selected.cols} onClick={() => setExtra((e) => ({ ...e, cols: Math.min(selected.cols, e.cols + 2) }))}>
            + colunas
          </button>
          <button className="btn btn--small btn--ghost" disabled={extra.rows >= selected.rows} onClick={() => setExtra((e) => ({ ...e, rows: Math.min(selected.rows, e.rows + 2) }))}>
            + linhas
          </button>
          {picked && (
            <button className="btn btn--small btn--ghost" onClick={() => unplace(picked)}>
              Tirar a mesa {byId.get(picked)?.number} da planta
            </button>
          )}
        </div>
      </div>

      <section
        className="floor-tray"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const dragged = e.dataTransfer.getData("text/plain");
          if (dragged) unplace(dragged);
        }}
      >
        <h2 className="s-h2">Sem posição nesta planta ({unplaced.length})</h2>
        {unplaced.length === 0 ? (
          <p className="muted small">Todas as mesas estão na planta. Arraste uma mesa até aqui para tirá-la.</p>
        ) : (
          <ul className="floor-tray__list">
            {unplaced.map((t) => (
              <li key={t.id}>
                <TrayTile t={t} picked={picked === t.id} onPick={() => setPicked(picked === t.id ? null : t.id)} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <Dialog open={newOpen} title="Novo modelo de planta" onClose={() => setNewOpen(false)}>
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <Field label="Nome" hint="Ex.: Evento, Varanda aberta, Sexta à noite">
            <input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={80} required autoFocus />
          </Field>
          <label className="check">
            <input type="checkbox" checked={copy} onChange={(e) => setCopy(e.target.checked)} />
            <span>Começar com as posições de “{selected.name}”</span>
          </label>
          <button className="btn btn--primary" disabled={busy || !newName.trim()}>
            Criar modelo
          </button>
        </form>
      </Dialog>
    </section>
  );
}

function TrayTile({ t, picked, onPick }: { t: Table; picked: boolean; onPick: () => void }) {
  return (
    <button
      className={`floor-tile floor-tile--tray tt-${t.status} ${picked ? "is-picked" : ""}`}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", t.id)}
      onClick={onPick}
    >
      <strong>{t.number}</strong>
      {t.name && <span>{t.name}</span>}
    </button>
  );
}
