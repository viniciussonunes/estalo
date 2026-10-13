/**
 * Quando o servidor responde fora do formato, o estrago tem que ser do
 * tamanho certo.
 *
 * As telas fazem `.map`/`.length` direto no que a API devolve. Um corpo
 * fora do formato -- um `{}` vindo de um proxy, uma página de erro de CDN,
 * um endpoint que mudou de forma -- virava `undefined.map is not a
 * function` NO RENDER, fora de qualquer try/catch: ia direto pro
 * ErrorBoundary da raiz e o app INTEIRO sumia atrás de "Algo deu errado".
 * Reproduzido numa varredura, no Revelar e no Dashboard.
 *
 * Agora isso vira erro na camada de dados (ver _lista em api.js): a tela
 * que pediu mostra a própria mensagem de erro, com o resto do app de pé.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };
const DECK = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 2, memorization_pct: 0 };
const STATS = { total_cards: 2, criticos: 0, hoje: 0, novos: 2, validando: 0, dominados: 0, new_cards: 2, validating: 0, dominated: 0, due_now: 2 };
const CARDS = [
  { id: 100, front: "P1", back: "R1", source: "manual", repetitions: 0, options: ["a", "b", "c"], explanation: "e" },
  { id: 101, front: "P2", back: "R2", source: "manual", repetitions: 0, options: ["a", "b", "c"], explanation: "e" },
];

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** `estragar` é o pathname que vai responder `{}` em vez de uma lista. */
async function abrirLogado(page, { estragar } = {}) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (estragar && estragar.test(p)) return json({}); // 200, mas não é lista
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json([{ ...PASTA, children: [] }]);
    if (p === "/decks") return json([DECK]);
    if (p === "/study/decks/stats") return json({ 10: STATS });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    if (/^\/decks\/\d+\/cards$/.test(p)) return json(CARDS);
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(STATS);
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
}

const appMorreu = (page) => page.getByText("Algo deu errado.");

test.describe("Resposta fora do formato", () => {
  test("Revelar: a tela avisa, o app continua de pé", async ({ page }) => {
    await abrirLogado(page, { estragar: /\/reveal$/ });
    await page.goto("/?folder=2");
    await page.locator(".lista-deck .lista-info").first().click();
    await expect(page.locator(".cards-lista-topo")).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: "Outros modos" }).click();
    await page.getByRole("button", { name: /Só ler/ }).click();

    await expect(page.locator(".erro")).toContainText(/formato inesperado/i);
    await expect(appMorreu(page)).toHaveCount(0);
    // Dá pra sair pelo próprio app, sem recarregar nada.
    await page.getByRole("button", { name: "← Voltar" }).click();
    await expect(page.locator(".cards-lista-topo")).toBeVisible({ timeout: 15000 });
  });

  test("Dashboard: a Home avisa em vez de sumir", async ({ page }) => {
    await abrirLogado(page, { estragar: /^\/folders$/ });
    await page.goto("/");

    await expect(page.locator(".erro")).toContainText(/formato inesperado/i);
    await expect(appMorreu(page)).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Sua conta/ })).toBeVisible();
  });

  test("lista de cards: o deck avisa e o resto do app fica", async ({ page }) => {
    await abrirLogado(page, { estragar: /^\/decks\/\d+\/cards$/ });
    await page.goto("/?folder=2");
    await page.locator(".lista-deck .lista-info").first().click();

    await expect(page.locator(".erro")).toContainText(/formato inesperado/i);
    await expect(appMorreu(page)).toHaveCount(0);
  });
});
