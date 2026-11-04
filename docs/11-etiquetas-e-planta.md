# Etiquetas NFC e planta do salão

Duas funções só do **administrador**, pensadas para tirar o erro humano da implantação e acompanhar mudanças
no salão.

## 1. Criar mesa e gravar a etiqueta num fluxo só
Em **Mesas**, o administrador informa número, nome e confirma com o **PIN ou senha**, e toca em
*Criar mesa e gravar etiqueta*. Numa única transação (`POST /admin/tables/provision`) o sistema:

1. cria a mesa e o endereço único dela (`/m/<código>`), que é também o do **QR Code** (`/tables/{id}/qr.svg`);
2. coloca a mesa na **primeira célula livre da planta ativa**;
3. abre uma gravação de etiqueta (`PENDENTE`) cuja **URL vem do servidor** — ninguém digita o endereço.

O assistente (Chrome para Android, NFC ligado, HTTPS) então:

| Passo | O que acontece | Estado |
|---|---|---|
| Gravar | O celular grava a URL (`overwrite`) | `GRAVANDO` |
| Conferir | O celular lê a etiqueta de volta e envia UID + URL lida. O servidor compara com a URL esperada, com o endereço atual da mesa e verifica que o chip não serve a outra mesa | `GRAVADA` ou `FALHA` |
| Travar (opcional) | Pede de novo o PIN/senha (`authorize-lock`, vale 2 min); o celular confere que é o mesmo chip e o torna somente leitura | `TRAVADA` |

Se algo falha (URL lida diferente, chip já usado em outra mesa, tempo esgotado, chip errado na hora de
travar), a falha é registrada e mostrada a todos; basta *Tentar de novo*, sem digitar nada. **Substituir** uma
etiqueta já gravada exige confirmação, a mesa precisa estar **livre** e o endereço é **trocado** (a etiqueta e
o QR antigos deixam de funcionar).

### Ver o que está sendo gravado
O painel *Gravando agora* (em Mesas) e a coluna *Etiqueta NFC* acompanham, **em tempo real** (evento
`tag.updated`), qual mesa está em gravação, por quem e há quanto tempo, inclusive em outros aparelhos. Cada
passo vai para a auditoria (`tag.provision`, `tag.start`, `tag.written`, `tag.write_failed`,
`tag.lock_authorized`, `tag.locked`).

### O que protege contra regravação
Web NFC não define senha em NTAG213/215. A proteção possível pelo navegador é o **travamento permanente**
(irreversível). Ele é opcional e exige senha do administrador. Ver limitações em `09-limitacoes.md`.

## 2. Planta do salão (templates)
Cada **planta** guarda a posição (célula x, y numa grade de 24 × 16) de cada mesa. Há uma planta **ativa**
por estabelecimento; todos os painéis do Salão mostram essa planta e se atualizam na hora
(`layout.updated`). Só o administrador, em **Planta**:

- arrasta as mesas (ou toca na mesa e depois na célula; arrastar sobre outra mesa troca as duas);
- cria **modelos** (ex.: *Evento*, *Varanda aberta*), com cópia da planta atual;
- **ativa** um modelo: o salão de toda a equipe muda;
- renomeia e exclui modelos (a ativa não pode ser excluída).

Mesas sem posição na planta ativa aparecem numa lista *Sem posição*, então nenhuma some quando o salão é
rearranjado. Mesa nova entra automaticamente na primeira célula livre. Salvar usa a **versão** da planta:
se outro administrador alterou antes, o servidor responde `409 stale_version` e nada é sobrescrito.
A migração `0002` cria a planta *Padrão* para estabelecimentos já existentes.

## Decisões
- O **servidor é a fonte da URL** e da conferência; o navegador só grava, lê e (se autorizado) trava.
- Estado da gravação em tabela própria (`table_tags`) com **índices únicos parciais**: uma etiqueta viva por
  mesa e um chip em uma mesa só. Eventos pelo mesmo **outbox** dos demais (ver ADR-0005).
- Permissões novas `tables.provision` e `layouts.manage` (ver `02-permissoes.md`).

## Testes
`backend/tests/test_tags_layouts.py` (15 testes: permissões, atomicidade, ciclo completo, URL divergente, mesmo
chip em duas mesas, substituição, expiração da autorização de travar, isolamento entre estabelecimentos,
criação concorrente da planta, ativações simultâneas, validações e versão obsoleta) e a jornada e2e
`frontend/e2e/etiquetas-planta.spec.ts`, com leitor NFC simulado.
