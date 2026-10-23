# ADR-0003 — Componentes de interface próprios em vez de biblioteca

**Contexto.** O requisito pede uma biblioteca de componentes acessíveis e responsivos "escolhida e documentada".
**Decisão.** Usar HTML semântico com um pequeno conjunto próprio (`src/components/ui.tsx`): `<dialog>` nativo (foco preso e Esc pelo navegador), região `aria-live` para avisos, campos com `<label>`, foco visível, alvos de toque ≥ 44 px, `prefers-reduced-motion` e tema escuro.
**Por quê.** O cliente abre a página em rede móvel ruim, sem instalar nada: cada KB conta. As telas usam poucos padrões (botão, campo, diálogo, lista, tabela). Uma biblioteca completa traria peso e dependências sem ganho proporcional.
**Consequências.** Manter os componentes é responsabilidade do projeto. Se a interface administrativa crescer muito (tabelas com filtro avançado, datas complexas), avaliar React Aria Components.
