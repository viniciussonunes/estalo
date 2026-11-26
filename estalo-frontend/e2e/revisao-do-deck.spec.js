/**
 * Revisão do deck e treino no Aprender do deck inteiro.
 *
 * Por que existe: o botão do deck dizia "Estudar hoje (5)" e abria o
 * Aprender com o deck INTEIRO -- 15 perguntas num deck de 15 com 5
 * vencidas. E toda resposta valia como revisão espaçada, vencida ou não.
 * Medido com o SM-2 real: card novo aberto duas vezes no mesmo dia virava
 * Dominado sem esperar intervalo nenhum; card que só venceria em 6 dias
 * ia pra 16 com 1 dia passado.
 *
 * O que estes testes seguram:
 *   - o botão leva só aos vencidos, os mais atrasados primeiro, e o
 *     número dele é o número da sessão;
 *   - no deck inteiro, card que ainda não venceu é treino: a resposta NÃO
 *     vai pro servidor (contamos as chamadas a /answer);
 *   - os que contam vêm primeiro, e um aviso só explica o treino;
 *   - revisão sem nada vencido diz isso, e não "falha da IA".
 *
 * A revisão do deck é montada a partir de /decks/{id}/cards (vence_em),
 * não de uma rota própria, porque a lista tem cópia offline -- o caso do
 * deck baixado está em rede-lenta.spec.js.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASSADO = "2026-01-01";
const FUTURO = "2099-01-01";

function card(id, grupo) {
  const vence = { critico: "2025-12-01", vencido: PASSADO, futuro: FUTURO, novo: null }[grupo];
  return {
    id, front: `Pergunta ${grupo} ${id}`, back: `CERTA ${id}`, source: "ai",
    repetitions: grupo === "novo" ? 0 : 2, vence_em: vence,
    options: [`errada A${id}`, `errada B${id}`, `errada C${id}`], explanation: "Explicação.",
  };
}

/** 15 cards, na ordem de criação: 6 em dia, 3 vencidos, 2 críticos, 4 novos. */
const BARALHO = [
  ...[100, 101, 102, 103, 104, 105].map(i => card(i, "futuro")),
  ...[106, 107, 108].map(i => card(i, "vencido")),
  ...[109, 110].map(i => card(i, "critico")),
  ...[111, 112, 113, 114].map(i => card(i, "novo")),
];

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

async function abrirDeck(page, { cards = BARALHO, criticos = 2, hoje = 3 } = {}) {
  const deck = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: cards.length, memorization_pct: 0 };
  const stats = { total_cards: cards.length, criticos, hoje, novos: 4, validando: 0, dominados: 11, new_cards: 4, validating: 0, dominated: 11, due_now: criticos + hoje };
  const respondidos = [];
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev", cards_por_sessao: 15 });
    if (p === "/folders") return json([{ id: 2, name: "MD-102", parent_id: null, depth: 1, color: null, children: [] }]);
    if (p === "/decks") return json([deck]);
    if (p === "/study/decks/stats") return json({ 10: stats });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    if (/^\/decks\/\d+\/cards$/.test(p)) return json(cards);
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(stats);
    const m = p.match(/^\/study\/cards\/(\d+)\/answer$/);
    if (m) {
      respondidos.push(Number(m[1]));
      return json({ card_id: Number(m[1]), interval: 1, ease_factor: 2.5, repetitions: 1, next_due: "2026-01-02T00:00:00", status: "validando" });
    }
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto("/?folder=2");
  await page.locator(".lista-deck .lista-info").first().click();
  return respondidos;
}

const pergunta = (page) => page.locator(".cartao-frente .cartao-texto");

async function acertarTudo(page) {
  for (let i = 0; i < 40; i++) {
    if (await page.locator(".sessao-resumo").count()) return;
    await page.locator(".quiz-opcao", { hasText: "CERTA" }).first().click();
    await page.getByRole("button", { name: /Próxim|Ver resultado/ }).click();
    await page.waitForFunction(() =>
      document.querySelector(".sessao-resumo") || document.querySelector(".quiz-opcao:not([disabled])"));
  }
}

