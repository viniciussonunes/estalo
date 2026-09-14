/**
 * O que a pessoa vê quando a IA falha ao gerar cards.
 *
 * Duas coisas estavam erradas. O backend mandava texto de desenvolvedor
 * ("A IA não devolveu um JSON válido", "Gemini indisponível após 2
 * tentativas") e a tela mostrava inteiro -- isso foi resolvido no
 * backend (app/core/erros_ia.py), aqui a API simulada já devolve a frase
 * nova. E o texto colado sobrevive ao erro (é estado da tela), mas nada
 * dizia isso: com um erro na cara, é razoável achar que perdeu tudo.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };
const DECK = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 0, memorization_pct: 0 };
const MENSAGEM_DO_BACKEND = "A IA não conseguiu responder agora. Tente de novo em instantes.";
const TEXTO = "Intune é o MDM da Microsoft. Políticas de conformidade definem os requisitos mínimos de um aparelho.";

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

async function prepararComIAFora(page, { status = 503, detail = MENSAGEM_DO_BACKEND } = {}) {
  const chamadas = { geracoes: 0, decksCriados: 0, decksExcluidos: 0 };
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json([{ ...PASTA, children: [] }]);
    if (p === "/decks" && req.method() === "POST") { chamadas.decksCriados += 1; return json({ ...DECK, id: 11, title: "Novo" }, 201); }
    if (p === "/decks") return json([DECK]);
    if (/^\/decks\/\d+$/.test(p) && req.method() === "DELETE") { chamadas.decksExcluidos += 1; return route.fulfill({ status: 204 }); }
    if (/^\/decks\/\d+\/cards\/generate$/.test(p)) { chamadas.geracoes += 1; return json({ detail }, status); }
    if (/^\/decks\/\d+\/cards$/.test(p)) return json([]);
    if (p === "/study/decks/stats") return json({ 10: { total_cards: 0, criticos: 0, hoje: 0, novos: 0, validando: 0, dominados: 0 } });
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json({ total_cards: 0, criticos: 0, hoje: 0, novos: 0, validando: 0, dominados: 0 });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  return chamadas;
}

test.describe("Quando a IA falha", () => {
  test("criar deck: a frase é calma e diz que o texto continua lá", async ({ page }) => {
    const chamadas = await prepararComIAFora(page);
    await page.goto("/criar-deck");
    await page.getByPlaceholder(/SC-900/).fill("Intune básico");
    await page.locator("textarea").fill(TEXTO);
    await page.getByRole("button", { name: "Gerar cards com IA" }).click();

    const erro = page.locator(".erro");
    await expect(erro).toContainText(MENSAGEM_DO_BACKEND);
    await expect(erro).toContainText("O nome e o texto continuam aqui.");
    await expect(erro).not.toContainText(/JSON|Gemini|tentativas/);
    // E é verdade: nada foi apagado do formulário.
    await expect(page.locator("textarea")).toHaveValue(TEXTO);
    await expect(page.getByPlaceholder(/SC-900/)).toHaveValue("Intune básico");
    // O deck órfão criado antes da geração foi desfeito (comportamento
    // que já existia; aqui só garante que a mensagem nova não o quebrou).
    expect(chamadas.decksCriados).toBe(1);
    expect(chamadas.decksExcluidos).toBe(1);
  });

  test("dentro do deck: o modal de gerar também avisa que o texto ficou", async ({ page }) => {
    await prepararComIAFora(page);
    await page.goto("/?folder=2");
    await page.locator(".lista-deck .lista-info").first().click();
    await page.locator(".botao-adicionar-card").click();
    await page.getByRole("button", { name: "Gerar com IA" }).click();
    await page.locator(".modal-conteudo textarea, [role=dialog] textarea").first().fill(TEXTO);
    await page.getByRole("button", { name: "Gerar cards" }).click();

    const erro = page.locator(".erro");
    await expect(erro).toContainText(MENSAGEM_DO_BACKEND);
    await expect(erro).toContainText("Seu texto continua aqui.");
    await expect(page.locator(".modal-conteudo textarea, [role=dialog] textarea").first()).toHaveValue(TEXTO);
  });

  test("cota estourada mantém a mensagem própria, sem prometer o texto pra amanhã", async ({ page }) => {
    await prepararComIAFora(page, { status: 429, detail: "Limite diário de uso do Tutor/IA atingido. Tente novamente amanhã." });
    await page.goto("/criar-deck");
    await page.getByPlaceholder(/SC-900/).fill("Intune básico");
    await page.locator("textarea").fill(TEXTO);
    await page.getByRole("button", { name: "Gerar cards com IA" }).click();

    const erro = page.locator(".erro");
    await expect(erro).toContainText("Tente novamente amanhã.");
    await expect(erro).not.toContainText("continuam aqui");
  });
});
