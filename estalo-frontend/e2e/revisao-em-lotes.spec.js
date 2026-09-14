/**
 * A Revisão Geral ("Estudar Tudo") vem em lotes -- e a tela precisa dizer.
 *
 * O backend entrega no máximo 15 cards por chamada a /study/global-reviews,
 * e a Home diz "15+ esperando". Quem tinha 40 vencidos terminava o lote,
 * encontrava só "Voltar à Home" como saída, voltava, via "25 esperando" e
 * clicava de novo -- sem nada explicar que a sessão era um pedaço. O
 * coração do app tinha um degrau invisível.
 *
 * Agora, depois de salvar, o app pergunta ao servidor o que sobrou e:
 *   - sobrando: "Continuar · N restantes" vira a ação principal, e o
 *     próximo lote começa sem passar pela Home;
 *   - zerou: a tela diz isso, em vez de calar.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };
const DECK = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 3, memorization_pct: 0 };
const STATS = { total_cards: 3, criticos: 3, hoje: 0, novos: 0, validando: 0, dominados: 0, new_cards: 0, validating: 0, dominated: 0, due_now: 3 };

function loteGlobal(ids) {
  return ids.map(i => ({
    card_id: i,
    front: `Pergunta ${i}`,
    back: `CERTA ${i}`,
    due_date: "2026-01-01T00:00:00",
    repetitions: 2,
    options: [`errada A${i}`, `errada B${i}`, `errada C${i}`],
    explanation: "Explicação do card.",
    deck_name: "Intune",
    deck_color: null,
  }));
}

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/**
 * Simula o servidor de verdade: /study/global-reviews devolve os cards
 * VENCIDOS que ainda não foram respondidos, até 15 por vez, e cada
 * /answer tira o card da lista. Modelar por contagem de chamadas não
 * serve -- o StrictMode do React em dev dispara o carregamento duas
 * vezes, e o lote da sessão sumiria no segundo disparo.
 *
 * `primeiroLote` deixa a primeira sessão curta (não vale responder 15
 * cards por teste); depois da primeira resposta gravada, vale a regra
 * do servidor.
 */
async function abrirRevisaoGeral(page, { primeiroLote, vencidos }) {
  const contagem = { gravadas: 0 };
  const respondidos = new Set();
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json([{ ...PASTA, children: [] }]);
    if (p === "/decks") return json([DECK]);
    if (p === "/study/decks/stats") return json({ 10: STATS });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    if (p === "/study/global-reviews") {
      if (respondidos.size === 0) return json(loteGlobal(primeiroLote));
      return json(loteGlobal(vencidos.filter(i => !respondidos.has(i)).slice(0, 15)));
    }
    const resposta = p.match(/^\/study\/cards\/(\d+)\/answer$/);
    if (resposta) {
      contagem.gravadas += 1;
      respondidos.add(Number(resposta[1]));
      return json({ card_id: Number(resposta[1]), interval: 1, ease_factor: 2.5, repetitions: 3, next_due: "2026-01-02T00:00:00", status: "dominado" });
    }
    return json({});
  });

  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto("/");
  await page.getByRole("button", { name: "Estudar Tudo" }).click();
  await expect(page.locator(".quiz-opcao").first()).toBeVisible();
  return contagem;
}

async function acertar(page) {
  const opcoes = page.locator(".quiz-opcao");
  const total = await opcoes.count();
  for (let i = 0; i < total; i++) {
    if ((await opcoes.nth(i).textContent()).includes("CERTA")) { await opcoes.nth(i).click(); break; }
  }
  await expect(page.locator(".quiz-explicacao")).toBeVisible();
  await page.getByRole("button", { name: /Próxim|Ver resultado|Finalizar/ }).click();
  await page.waitForTimeout(450);
}

async function terminarLote(page, n) {
  for (let i = 0; i < n; i++) await acertar(page);
  await expect(page.locator(".sessao-resumo")).toBeVisible();
}

test.describe("Revisão Geral em lotes", () => {
  test("com cards sobrando, a tela diz quantos e oferece continuar", async ({ page }) => {
    const contagem = await abrirRevisaoGeral(page, { primeiroLote: [100, 101], vencidos: [100, 101, 102] });
    await terminarLote(page, 2);

    await expect(page.locator(".sessao-restante")).toHaveText(/Ainda tem 1 card vencido esperando/);
    await expect(page.locator(".sessao-acoes .botao-principal")).toHaveText("Continuar · 1 restante");
    // Voltar continua ali, só deixou de ser a única saída.
    await expect(page.getByRole("button", { name: "Voltar à Home" })).toBeVisible();
    expect(contagem.gravadas, "o lote precisa ter sido salvo antes de perguntar o que sobrou").toBe(2);
  });

  test("continuar começa o próximo lote na hora, sem passar pela Home", async ({ page }) => {
    const contagem = await abrirRevisaoGeral(page, { primeiroLote: [100, 101], vencidos: [100, 101, 102] });
    await terminarLote(page, 2);
    await page.locator(".sessao-acoes .botao-principal").click();

    // É uma sessão nova, do card que faltava -- não uma repetição da anterior.
    await expect(page.locator(".cartao-texto")).toContainText("Pergunta 102");
    await expect(page).toHaveURL(/revisao-global/);
    await terminarLote(page, 1);

    // O segundo lote também vale: gravou no servidor.
    expect(contagem.gravadas).toBe(3);
    await expect(page.locator(".sessao-restante")).toHaveText("Você zerou a revisão de hoje.");
    await expect(page.locator(".sessao-acoes .botao-principal")).toHaveText("Voltar à Home");
  });

  test("quando vêm 15, o número é o mesmo '15+' da Home", async ({ page }) => {
    const vencidos = [100, ...Array.from({ length: 15 }, (_, i) => 200 + i)];
    await abrirRevisaoGeral(page, { primeiroLote: [100], vencidos });
    await terminarLote(page, 1);

    await expect(page.locator(".sessao-acoes .botao-principal")).toHaveText("Continuar · 15+ restantes");
  });

  test("sem rede depois de salvar, a tela não promete nada", async ({ page }) => {
    // As respostas ficam na fila offline; perguntar o que sobrou devolveria
    // os mesmos cards. A tela fica como antes: só "Voltar à Home".
    await abrirRevisaoGeral(page, { primeiroLote: [100, 101], vencidos: [100, 101, 102] });
    await page.route(/\/study\/cards\/\d+\/answer$/, route => route.abort("internetdisconnected"));
    await terminarLote(page, 2);
    await page.waitForTimeout(700);

    await expect(page.locator(".sessao-restante")).toHaveCount(0);
    await expect(page.locator(".sessao-acoes .botao-principal")).toHaveText("Voltar à Home");
  });
});