test.describe("Revisão do deck", () => {
  test("o botão diz o total de vencidos e abre só eles, críticos primeiro", async ({ page }) => {
    await abrirDeck(page);
    const botao = page.locator(".modos-estudo-topo").getByRole("button", { name: "🔴 Revisar (5)" });
    await expect(botao).toBeVisible();

    await botao.click();
    await expect(page.locator(".quiz-progresso-contador")).toHaveText("0 de 5 concluídos");
    await expect(pergunta(page)).toHaveText(/Pergunta critico/);
  });

  test("só com vencidos de hoje, o botão continua sendo 'Estudar hoje (N)'", async ({ page }) => {
    await abrirDeck(page, { cards: BARALHO.filter(c => c.vence_em !== "2025-12-01"), criticos: 0, hoje: 3 });
    await page.getByRole("button", { name: "Estudar hoje (3)" }).click();
    await expect(page.locator(".quiz-progresso-contador")).toHaveText("0 de 3 concluídos");
  });

  test("ao terminar, diz que zerou o deck e grava as 5 respostas", async ({ page }) => {
    const respondidos = await abrirDeck(page);
    await page.getByRole("button", { name: /Revisar/ }).click();
    await acertarTudo(page);

    await expect(page.getByText("Você zerou a revisão de hoje neste deck.")).toBeVisible();
    await expect.poll(() => respondidos.length).toBe(5);
    expect(respondidos.sort()).toEqual([106, 107, 108, 109, 110]);
  });

  test("sem nada vencido, diz que não há o que revisar (e não que a IA falhou)", async ({ page }) => {
    // Contagem do botão velha: as stats ainda dizem 2, a lista não tem nenhum.
    await abrirDeck(page, { cards: BARALHO.filter(c => c.vence_em === FUTURO || c.vence_em === null) });
    await page.getByRole("button", { name: /Revisar/ }).click();
    await expect(page.getByText("Nada para revisar agora")).toBeVisible();
    await expect(page.getByText(/Não foi possível preparar/)).toHaveCount(0);
  });
});

test.describe("Aprender do deck inteiro: treino", () => {
  async function abrirDeckInteiro(page) {
    const respondidos = await abrirDeck(page);
    await page.getByRole("button", { name: "Outros modos" }).click();
    await page.locator(".modo-opcao", { hasText: "Aprender" }).click();
    await expect(page.locator(".quiz-opcao").first()).toBeVisible();
    return respondidos;
  }

  test("os que contam vêm primeiro, e um aviso só explica o treino", async ({ page }) => {
    await abrirDeckInteiro(page);
    await expect(page.locator(".aviso-treino")).toHaveText(/6 de 15 cards ainda não venceram e entram como treino/);
    await expect(pergunta(page)).not.toHaveText(/Pergunta futuro/);
  });

  test("resposta de card que não venceu NÃO vai pro servidor", async ({ page }) => {
    const respondidos = await abrirDeckInteiro(page);
    await acertarTudo(page);

    // 9 contam (3 vencidos + 2 críticos + 4 novos); os 6 em dia são treino.
    await expect.poll(() => respondidos.length).toBe(9);
    for (const id of [100, 101, 102, 103, 104, 105]) expect(respondidos).not.toContain(id);
    await expect(page.getByText(/6 cards ainda não tinham vencido e entraram como treino/)).toBeVisible();
  });

  test("o resumo não anuncia avanço de card de treino", async ({ page }) => {
    await abrirDeckInteiro(page);
    await acertarTudo(page);
    // 4 novos avançam pra Validando; os 6 de treino (repetitions 2) não
    // podem aparecer em contagem nenhuma de avanço.
    await expect(page.locator(".sessao-stat.ambar .sessao-stat-valor")).toHaveText("+4");
  });

  test("sem card de treino, nenhum aviso de treino aparece", async ({ page }) => {
    await abrirDeck(page, { cards: BARALHO.filter(c => c.vence_em !== FUTURO) });
    await page.getByRole("button", { name: "Outros modos" }).click();
    await page.locator(".modo-opcao", { hasText: "Aprender" }).click();
    await expect(page.locator(".quiz-opcao").first()).toBeVisible();
    await expect(page.locator(".aviso-treino")).toHaveCount(0);
  });
});
