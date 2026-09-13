/**
 * Confirmação ao excluir pasta.
 *
 * Pasta é a exceção deliberada à regra do desfazer (que substituiu o
 * confirm() nativo no resto do app). O desfazer protege contra o clique
 * errado que a pessoa PERCEBE -- e uma pasta fechada esconde tudo que tem
 * dentro: subpastas, decks e cards somem em cascata sem nunca terem
 * aparecido na tela. Os 5 segundos do toast podem passar antes de alguém
 * entender o tamanho do erro.
 *
 * A assimetria é intencional: se um dia alguém "padronizar" isso tirando o
 * pop-up em nome da consistência, estes testes falham.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

// Certificações > MD-102 > Reforço.  Decks em MD-102 e em Reforço, pra a
// contagem ter que descer a árvore inteira e não só um nível.
const ARVORE = [{
  id: 1, name: "Certificações", parent_id: null, depth: 1, color: null,
  children: [{
    id: 2, name: "MD-102", parent_id: 1, depth: 2, color: null,
    children: [{ id: 3, name: "Reforço", parent_id: 2, depth: 3, color: null, children: [] }],
  }],
}];
// Uma pasta sem nada dentro, pra checar o caminho que NÃO pergunta.
const PASTA_VAZIA = { id: 9, name: "Rascunhos", parent_id: null, depth: 1, color: null, children: [] };

const DECKS = [
  { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 40, memorization_pct: 0 },
  { id: 11, title: "Autopilot", description: null, folder_id: 3, created_at: "2026-01-02T00:00:00", total_cards: 8, memorization_pct: 0 },
];
const STATS = { total_cards: 40, criticos: 0, hoje: 0, novos: 40, validando: 0, dominados: 0, new_cards: 40, validating: 0, dominated: 0, due_now: 0 };

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** Devolve um contador vivo dos DELETE de pasta que chegaram ao servidor. */
async function abrirDashboard(page) {
  const apagadas = { total: 0 };
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });

    if (/^\/folders\/\d+$/.test(p) && req.method() === "DELETE") {
      apagadas.total += 1;
      return route.fulfill({ status: 204, body: "" });
    }
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json([...ARVORE, PASTA_VAZIA]);
    if (p === "/decks") return json(DECKS);
    if (p === "/study/decks/stats") return json({ 10: STATS, 11: STATS });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto("/");
  await expect(page.locator(".pasta-card, .lista-pasta").first()).toBeVisible();
  return apagadas;
}

/** O botão de excluir da pasta com esse nome, na área de conteúdo. */
function botaoExcluir(page, nome) {
  return page.locator(".pasta-card, .lista-pasta")
    .filter({ hasText: nome })
    .getByRole("button", { name: "Excluir pasta" });
}

test.describe("Excluir pasta", () => {
  test("pergunta antes, dizendo exatamente o que vai junto", async ({ page }) => {
    await abrirDashboard(page);
    await botaoExcluir(page, "Certificações").click();

    const dialogo = page.getByRole("dialog");
    await expect(dialogo).toBeVisible();
    await expect(dialogo).toContainText('Excluir "Certificações"?');
    // 2 subpastas (MD-102 e Reforço), 2 decks, 48 cards (40 + 8) -- a
    // contagem desce a árvore toda, não só um nível. Um "tem certeza?"
    // genérico não diria nada disso.
    await expect(dialogo).toContainText("2 subpastas, 2 decks e 48 cards");
  });

  test("cancelar não apaga nada", async ({ page }) => {
    const apagadas = await abrirDashboard(page);
    await botaoExcluir(page, "Certificações").click();
    await page.getByRole("button", { name: "Cancelar" }).click();

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator(".pasta-card, .lista-pasta").filter({ hasText: "Certificações" })).toBeVisible();
    await page.waitForTimeout(6500); // além da janela do desfazer
    expect(apagadas.total, "cancelar mandou DELETE mesmo assim").toBe(0);
  });

  test("Esc também cancela", async ({ page }) => {
    const apagadas = await abrirDashboard(page);
    await botaoExcluir(page, "Certificações").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator(".pasta-card, .lista-pasta").filter({ hasText: "Certificações" })).toBeVisible();
    expect(apagadas.total).toBe(0);
  });

  test("confirmar apaga — e o desfazer continua valendo depois", async ({ page }) => {
    const apagadas = await abrirDashboard(page);
    await botaoExcluir(page, "Certificações").click();
    await page.getByRole("button", { name: "Excluir pasta" }).last().click();

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator(".pasta-card, .lista-pasta").filter({ hasText: "Certificações" })).toHaveCount(0);

    // Confirmar não abre mão da rede de segurança: o toast ainda aparece.
    await page.getByRole("button", { name: /Desfazer/i }).click();
    await expect(page.locator(".pasta-card, .lista-pasta").filter({ hasText: "Certificações" })).toBeVisible();
    await page.waitForTimeout(6500);
    expect(apagadas.total, "desfazer não impediu o DELETE").toBe(0);
  });

  test("pasta vazia não pergunta nada", async ({ page }) => {
    // Sem conteúdo não há cascata -- perguntar ali seria só atrito, e o
    // desfazer já cobre o clique errado.
    await abrirDashboard(page);
    await botaoExcluir(page, "Rascunhos").click();

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator(".pasta-card, .lista-pasta").filter({ hasText: "Rascunhos" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Desfazer/i })).toBeVisible();
  });

  test("deck continua sem perguntar", async ({ page }) => {
    // A assimetria é o ponto: deck se recria em segundos e o estrago está
    // à vista. Se alguém "padronizar" e puser pop-up aqui também, este
    // teste avisa.
    await abrirDashboard(page);
    await page.goto("/?folder=2");
    await expect(page.locator(".lista-deck").first()).toBeVisible();
    await page.locator(".lista-deck").filter({ hasText: "Intune" })
      .getByRole("button", { name: "Excluir deck" }).click();

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Desfazer/i })).toBeVisible();
  });
});
