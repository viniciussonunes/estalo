/**
 * A tela de fim de sessão do Aprender.
 *
 * Por que existe: a tela oferecia "Consolidar Domínio", e esse botão
 * refazia a sessão VALENDO -- respondia os mesmos cards no servidor
 * minutos depois de a pessoa tê-los aprendido. Com ignorar_elegibilidade
 * ligado (o modo Aprender manda sempre), o SM-2 tratava aquilo como uma
 * revisão espaçada real. Calculado com o próprio sm2.py do backend:
 *
 *   card novo, acertou        -> reps 1, intervalo 1 dia   (volta amanhã)
 *   clicou "Consolidar" agora -> reps 2, intervalo 6 dias  (Dominado)
 *
 * Ou seja: a tela chamava de "consolidar" o ato de PULAR a consolidação,
 * apagando a revisão do dia seguinte com base num acerto ainda em memória
 * de trabalho. Era o único lugar do app onde a interface empurrava o
 * usuário contra o próprio algoritmo.
 *
 * O teste que segura isso é o de contar chamadas a /answer: praticar de
 * novo não pode escrever nada.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };

/** Cards NOVOS (repetitions 0) — é o estado que fazia a tela antiga
 *  oferecer o "Consolidar Domínio". */
function baralhoNovo(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: 100 + i,
    front: `Pergunta ${i + 1}`,
    back: `CERTA ${i + 1}`,
    source: "manual",
    repetitions: 0,
    options: [`errada A${i + 1}`, `errada B${i + 1}`, `errada C${i + 1}`],
    explanation: "Explicação do card.",
  }));
}

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** Devolve um contador vivo de respostas gravadas no servidor. */
async function comecarSessao(page, quantosCards) {
  const cards = baralhoNovo(quantosCards);
  const deck = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: quantosCards, memorization_pct: 0 };
  const stats = { total_cards: quantosCards, criticos: 0, hoje: 0, novos: quantosCards, validando: 0, dominados: 0, new_cards: quantosCards, validating: 0, dominated: 0, due_now: quantosCards };
  const gravadas = { total: 0 };

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
      gravadas.total += 1;
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
  return gravadas;
}

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

async function terminarSessao(page, n) {
  for (let i = 0; i < n; i++) await responder(page, true);
  await expect(page.locator(".sessao-resumo")).toBeVisible();
  await page.waitForTimeout(600); // deixa o _salvarProgresso terminar
}

test.describe("Fim de sessão no Aprender", () => {
  test("diz quando os cards voltam, em vez de prometer domínio", async ({ page }) => {
    await comecarSessao(page, 3);
    await terminarSessao(page, 3);

    await expect(page.locator(".sessao-proximo")).toHaveText("3 cards novos aprendidos. Eles voltam amanhã.");
    // O texto antigo prometia o que o algoritmo não entrega.
    await expect(page.locator(".sessao-resumo")).not.toContainText(/consolidar/i);
    await expect(page.locator(".sessao-resumo")).not.toContainText(/DOMÍNIO permanente/i);
  });

  test("a ação principal é terminar, não recomeçar", async ({ page }) => {
    await comecarSessao(page, 3);
    await terminarSessao(page, 3);
    // Terminar a sessão é o sucesso. Antes, o botão de destaque era o que
    // mandava refazer tudo -- e o de sair era o secundário, tom de consolo.
    await expect(page.locator(".sessao-acoes .botao-principal")).toHaveText(/Voltar ao deck/);
    await expect(page.getByRole("button", { name: "Praticar de novo" })).toBeVisible();
  });

  test("praticar de novo NÃO grava nada no servidor", async ({ page }) => {
    // Este é o teste que importa. Antes, este mesmo caminho reenviava uma
    // resposta por card e empurrava o agendamento de 1 dia pra 6.
    const gravadas = await comecarSessao(page, 3);
    await terminarSessao(page, 3);
    expect(gravadas.total, "a sessão real precisa ter gravado").toBe(3);

    await page.getByRole("button", { name: "Praticar de novo" }).click();
    await expect(page.locator(".quiz-opcao").first()).toBeVisible();
    await responder(page, true);
    await responder(page, true);
    await responder(page, true);
    await expect(page.locator(".sessao-resumo")).toBeVisible();
    await page.waitForTimeout(700);

    expect(gravadas.total, "praticar de novo mexeu no agendamento").toBe(3);
  });

  test("durante a prática a tela avisa que não conta", async ({ page }) => {
    await comecarSessao(page, 3);
    await terminarSessao(page, 3);
    await page.getByRole("button", { name: "Praticar de novo" }).click();
    await expect(page.locator(".modo-label")).toHaveText("Praticando — não conta");
    // Voltar não sai da tela: devolve pro resumo da sessão que já contou.
    await page.getByRole("button", { name: /Voltar ao resumo/ }).click();
    await expect(page.locator(".sessao-resumo")).toBeVisible();
  });

  test("a prática não infla o placar da sessão", async ({ page }) => {
    await comecarSessao(page, 3);
    await terminarSessao(page, 3);
    const antes = await page.locator(".anel-texto, .sessao-resumo").first().textContent();

    await page.getByRole("button", { name: "Praticar de novo" }).click();
    for (let i = 0; i < 3; i++) await responder(page, true);
    await expect(page.locator(".sessao-resumo")).toBeVisible();
    await page.waitForTimeout(500);

    // O resumo é da sessão real. Somar de novo os acertos da prática
    // levaria a porcentagem a passar de 100%.
    const depois = await page.locator(".anel-texto, .sessao-resumo").first().textContent();
    expect(depois).toBe(antes);

    const pct = Number((depois.match(/(\d+)%/) ?? [])[1]);
    expect(Number.isFinite(pct), "não achei a porcentagem no resumo").toBe(true);
    expect(pct, "a precisão passou de 100% -- a prática entrou na conta").toBeLessThanOrEqual(100);
  });
});
