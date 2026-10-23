# Perfis e permissões

Fonte única: `backend/app/core/permissions.py`. Toda rota protegida declara a permissão exigida com
`Depends(require(Perm.X))`; o papel vem da sessão no banco, nunca do frontend. A interface esconde o que o
perfil não pode fazer, mas isso é só conveniência — o backend nega de qualquer forma (testado em
`tests/test_permissions.py`).

| Permissão | Atendente | Caixa | Admin | Onde é usada |
|---|:-:|:-:|:-:|---|
| `tables.view` | ✔ | ✔ | ✔ | `GET /tables`, detalhe de sessão aberta |
| `tables.open` | ✔ | ✔ | ✔ | `POST /tables/{id}/open` (com PIN/senha pessoal) |
| `tables.request_close` | ✔ | ✔ | ✔ | `POST /tables/{id}/request-close` |
| `tables.close` | | ✔ | ✔ | fechar conta, cancelar pedido de conta, concluir chamado PEDIR_CONTA |
| `tables.manage` | | | ✔ | cadastrar/renumerar/desativar mesas, QR, novo endereço |
| `requests.view` / `requests.handle` | ✔ | ✔ | ✔ | listar, assumir, iniciar, concluir chamados |
| `requests.prioritize` | | ✔ | ✔ | prioridade manual; agir em chamado de outro funcionário |
| `orders.view` / `orders.update_status` | ✔ | ✔ | ✔ | tela Pedidos |
| `orders.cancel` | | ✔ | ✔ | cancelar pedido (motivo obrigatório) |
| `cash.view` | | ✔ | ✔ | tela Caixa |
| `history.view` | | ✔ | ✔ | histórico e detalhe de sessões encerradas |
| `menu.manage` | | | ✔ | categorias, produtos, adicionais, disponibilidade |
| `promotions.manage` | | | ✔ | promoções e cupons |
| `push.send` | | | ✔ | envio de notificações |
| `users.manage` | | | ✔ | equipe, papéis, senhas, PIN |
| `audit.view` | | | ✔ | auditoria |
| `settings.manage` | | | ✔ | nome, fuso, código de entrada, pedidos pelo celular |

## Regras adicionais
- **Administrador** recebe automaticamente todas as permissões, inclusive futuras (`frozenset(Perm)`).
- **Escalonamento**: só `users.manage` altera papéis. Não é possível rebaixar/desativar a si mesmo nem
  remover o último administrador ativo.
- **Mudança de papel, desativação ou troca de senha** revoga todas as sessões do usuário e fecha seus
  WebSockets — o novo papel vale no próximo login.
- **Chamado assumido** por outra pessoa só pode ser movido por ela ou por quem tem `requests.prioritize`.
- **Isolamento**: todas as consultas filtram pelo `establishment_id` do usuário; IDs de outro
  estabelecimento respondem 404 (sem revelar que existem).
- **Clientes** não têm papel: o token da mesa só permite operações daquela sessão (`/public/*`).
