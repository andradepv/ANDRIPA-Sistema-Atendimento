/* Jornada completa no navegador (Cenários A–F e I), com os dados de `python -m app.cli seed-dev`:
 * página da mesa → “Liberar mesa” com o PIN do atendente → cliente chama o atendente e faz pedido →
 * painel recebe em tempo real e resolve com um toque → cliente pede a conta → caixa finaliza →
 * celular do cliente sai do atendimento.
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

const SHOTS = "test-results/screens";
const PINS: Record<string, string> = { admin: "1111", caixa: "2222", atendente: "3333" };

// Uma sessão por funcionário durante toda a execução (o login tem rate limit de verdade).
const sessions = new Map<string, Page>();

async function login(browser: Browser, username: string): Promise<Page> {
  const cached = sessions.get(username);
  if (cached && !cached.isClosed()) {
    await cached.goto("/painel");
    await expect(cached.getByText("Ao vivo")).toBeVisible();
    return cached;
  }
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const page = await ctx.newPage();
  await page.goto("/login");
  await page.getByLabel("Usuário").fill(username);
  await page.getByLabel("PIN").fill(PINS[username]!);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Ao vivo")).toBeVisible();
  sessions.set(username, page);
  return page;
}

/** Endereço (o mesmo do QR Code e da etiqueta NFC) de uma mesa livre, lido na tela Mesas do admin. */
async function freeTableUrl(browser: Browser): Promise<{ n: number; path: string }> {
  const admin = await login(browser, "admin");
  await admin.goto("/admin/mesas");
  const row = admin.locator("tr", { hasText: "Livre" }).first();
  const n = Number(await row.locator("td strong").innerText());
  return { n, path: new URL(await row.locator("code.url").innerText()).pathname };
}

async function phone(browser: Browser, init?: () => void): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  if (init) await ctx.addInitScript(init);
  return ctx.newPage();
}

async function releaseWithPin(page: Page, pin: string): Promise<void> {
  await page.getByRole("button", { name: "Liberar mesa" }).click();
  await page.getByRole("dialog").getByLabel("PIN do atendente").fill(pin);
  await page.getByRole("dialog").getByRole("button", { name: "Liberar mesa" }).click();
}

test("jornada completa do atendimento", async ({ browser }) => {
  const { n, path } = await freeTableUrl(browser);
  const caixa = await login(browser, "caixa");

  // --- Página da mesa: “Cliente” em destaque e “Liberar mesa” discreto
  const p = await phone(browser);
  await p.goto(path);
  await expect(p.getByRole("heading", { name: new RegExp(`Mesa ${n}`) })).toBeVisible();
  await p.screenshot({ path: `${SHOTS}/01-pagina-da-mesa.png` });

  // Mesa ainda não liberada: “Cliente” leva à tela de mesa não liberada (Cenário B).
  await p.getByRole("button", { name: /^Cliente/ }).click();
  await expect(p.getByText(/ainda não foi liberada/)).toBeVisible();
  await p.getByRole("button", { name: "Voltar" }).click();

  // --- Atendente libera a mesa só com o PIN (Cenário A)
  await releaseWithPin(p, "0000");
  await expect(p.getByText("PIN incorreto.")).toBeVisible();
  await p.getByRole("dialog").getByLabel("PIN do atendente").fill("3333");
  await p.getByRole("dialog").getByRole("button", { name: "Liberar mesa" }).click();
  await expect(p.getByText("Mesa liberada!")).toBeVisible();
  await expect(caixa.locator(`.table-tile.tt-OCUPADA .table-tile__num:text-is("${n}")`)).toBeVisible({ timeout: 5000 });

  // --- Cliente entra e chama o atendente (Cenário C)
  await p.getByRole("button", { name: /^Cliente/ }).click();
  await expect(p.getByRole("button", { name: /Pedir a conta/ })).toBeVisible();
  await expect(p.getByRole("button", { name: "Comanda" })).toHaveCount(0);
  await expect(p.getByText(/R\$/)).toHaveCount(0); // “Pedir a conta” não mostra valor
  await p.getByRole("button", { name: /Chamar atendente/ }).first().click();
  await p.getByRole("dialog").getByRole("button", { name: "Chamar atendente" }).click();
  await expect(p.getByText("Chamado enviado. Um atendente já foi avisado.")).toBeVisible();
  const call = caixa.locator(".req", { hasText: `Mesa ${n}` }).filter({ hasText: "Chamou o atendente" });
  await expect(call).toBeVisible({ timeout: 5000 });
  await caixa.screenshot({ path: `${SHOTS}/02-salao-chamado.png` });
  await call.getByRole("button", { name: "Atendido" }).click();
  await expect(p.locator(".timeline__item", { hasText: "Chamado" })).toContainText("Atendido", { timeout: 5000 });

  // --- Pedido pelo cardápio: a equipe só repassa à cozinha (Cenário D)
  await p.getByRole("button", { name: /^Cardápio/ }).click();
  await p.getByRole("button", { name: "Adicionar Batata frita" }).click();
  await p.getByRole("dialog").getByLabel("Cheddar").check();
  await p.getByRole("dialog").getByRole("button", { name: /Adicionar · R\$/ }).click();
  await p.getByRole("button", { name: /Revisar pedido/ }).click();
  await p.getByRole("button", { name: "Enviar pedido" }).click();
  await expect(p.getByText(/Pedido enviado!/)).toBeVisible();
  const order = caixa.locator(".req", { hasText: `Mesa ${n}` }).filter({ hasText: "Pedido do cardápio" });
  await expect(order).toContainText("Cheddar", { timeout: 5000 });
  await order.getByRole("button", { name: "Repassado à cozinha" }).click();
  await expect(p.locator(".timeline__item", { hasText: "Pedido nº" })).toContainText("Repassado à cozinha", { timeout: 5000 });
  await p.screenshot({ path: `${SHOTS}/03-cliente-acompanhamento.png` });

  // --- Pedir a conta e conta finalizada (Cenários E e F)
  await p.getByRole("button", { name: /Pedir a conta/ }).click();
  await p.getByRole("dialog").getByRole("button", { name: "Pedir a conta" }).click();
  await expect(p.getByText("Conta solicitada")).toBeVisible();
  const bill = caixa.locator(".req", { hasText: `Mesa ${n}` }).filter({ hasText: "Pediu a conta" });
  await bill.getByRole("button", { name: "Conta finalizada" }).click();
  await expect(p.getByRole("heading", { name: "Atendimento encerrado" })).toBeVisible({ timeout: 5000 });
  await p.screenshot({ path: `${SHOTS}/04-cliente-encerrado.png` });
  await expect(caixa.locator(`.table-tile.tt-LIVRE .table-tile__num:text-is("${n}")`)).toBeVisible();

  // Página antiga recarregada continua sem acesso.
  await p.reload();
  await expect(p.getByText(/ainda não foi liberada/)).toBeVisible();

  // --- Detalhes da mesa: histórico com o horário de cada solicitação
  await caixa.locator(".table-tile").filter({ has: caixa.locator(`.table-tile__num:text-is("${n}")`) }).click();
  await caixa.locator(".history__row").first().click();
  await expect(caixa.locator(".table-detail")).toContainText("Conta finalizada");
  await expect(caixa.locator(".table-detail")).toContainText("Repassado à cozinha");
  await caixa.screenshot({ path: `${SHOTS}/05-detalhes-da-mesa.png` });
});

