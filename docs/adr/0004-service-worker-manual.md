# ADR-0004 — Service worker escrito à mão

**Decisão.** `public/sw.js` sem gerador (Workbox/vite-plugin-pwa). Regras: nunca cachear `/api/*`; navegação rede-primeiro com fallback para a casca em cache; `/assets/*` (hash no nome) cache-first; atualização controlada (`SKIP_WAITING` só quando a nova versão está instalada).
**Por quê.** Estado operacional (mesa aberta, chamados) não pode vir de cache. A política fica explícita em poucas linhas revisáveis.
**Consequências.** Ao mudar a lista de arquivos da casca, incremente `VERSION` em `sw.js`.
