/* Criar mesa → gravar etiqueta NFC (leitor simulado) → conferir → travar → rearranjar e ativar planta.
 * O Chromium de teste não tem NFC: um `NDEFReader` falso guarda a "etiqueta" em memória, com UID aleatório.
 * Usa `seed-dev` (senha em E2E_PASSWORD). Cada execução cria uma mesa nova, de número aleatório.
 */
import { expect, test } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "demo-senha-123";

test("administrador cria mesa, grava e trava a etiqueta e troca a planta do salão", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(() => {
    const hex = () => Array.from({ length: 6 }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, "0")).join(":");
    const tag = { uid: "04:" + hex(), url: null as string | null, locked: false };
    (window as unknown as { __tag: typeof tag }).__tag = tag;
    (window as unknown as { NDEFReader: unknown }).NDEFReader = class extends EventTarget {
      onreading: ((ev: Event) => void) | null = null;
      async write(msg: { records: { data: string }[] }) {
        await new Promise((r) => setTimeout(r, 100));
        if (tag.locked) throw new DOMException("locked", "NotAllowedError");
        tag.url = msg.records[0]!.data;
      }
      async scan() {
        setTimeout(() => {
          const ev = new Event("reading") as Event & { serialNumber: string; message: unknown };
          ev.serialNumber = tag.uid;
          ev.message = { records: tag.url ? [{ recordType: "url", data: new TextEncoder().encode(tag.url) }] : [] };
          this.onreading?.(ev);
        }, 100);
      }
      async makeReadOnly() {
        tag.locked = true;
      }
    };
  });
  const page = await ctx.newPage();
  await page.goto("/login");
  await page.getByLabel("E-mail").fill("admin@demo.local");
  await page.getByLabel("Senha").fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Ao vivo")).toBeVisible();

  // Criar mesa + gravar
  const number = String(500 + Math.floor(Math.random() * 400));
  await page.goto("/admin/mesas");
  await expect(page.getByText("Gravando agora").first()).toBeVisible();
  await page.locator('input[inputmode="numeric"]').fill(number);
  await page.locator('form input[type="password"]').first().fill(PASSWORD);
  await page.getByRole("button", { name: "Criar mesa e gravar etiqueta" }).click();
  await expect(page.getByRole("dialog").getByText(`Mesa ${number}`)).toBeVisible();
  await page.getByRole("button", { name: "Gravar etiqueta agora" }).click();
  await expect(page.getByRole("dialog").getByText("gravada e conferida").first()).toBeVisible({ timeout: 15_000 });
  const written = await page.evaluate(() => (window as unknown as { __tag: { url: string } }).__tag.url);
  expect(written).toMatch(/\/m\/[\w-]+$/); // a URL veio do servidor, ninguém digitou

  // Travar (pede a senha de novo)
  await page.locator(".step").nth(2).locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Travar para sempre" }).click();
  await expect(page.getByRole("dialog").getByText("Etiqueta travada").first()).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Concluir" }).click();
  await expect(page.locator("tr", { hasText: number }).getByText("Gravada e travada")).toBeVisible();

  // Planta: novo modelo, mover a mesa, ativar → o Salão mostra a planta nova
  await page.goto("/admin/planta");
  await expect(page.locator(".floor-grid")).toBeVisible();
  await page.locator(`.floor-tile:has(strong:text-is("${number}"))`).click();
  await page.locator(".floor-cell:not(.has-table)").nth(40).click();
  await page.getByRole("button", { name: "Novo modelo" }).click();
  const name = `Evento ${number}`;
  await page.locator("dialog input").first().fill(name);
  await page.getByRole("dialog").getByRole("button", { name: "Criar modelo" }).click();
  await expect(page.locator("select option", { hasText: name })).toBeAttached();
  await page.getByRole("button", { name: "Usar esta planta" }).click();
  await expect(page.getByRole("button", { name: "Planta ativa" })).toBeVisible();
  await page.goto("/painel");
  await expect(page.getByText(`Planta: ${name}`)).toBeVisible();
  await ctx.close();
});
