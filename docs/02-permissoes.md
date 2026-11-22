# Perfis e permissões

Fonte única: `backend/app/core/permissions.py`. Toda rota protegida declara a permissão exigida com
`Depends(require(Perm.X))`; o papel vem da sessão no banco, nunca do frontend. A interface esconde o que o
perfil não pode fazer, mas isso é só conveniência — o backend nega de qualquer forma (testado em
`tests/test_permissions.py`).

## Como cada pessoa entra
- **Painel** (`/login`): **usuário + PIN**. Não há e-mail nem senha.
- **Liberar mesa** (página da mesa, `/m/<código>`): só o **PIN** de qualquer pessoa ativa da equipe.
  O atendente não precisa abrir o painel: lê o QR Code, toca em “Liberar mesa”, digita o PIN e pronto.
- Por isso o **PIN é único por estabelecimento** (o sistema recusa um PIN já usado por outra pessoa).

| Permissão | Atendente | Caixa | Admin | Onde é usada |
|---|:-:|:-:|:-:|---|
| `tables.view` | ✔ | ✔ | ✔ | Salão: mesas e solicitações aguardando; detalhe do atendimento atual |
| `tables.open` | ✔ | ✔ | ✔ | `POST /tables/{id}/open` (pelo painel) |
| `requests.handle` | ✔ | ✔ | ✔ | “Atendido” e “Repassado à cozinha” (`POST /service-requests/{id}/complete`) |
| `tables.close` | | ✔ | ✔ | “Conta finalizada”: encerra a mesa (`POST /tables/{id}/close` ou completar `PEDIR_CONTA`) |
| `history.view` | | ✔ | ✔ | atendimentos anteriores de cada mesa |
| `tables.manage` | | | ✔ | cadastrar/renumerar/desativar mesas, QR, novo endereço |
| `menu.manage` | | | ✔ | categorias, produtos, adicionais, disponibilidade |
| `notices.manage` | | | ✔ | avisos aos clientes (e push opcional) |
| `users.manage` | | | ✔ | equipe, papéis, PIN |
| `audit.view` | | | ✔ | auditoria |
| `settings.manage` | | | ✔ | nome, fuso, pedidos pelo celular |
| `tables.provision` | | | ✔ | criar mesa + gravar/travar etiqueta NFC (`/admin/tables/provision`, `/admin/tags/*`) |
| `layouts.manage` | | | ✔ | criar, editar, ativar e excluir plantas do salão (`/admin/layouts/*`) |

## Regras adicionais
- **Plantas e etiquetas**: qualquer funcionário *vê* a planta ativa (`GET /layouts/active`, exige `tables.view`);
  só o administrador altera plantas e grava etiquetas. Criar a mesa com etiqueta, substituir e travar exigem
  PIN ou senha do administrador (mesma confirmação individual da abertura de mesa).
- **Administrador** recebe automaticamente todas as permissões, inclusive futuras (`frozenset(Perm)`).
- **Escalonamento**: só `users.manage` altera papéis. Não é possível rebaixar/desativar a si mesmo nem
  remover o último administrador ativo.
- **Mudança de papel, desativação ou troca de PIN** revoga as sessões do usuário e fecha seus
  WebSockets — o novo papel vale no próximo login.
- **Sem “quem assumiu”**: qualquer pessoa da equipe resolve uma solicitação; o sistema registra quem e quando.
  Se duas pessoas tocarem ao mesmo tempo, só uma registra (a outra recebe `409 already_done`).
- **Força bruta de PIN**: login limitado por usuário e por IP; liberação de mesa limitada por IP, por mesa e por
  estabelecimento; tentativas erradas ficam na auditoria (`table.open_denied`).
- **Isolamento**: todas as consultas filtram pelo `establishment_id` do usuário; IDs de outro
  estabelecimento respondem 404 (sem revelar que existem). O PIN de um bar não libera mesa de outro.
- **Clientes** não têm papel: o token da mesa só permite operações daquela sessão (`/public/*`).
