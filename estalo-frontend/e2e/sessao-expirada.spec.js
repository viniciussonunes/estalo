/**
 * O que acontece quando o crachá deixa de valer no meio do uso.
 *
 * O app só conferia o token UMA vez, no boot. Depois disso um 401 era
 * erro da tela que o recebeu: a pessoa continuava navegando por dados
 * velhos, com toda ação falhando sem explicação, e a fila de respostas de
 * estudo ficava parada esperando um login que ninguém tinha pedido.
 *
 * Dois caminhos levam a isso no uso normal: o token expira, ou a senha é
 * trocada em outro aparelho (token_version derruba as sessões antigas --
 * comportamento que nós mesmos construímos).
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };
const DECK = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 2, memorization_pct: 0 };

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** `ref.expirado = true` faz o servidor passar a recusar o crachá. */
async function abrirLogado(page) {
  const ref = { expirado: false };
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/login") {
      // Senha errada também responde 401 -- e NÃO pode ser confundido com
      // fim de sessão (ver o teste do login mais abaixo).
      return json({ detail: "Email ou senha incorretos" }, 401);
    }
    if (ref.expirado) return json({ detail: "Not authenticated" }, 401);
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json([{ ...PASTA, children: [] }]);
    if (p === "/decks") return json([DECK]);
    if (p === "/study/decks/stats") return json({ 10: { total_cards: 2, criticos: 0, hoje: 0, novos: 2, validando: 0, dominados: 0 } });
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto("/?folder=2");
  await expect(page.locator(".lista-deck").first()).toBeVisible({ timeout: 15000 });
  // Espera a carga assentar antes de devolver: com requests ainda em voo,
  // ligar ref.expirado derrubava a sessão antes do gatilho do teste.
  await page.waitForLoadState("networkidle");
  return ref;
}

test.describe("Sessão expirada", () => {
  test("cai no login com uma explicação, em vez de falhar calado", async ({ page }) => {
    const servidor = await abrirLogado(page);
    servidor.expirado = true;

    // Qualquer ação autenticada serve de gatilho -- aqui, abrir um deck,
    // que vai buscar os cards no servidor.
    await page.locator(".lista-deck .lista-info").first().click();

    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
    await expect(page.locator(".toast-global")).toContainText(/sessão expirou/i);
    expect(await page.evaluate(() => localStorage.getItem("estalo_token"))).toBeNull();
  });

  test("as respostas de estudo que não subiram continuam guardadas", async ({ page }) => {
    // O ponto: deslogar não pode ser desculpa pra jogar fora o estudo que
    // ainda está na fila -- ele sobe no próximo login (ver outbox.js).
    const servidor = await abrirLogado(page);
    await page.evaluate(() => localStorage.setItem("estalo_outbox_respostas", JSON.stringify([
      { id: "r1", userId: "1", cardId: 100, quality: 4, ignorarElegibilidade: true, respondidoEm: "2026-10-13T10:00:00.000Z" },
    ])));
    servidor.expirado = true;
    await page.locator(".lista-deck .lista-info").first().click();
    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });

    const fila = await page.evaluate(() => JSON.parse(localStorage.getItem("estalo_outbox_respostas") || "[]"));
    expect(fila).toHaveLength(1);
  });

  test("senha errada no login não é fim de sessão", async ({ page }) => {
    // O 401 do /auth/login quer dizer "email ou senha incorretos". Tratá-lo
    // como sessão expirada encheria a tela de login de um aviso que não tem
    // nada a ver com o que a pessoa fez.
    await page.route("**/*", async (route) => {
      const req = route.request();
      const p = new URL(req.url()).pathname;
      if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
      if (p === "/auth/login") {
        return route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Email ou senha incorretos" }) });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });
    await page.goto("/login");
    await page.getByRole("textbox", { name: "Email" }).fill("estudante@estalo.dev");
    await page.getByRole("textbox", { name: "Senha" }).fill("senha-errada-123");
    await page.getByRole("button", { name: "Entrar" }).last().click();

    await expect(page.locator(".erro")).toContainText(/incorreto/i);
    await expect(page.locator(".toast-global")).toHaveCount(0);
  });
});
