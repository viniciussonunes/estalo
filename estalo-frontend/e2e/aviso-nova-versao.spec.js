/**
 * Faixa de "nova versão disponível".
 *
 * Por que existe: com `registerType: "autoUpdate"`, o service worker só
 * troca de versão depois que TODAS as abas do app fecham. Num app
 * instalado na tela inicial isso leva dias -- e foi assim que uma mudança
 * recém-publicada pareceu "não ter subido" em 2026-09-13. Tinha subido; só
 * não tinha chegado naquele navegador.
 *
 * O que este arquivo cobre: a faixa em si -- aparece quando avisada, tem a
 * ação junto, e não aparece sozinha. A ponte service worker -> aviso é
 * exercitada à parte (precisa de dois builds e de um SW de verdade, coisa
 * que o servidor de dev não tem).
 *
 * O gancho `estalo:nova-versao` não é enfeite de teste: é o mesmo evento
 * que src/atualizacao.js dispara quando o SW avisa. Testar por ele é
 * testar o caminho real do componente.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

async function abrirLogado(page) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders" || p === "/decks") return json([]);
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto("/");
  await expect(page.locator(".primeiro-uso")).toBeVisible();
}

const faixa = (page) => page.locator(".aviso-versao");
const anunciar = (page) => page.evaluate(() => window.dispatchEvent(new CustomEvent("estalo:nova-versao")));

test.describe("Aviso de nova versão", () => {
  test("não aparece quando não há versão nova", async ({ page }) => {
    // A regra da casa: não anuncia o normal. Uma faixa permanente sobre
    // "você está atualizado" seria exatamente isso.
    await abrirLogado(page);
    await expect(faixa(page)).toHaveCount(0);
  });

  test("aparece com a ação junto quando sai versão nova", async ({ page }) => {
    await abrirLogado(page);
    await anunciar(page);

    await expect(faixa(page)).toBeVisible();
    await expect(faixa(page)).toContainText("Nova versão disponível");
    // Avisar sem dar o botão empurraria a pessoa pro "recarregue com
    // Ctrl+Shift+R", que é instrução de suporte técnico, não de produto.
    await expect(faixa(page).getByRole("button", { name: "Atualizar" })).toBeVisible();
  });

  test("clicar em Atualizar recarrega o app", async ({ page }) => {
    await abrirLogado(page);
    await page.evaluate(() => { window.__marcaAntesDoReload = true; });
    await anunciar(page);
    await faixa(page).getByRole("button", { name: "Atualizar" }).click();

    // Recarregou de verdade: a marca deixada no window não sobrevive.
    await expect.poll(
      () => page.evaluate(() => window.__marcaAntesDoReload ?? false),
      // Até 3s é a rede de segurança do atualizacao.js: se o service
      // worker não recarregar sozinho, a página recarrega na marra. Um
      // botão "Atualizar" que não faz nada é pior que não ter botão.
      { timeout: 12000, message: "a página não recarregou" },
    ).toBe(false);
    await expect(page.locator(".primeiro-uso")).toBeVisible();
  });

  test("é faixa, não modal: dá pra continuar usando o app", async ({ page }) => {
    // Quem está no meio de uma sessão de estudo não pode ser bloqueado por
    // um aviso de atualização.
    await abrirLogado(page);
    await anunciar(page);
    await expect(faixa(page)).toBeVisible();

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByRole("button", { name: "Criar meu primeiro deck" }).click();
    await expect(page).toHaveURL(/criar-deck/);
    // E continua visível na tela seguinte -- some só quando for aplicada.
    await expect(faixa(page)).toBeVisible();
  });
});