test("atendente só vê o salão e não acessa funções administrativas (Cenário I)", async ({ browser }) => {
  const att = await login(browser, "atendente");
  await expect(att.getByRole("link", { name: "Equipe" })).toHaveCount(0);
  await expect(att.getByRole("navigation", { name: "Painéis" })).toHaveCount(0);
  expect((await att.request.get("/api/v1/admin/users")).status()).toBe(403);
});

test("avisos aparecem em Novidades com o botão de chamar atendente", async ({ browser }) => {
  const admin = await login(browser, "admin");
  await admin.goto("/admin/notificacoes");
  const title = `Happy hour ${Date.now()}`;
  await admin.getByLabel("Título").fill(title);
  await admin.getByRole("button", { name: "Publicar aviso" }).click();
  await expect(admin.getByText("Aviso publicado.")).toBeVisible();

  const { path } = await freeTableUrl(browser);
  // Navegador sem Push API (ex.: Safari no iPhone fora do modo app): o atendimento continua normal.
  const p = await phone(browser, () => {
    delete (window as unknown as Record<string, unknown>).PushManager;
  });
  await p.goto(path);
  await releaseWithPin(p, "3333");
  await p.getByRole("button", { name: /^Cliente/ }).click();
  await p.getByRole("button", { name: "Novidades" }).click();
  await expect(p.getByText(title)).toBeVisible();
  await p.getByRole("button", { name: "Chamar atendente" }).click();
  await expect(p.getByText("Chamado enviado. Um atendente já foi avisado.")).toBeVisible();

  // limpa: o aviso sai (e some do celular na hora) e a mesa é encerrada
  await admin.goto("/admin/notificacoes");
  await admin.locator(".promo", { hasText: title }).getByRole("button", { name: "Ocultar" }).click();
  await expect(p.getByText(title)).toHaveCount(0, { timeout: 5000 });
  const caixa = await login(browser, "caixa");
  await caixa.locator(".req").filter({ hasText: "Chamou o atendente" }).first().getByRole("link").click();
  await caixa.getByRole("button", { name: "Finalizar conta e liberar a mesa" }).click();
  await caixa.getByRole("dialog").getByRole("button", { name: "Conta finalizada" }).click();
  await expect(caixa.getByText(/finalizada\. Mesa liberada\./)).toBeVisible();
});

test("endereço inexistente mostra mesa não encontrada", async ({ browser }) => {
  const p = await phone(browser);
  await p.goto("/m/codigo-inexistente-123");
  await expect(p.getByRole("heading", { name: "Mesa não encontrada" })).toBeVisible();
});
