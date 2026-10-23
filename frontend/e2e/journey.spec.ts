/* Jornada completa no navegador (Cenários A, C, D, E, F e I):
 * atendente abre a mesa no desktop → cliente no celular usa QR (URL da mesa), chama o atendente
 * e faz pedido → painel recebe em tempo real → caixa fecha → celular do cliente perde o acesso.
 * Usa os dados de `python -m app.cli seed-dev` (senha em E2E_PASSWORD).
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "demo-senha-123";
const SHOTS = "test-results/screens";

// Uma sessão por funcionário durante toda a execução (o login tem rate limit de verdade).
const sessions = new Map<string, Page>();

async function login(browser: Browser, email: string): Promise<Page> {
  const cached = sessions.get(email);
  if (cached && !cached.isClosed()) {
    await cached.goto("/painel");
    await expect(cached.getByText("Ao vivo")).toBeVisible();
    return cached;
  }
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const page = await ctx.newPage();
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha").fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Ao vivo")).toBeVisible();
  sessions.set(email, page);
  return page;
}

async function freeTable(page: Page): Promise<number> {
  const tile = page.locator(".table-tile.tt-LIVRE").first();
  const n = Number(await tile.locator(".table-tile__num").innerText());
  return n;
}

test("jornada completa do atendimento", async ({ browser }) => {
  // --- Atendente abre a mesa (Cenário A)
  const att = await login(browser, "atendente@demo.local");
  const n = await freeTable(att);
  await att.locator(".table-tile", { hasText: String(n) }).filter({ has: att.locator(`.table-tile__num:text-is("${n}")`) }).click();
  await att.getByLabel("Identificação (opcional)").fill("Mesa do teste E2E");
  await att.getByLabel("Seu PIN pessoal").fill("0000");
  await att.getByRole("button", { name: "Abrir mesa" }).click();
  await expect(att.getByText("PIN ou senha de confirmação incorretos.")).toBeVisible();
  await att.getByLabel("Seu PIN pessoal").fill("3333");
  await att.getByRole("button", { name: "Abrir mesa" }).click();
  await expect(att.getByText(`Mesa ${n} aberta.`)).toBeVisible();
  await att.keyboard.press("Escape");

  // URL pública (a mesma do QR Code e da tag NFC) vem do admin.
  const admin = await login(browser, "admin@demo.local");
  await admin.goto("/admin/mesas");
  const row = admin.locator("tr", { has: admin.locator(`td strong:text-is("${n}")`) });
  const url = new URL(await row.locator("code.url").innerText());

  // --- Cliente no celular (sem instalar nada, sem cadastro)
  const phoneCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const phone = await phoneCtx.newPage();
  await phone.goto(url.pathname);
  await expect(phone.getByRole("heading", { name: new RegExp(`Mesa ${n}`) })).toBeVisible();
  await phone.screenshot({ path: `${SHOTS}/01-cliente-mesa.png` });

  // --- Chamar atendente (Cenário C)
  await phone.getByRole("button", { name: /Chamar atendente/ }).first().click();
  await phone.getByRole("dialog").getByRole("button", { name: "Chamar atendente" }).click();
  await expect(phone.getByText("Chamado enviado. Um atendente já foi avisado.")).toBeVisible();
  await expect(att.locator(".req", { hasText: `Mesa ${n}` }).filter({ hasText: "Chamou o atendente" })).toBeVisible({ timeout: 5000 });
  await att.screenshot({ path: `${SHOTS}/02-painel-chamado.png` });
  await att.locator(".req", { hasText: `Mesa ${n}` }).getByRole("button", { name: "Assumir" }).click();
  await expect(phone.getByText(/Atendente a caminho/)).toBeVisible({ timeout: 5000 });
  await expect(phone.getByText(/Assumido/).first()).toBeVisible();

  // --- Pedido (Cenário D)
  await phone.getByRole("button", { name: /^Cardápio/ }).click();
  await phone.getByRole("button", { name: "Adicionar Batata frita" }).click();
  await phone.getByRole("dialog").getByLabel("Cheddar").check();
  await phone.getByRole("dialog").getByRole("button", { name: /Adicionar · R\$/ }).click();
  await phone.getByRole("button", { name: /Revisar pedido/ }).click();
  await phone.screenshot({ path: `${SHOTS}/03-cliente-carrinho.png` });
  await phone.getByRole("button", { name: "Enviar pedido" }).click();
  await expect(phone.getByText("Pedido recebido pela cozinha.")).toBeVisible();
  await expect(phone.getByText("Batata frita").first()).toBeVisible();

  await att.getByRole("link", { name: "Pedidos", exact: true }).click();
  const card = att.locator(".order", { hasText: `Mesa ${n}` });
  await expect(card).toBeVisible({ timeout: 5000 });
  await expect(card).toContainText("Cheddar");
  await card.getByRole("button", { name: "Começar preparo" }).click();
  await card.getByRole("button", { name: "Marcar como pronto" }).click();
  await card.getByRole("button", { name: "Entregue na mesa" }).click();
  await expect(phone.locator(".bill__order").first()).toContainText("Entregue", { timeout: 5000 });

  // --- Atendente não acessa funções administrativas (Cenário I)
  await expect(att.getByRole("link", { name: "Equipe" })).toHaveCount(0);
  const denied = await att.request.get("/api/v1/admin/users");
  expect(denied.status()).toBe(403);

  // --- Pedir a conta (Cenário E)
  await phone.getByRole("button", { name: "Mesa" }).click();
  await phone.getByRole("button", { name: /Pedir a conta/ }).click();
  await phone.getByRole("dialog").getByRole("button", { name: "Pedir a conta" }).click();
  await expect(phone.getByText("Conta solicitada")).toBeVisible();

  const caixa = await login(browser, "caixa@demo.local");
  await caixa.getByRole("link", { name: "Caixa", exact: true }).click();
  await caixa.getByRole("button", { name: new RegExp(`Mesa ${n}\\b.*Pediu a conta`) }).click();
  await expect(caixa.getByText(/Comanda — mesa/)).toBeVisible();
  await caixa.screenshot({ path: `${SHOTS}/04-caixa-comanda.png` });

  // --- Encerramento e revogação (Cenário F)
  await caixa.getByRole("button", { name: "Fechar conta e liberar mesa" }).click();
  await caixa.getByRole("dialog").getByLabel("Forma de pagamento").selectOption("PIX");
  await caixa.getByRole("dialog").getByRole("button", { name: "Fechar conta" }).click();
  await expect(caixa.getByText(`Mesa ${n} encerrada e liberada.`)).toBeVisible();
  await expect(phone.getByRole("heading", { name: "Atendimento encerrado" })).toBeVisible({ timeout: 5000 });
  await phone.screenshot({ path: `${SHOTS}/05-cliente-encerrado.png` });

  // Página antiga recarregada continua sem acesso; mesa volta a LIVRE.
  await phone.reload();
  await expect(phone.getByText(/não está aberta para atendimento digital/)).toBeVisible();
  await att.getByRole("link", { name: /^Salão/ }).click();
  await expect(att.locator(`.table-tile.tt-LIVRE .table-tile__num:text-is("${n}")`)).toBeVisible();
});

test("navegador sem suporte a push continua atendendo", async ({ browser }) => {
  const att = await login(browser, "atendente@demo.local");
  const n = await freeTable(att);
  await att.locator(".table-tile").filter({ has: att.locator(`.table-tile__num:text-is("${n}")`) }).click();
  await att.getByLabel("Seu PIN pessoal").fill("3333");
  await att.getByRole("button", { name: "Abrir mesa" }).click();
  await expect(att.getByText(`Mesa ${n} aberta.`)).toBeVisible();

  const admin = await login(browser, "admin@demo.local");
  await admin.goto("/admin/mesas");
  const url = new URL(await admin.locator("tr", { has: admin.locator(`td strong:text-is("${n}")`) }).locator("code.url").innerText());

  const ctx = await browser.newContext({ viewport: { width: 375, height: 700 } });
  await ctx.addInitScript(() => {
    // Simula navegador sem Push API (ex.: Safari no iPhone fora do modo app).
    delete (window as unknown as Record<string, unknown>).PushManager;
  });
  const phone = await ctx.newPage();
  await phone.goto(url.pathname);
  await phone.getByRole("button", { name: "Novidades" }).click();
  await expect(phone.getByText(/não oferece notificações/)).toBeVisible();
  await phone.getByRole("button", { name: "Mesa" }).click();
  await phone.getByRole("button", { name: /Chamar atendente/ }).first().click();
  await phone.getByRole("dialog").getByRole("button", { name: "Chamar atendente" }).click();
  await expect(phone.getByText("Chamado enviado. Um atendente já foi avisado.")).toBeVisible();

  // limpa: caixa encerra a mesa
  const caixa = await login(browser, "caixa@demo.local");
  await caixa.getByRole("link", { name: "Caixa", exact: true }).click();
  await caixa.getByRole("button", { name: new RegExp(`Mesa ${n}\\b`) }).click();
  await caixa.getByRole("button", { name: "Fechar conta e liberar mesa" }).click();
  await caixa.getByRole("dialog").getByRole("button", { name: "Fechar conta" }).click();
  await expect(caixa.getByText(`Mesa ${n} encerrada e liberada.`)).toBeVisible();
});

test("mesa livre bloqueia o atendimento digital (Cenário B)", async ({ browser }) => {
  const admin = await login(browser, "admin@demo.local");
  await admin.goto("/admin/mesas");
  const freeRow = admin.locator("tr", { hasText: "Livre" }).first();
  const url = new URL(await freeRow.locator("code.url").innerText());
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  await page.goto(url.pathname);
  await expect(page.getByText(/não está aberta para atendimento digital/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Chamar atendente/ })).toHaveCount(0);
  await page.goto("/m/codigo-inexistente-123");
  await expect(page.getByRole("heading", { name: "Mesa não encontrada" })).toBeVisible();
});
