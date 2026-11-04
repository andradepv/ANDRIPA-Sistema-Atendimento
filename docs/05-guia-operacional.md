# Guia operacional — equipe

O Andripa serve para **avisar a equipe** de que uma mesa precisa de atendimento. Tudo é feito com um toque.

## Atendente
Você **não precisa** abrir o painel.

**Liberar a mesa** — quando o cliente se sentar:
1. Leia o QR Code da mesa (ou aproxime o celular da etiqueta NFC).
2. Toque em **Liberar mesa** (o botão discreto, abaixo de “Cliente”).
3. Digite **seu PIN**. Pronto: a mesa está liberada e o cliente já pode tocar em **Cliente**.

Nunca empreste o PIN: ele identifica você no histórico.

## Painel (caixa, gerente, ou um tablet no balcão)
Entre em `/login` com **usuário e PIN**. Confira o indicador ao lado do nome do bar: **Ao vivo** (verde)
significa que os avisos chegam na hora. Se aparecer **Sem conexão**, o painel reconecta sozinho e, ao
voltar, busca tudo o que aconteceu.

O **Salão** é a única tela de operação:
- À esquerda, **Solicitações** aguardando, das mais antigas para as mais novas, com bipe a cada nova.
  O tempo fica laranja após 2 min e vermelho após 5 min. Cada uma tem **um único botão**:

  | Solicitação | Botão |
  |---|---|
  | Chamou o atendente | **Atendido** |
  | Pedido do cardápio (mostra os itens e observações) | **Repassado à cozinha** |
  | Pediu a conta | **Conta finalizada** (só caixa/admin) — encerra a mesa |

- À direita, as **Mesas**: livres (tracejadas), ocupadas e, em vermelho, as que pediram a conta.
  **Toque numa mesa** para ver os detalhes: quando e por quem foi liberada, tudo o que foi pedido nesse
  atendimento (com o horário de cada pedido e de cada resposta) e os **atendimentos anteriores**.

Ao finalizar a conta, o celular do cliente sai do atendimento na hora e a mesa volta a **Livre**.
O sistema **não cobra** nem registra forma de pagamento: receba como de costume.

## Situações comuns
| Situação | O que fazer |
|---|---|
| Cliente tocou em “Cliente” e viu “mesa ainda não liberada” | Libere a mesa com seu PIN; o cliente toca em “Tentar de novo” |
| Cliente pagou sem pedir a conta pelo celular | Toque na mesa no Salão → **Finalizar conta e liberar a mesa** |
| Duas pessoas tocaram no mesmo botão | Só um toque vale; o outro vê “já foi resolvida” |
| “PIN incorreto” | Confira o PIN; após muitas tentativas erradas o sistema pede para aguardar |
| Painel “Sem conexão” | Verifique o Wi-Fi; nada se perde — tudo está gravado no servidor |
| Esqueceu o PIN | Peça ao administrador para trocar em **Equipe** |

## Fim do turno
Toque em **Sair**. Sair **não** fecha mesas nem apaga solicitações.

## Administrador (resumo)
- **Mesas**: cadastre, imprima o QR Code e use **Copiar para NFC** para gravar a mesma URL na etiqueta.
  **Gerar novo endereço** invalida QR e etiqueta antigos.
- **Cardápio**: categorias, produtos, adicionais; desmarque *Disponível* quando acabar um item.
- **Equipe**: nome, usuário, papel e PIN de cada pessoa (o PIN não pode se repetir). Trocar papel ou PIN
  desconecta a pessoa do painel.
- **Notificações**: publique avisos (promoções, eventos, novidades). Eles aparecem na aba *Novidades* do
  cliente com um botão para **chamar um atendente** — é assim que o cliente sabe mais ou aproveita.
- **Auditoria**: quem liberou/encerrou mesas, tentativas de PIN erradas, alterações no cardápio e na equipe.
