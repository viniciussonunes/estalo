/**
 * O medidor de progresso do modo Aprender.
 *
 * Por que existe: o rótulo dizia "Card 2 de 6" e o número era outra coisa
 * -- cards CONCLUÍDOS, não perguntas respondidas. Errar devolve o card pra
 * fila, então o número parava. Medido no código antigo: 1 acerto + 2 erros
 * deixava a tela na 4ª pergunta ainda dizendo "Card 2 de 6". Quem errava
 * concluía que estava patinando.
 *
 * E o aviso que deveria explicar isso ("+N↺") NUNCA aparecia: a conta era
 * `fila.length - ids distintos`, e como errar MOVE o card dentro da fila
 * em vez de duplicá-lo, dava sempre zero. Código morto que só apareceu
 * quando alguém foi medir em vez de ler.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };

/** Baralho de N cards onde a resposta certa é sempre reconhecível pelo
 *  texto ("CERTA"), pra o teste conseguir errar de propósito. */
function baralho(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: 100 + i,
    front: `Pergunta ${i + 1}`,
    back: `CERTA ${i + 1}`,
    source: "manual",
    repetitions: 1,
    options: [`errada A${i + 1}`, `errada B${i + 1}`, `errada C${i + 1}`],
    explanation: "Explicação do card.",
  }));
}

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

async function comecarSessao(page, quantosCards) {
  const cards = baralho(quantosCards);
  const deck = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: quantosCards, memorization_pct: 0 };
  const stats = { total_cards: quantosCards, criticos: quantosCards, hoje: 0, novos: 0, validando: quantosCards, dominados: 0, new_cards: 0, validating: quantosCards, dominated: 0, due_now: quantosCards };

  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json([{ ...PASTA, children: [] }]);
    if (p === "/decks") return json([deck]);
    if (p === "/study/decks/stats") return json({ 10: stats });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    if (/^\/decks\/\d+\/cards$/.test(p)) return json(cards);
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(stats);
    if (/^\/study\/cards\/\d+\/answer$/.test(p)) {
      return json({ card_id: 100, interval: 1, ease_factor: 2.5, repetitions: 1, next_due: "2026-01-02T00:00:00", status: "validando" });
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
  await page.getByRole("button", { name: /Aprender|Estudar hoje|Estudar críticos/ }).click();
  await expect(page.locator(".quiz-opcao").first()).toBeVisible();
}

/** Responde a questão da vez, de propósito certo ou errado. */
async function responder(page, certo) {
  const opcoes = page.locator(".quiz-opcao");
  const total = await opcoes.count();
  let alvo = 0;
  for (let i = 0; i < total; i++) {
    const texto = await opcoes.nth(i).textContent();
    if (texto.includes("CERTA") === certo) { alvo = i; break; }
  }
  await opcoes.nth(alvo).click();
  await expect(page.locator(".quiz-explicacao")).toBeVisible();
  await page.getByRole("button", { name: /Próxim|Ver resultado|Finalizar/ }).click();
  await page.waitForTimeout(450);
}

const contador = (page) => page.locator(".quiz-progresso-contador");
const aviso = (page) => page.locator(".quiz-repetindo");

test.describe("Progresso no modo Aprender", () => {
  test("o rótulo diz o que o número é", async ({ page }) => {
    await comecarSessao(page, 6);
    // Não é "Card 1 de 6": nada foi concluído ainda. O texto antigo
    // prometia um contador de perguntas que nunca existiu.
    await expect(contador(page)).toHaveText("0 de 6 concluídos");
    await responder(page, true);
    await expect(contador(page)).toHaveText("1 de 6 concluídos");
  });

  test("errar não faz o progresso andar — e a tela explica por quê", async ({ page }) => {
    await comecarSessao(page, 6);
    await responder(page, true);
    await expect(contador(page)).toHaveText("1 de 6 concluídos");

    await responder(page, false);
    // O número PARADO está certo: aquele card não foi concluído. O que
    // faltava era dizer isso -- é o que o aviso faz.
    await expect(contador(page)).toHaveText("1 de 6 concluídos");
    await expect(aviso(page), "o aviso de card que volta não apareceu").toHaveText("↺ 1 volta");

    await responder(page, false);
    await expect(aviso(page)).toHaveText("↺ 2 voltam");
  });

  test("reacertar o card tira ele da lista de pendentes", async ({ page }) => {
    await comecarSessao(page, 3);
    await responder(page, false);        // erra o 1º
    await expect(aviso(page)).toHaveText("↺ 1 volta");
    await responder(page, true);         // acerta o 2º
    await responder(page, true);         // acerta o 3º
    await expect(aviso(page)).toHaveText("↺ 1 volta");
    await responder(page, true);         // reacerta o 1º
    // Some quando não há mais nada esperando -- se ficasse, viraria um
    // alarme permanente sobre um problema que já passou.
    await expect(aviso(page)).toHaveCount(0);
  });

  test("no Rever vilões o contador conta os vilões, não a sessão", async ({ page }) => {
    // Antes: a fila virava só os vilões mas o total continuava sendo o da
    // sessão, então uma prática de 1 card dizia "Card 3 de 3" -- ou seja,
    // anunciava o fim bem na hora de recomeçar.
    await comecarSessao(page, 3);
    await responder(page, false);  // erra o 1º
    await responder(page, true);
    await responder(page, true);
    await responder(page, false);  // erra o 1º de novo -> vira vilão
    await responder(page, true);

    const rever = page.getByRole("button", { name: /Rever vil/i });
    await expect(rever).toBeVisible();
    await rever.click();

    await expect(contador(page)).toHaveText("Vilão 1 de 1");
    // Na prática de vilões todo card é um erro; repetir isso num aviso
    // seria dizer o óbvio.
    await expect(aviso(page)).toHaveCount(0);
  });
});
