/**
 * Rede lenta: o estudo não pode ficar refém do servidor.
 *
 * O app só tinha duas noções -- "respondeu" ou "caiu" -- e o mundo real
 * fica quase sempre no meio. Medido com uma rede que responde em 25s (não
 * cai, só demora), num deck já baixado: a tela de resultado do Aprender
 * ficava com "Salvando…" travado por 50s, sendo que a caixa de saída já
 * tinha as respostas a salvo no aparelho. A espera não protegia nada.
 *
 * Aqui cada /answer leva SEGUNDOS pra responder, e a tela precisa liberar
 * mesmo assim -- com o "Continuar" da Fila Única aparecendo depois, quando
 * a sincronização terminar por trás.
 *
 * E as LEITURAS: com a cópia baixada, abrir o deck e começar a estudar
 * levava os mesmos 25s (a cópia só entrava quando o fetch REJEITAVA, e
 * numa rede lenta ele não rejeita, fica pendurado). Agora leitura com
 * cópia local tem prazo (3s): passou, serve a cópia e a faixa vira
 * "Conexão lenta". Sem cópia, continua esperando -- um erro aos 3s seria
 * pior do que os cards chegarem aos 25s.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";
import { abrirLogado } from "./auditoria-layout.js";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };
const DECK = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 3, memorization_pct: 0 };
const STATS = { total_cards: 3, criticos: 3, hoje: 0, novos: 0, validando: 0, dominados: 0, new_cards: 0, validating: 0, dominated: 0, due_now: 3 };

const lote = (ids) => ids.map(i => ({
  card_id: i, front: `Pergunta ${i}`, back: `CERTA ${i}`, due_date: "2026-01-01T00:00:00", repetitions: 2,
  options: [`errada A${i}`, `errada B${i}`, `errada C${i}`], explanation: "Explicação.", deck_name: "Intune", deck_color: null,
}));

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** Servidor simulado em que cada /answer demora `demoraAnswerMs`. */
async function abrirRevisaoGeral(page, { demoraAnswerMs }) {
  const respondidos = new Set();
  const vencidos = [100, 101, 102];
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
      if (respondidos.size === 0) return json(lote([100, 101]));
      return json(lote(vencidos.filter(i => !respondidos.has(i))));
    }
    const m = p.match(/^\/study\/cards\/(\d+)\/answer$/);
    if (m) {
      await new Promise(r => setTimeout(r, demoraAnswerMs));
      respondidos.add(Number(m[1]));
      return json({ card_id: Number(m[1]), interval: 1, ease_factor: 2.5, repetitions: 3, next_due: "2026-01-02T00:00:00", status: "dominado" });
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
}

async function acertar(page) {
  const opcoes = page.locator(".quiz-opcao");
  const n = await opcoes.count();
  for (let i = 0; i < n; i++) {
    if ((await opcoes.nth(i).textContent()).includes("CERTA")) { await opcoes.nth(i).click(); break; }
  }
  await expect(page.locator(".quiz-explicacao")).toBeVisible();
  await page.getByRole("button", { name: /Próxim|Ver resultado|Finalizar/ }).click();
  await page.waitForTimeout(450);
}

test.describe("Rede lenta", () => {
  test("a tela de resultado libera em segundos, não quando o servidor quiser", async ({ page }) => {
    // 2 respostas x 6s em série = 12s de servidor. A tela não pode esperar isso.
    await abrirRevisaoGeral(page, { demoraAnswerMs: 6000 });
    await acertar(page);
    const inicio = Date.now();
    await acertar(page);
    await expect(page.locator(".sessao-resumo")).toBeVisible();

    const botao = page.locator(".sessao-acoes .botao-principal");
    await expect(botao).toBeEnabled({ timeout: 6000 });
    const esperou = (Date.now() - inicio) / 1000;
    expect(esperou, `esperou ${esperou.toFixed(1)}s com "Salvando…"`).toBeLessThan(5);
    await expect(botao).toHaveText("Voltar à Home");
  });

  test("quando a sincronização termina por trás, o 'Continuar' ainda aparece", async ({ page }) => {
    await abrirRevisaoGeral(page, { demoraAnswerMs: 2500 });
    await acertar(page);
    await acertar(page);
    await expect(page.locator(".sessao-acoes .botao-principal")).toBeEnabled({ timeout: 6000 });
    // Liberou antes de o servidor confirmar as duas (5s no total)...
    await expect(page.locator(".sessao-restante")).toHaveCount(0);
    // ...e, quando confirmou, o que sobrou aparece sem a pessoa fazer nada.
    await expect(page.locator(".sessao-restante")).toHaveText(/Ainda tem 1 card vencido/, { timeout: 10000 });
    await expect(page.locator(".sessao-acoes .botao-principal")).toHaveText("Continuar · 1 restante");
  });
});

/**
 * Rede que não cai, só demora: toda chamada de API leva `atrasoMs`.
 * `ref.atraso` pode ser mudado no meio do teste (0 = rede boa de novo).
 */
async function ficarLenta(page, atrasoMs) {
  const ref = { atraso: atrasoMs };
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    if (ref.atraso > 0) await new Promise(r => setTimeout(r, ref.atraso));
    return route.fallback(); // cai no mock de auditoria-layout, registrado antes
  });
  return ref;
}

const faixa = (page) => page.locator(".offline-banner");

test.describe("Rede lenta — leituras", () => {
  test("deck baixado abre da cópia local em segundos, e a faixa diz por quê", async ({ page }) => {
    await abrirLogado(page, "/?folder=2");
    const linha = page.locator(".lista-deck").filter({ hasText: "Autopilot" });
    await expect(linha).toBeVisible({ timeout: 15000 });
    await linha.getByTitle(/Baixar deck/).click();
    await expect(linha.getByTitle(/Disponível offline/)).toBeVisible();

    await ficarLenta(page, 20000);
    const inicio = Date.now();
    await linha.locator(".lista-info").click();
    await expect(page.locator(".item-card").first()).toBeVisible({ timeout: 8000 });
    const abriu = (Date.now() - inicio) / 1000;
    expect(abriu, `abrir o deck baixado levou ${abriu.toFixed(1)}s`).toBeLessThan(6);

    await expect(faixa(page)).toHaveText(/Conexão lenta/);
    // Rede lenta conta como indisponível pro que precisa dela: mesmo
    // tratamento do offline, em vez de clicar e esperar 20s.
    await expect(page.getByRole("button", { name: "Outros modos" })).toBeVisible();

    // E começar a estudar também não espera o servidor.
    const t2 = Date.now();
    await page.getByRole("button", { name: /Aprender|Estudar hoje|Estudar críticos/ }).click();
    await expect(page.locator(".quiz-opcao").first()).toBeVisible({ timeout: 8000 });
    expect((Date.now() - t2) / 1000).toBeLessThan(6);
  });

  test("sem cópia baixada, continua esperando em vez de dar erro", async ({ page }) => {
    // Um erro aos 3s seria pior que os cards chegarem aos 5s.
    await abrirLogado(page, "/?folder=2");
    const linha = page.locator(".lista-deck").filter({ hasText: "Autopilot" });
    await expect(linha).toBeVisible({ timeout: 15000 });

    await ficarLenta(page, 5000);
    await linha.locator(".lista-info").click();
    await expect(page.locator(".item-card").first()).toBeVisible({ timeout: 15000 });
    await expect(page.locator(".erro")).toHaveCount(0);
  });

  test("quando a rede volta a responder rápido, a faixa some sozinha", async ({ page }) => {
    await abrirLogado(page, "/?folder=2");
    const linha = page.locator(".lista-deck").filter({ hasText: "Autopilot" });
    await expect(linha).toBeVisible({ timeout: 15000 });
    await linha.getByTitle(/Baixar deck/).click();
    await expect(linha.getByTitle(/Disponível offline/)).toBeVisible();

    const rede = await ficarLenta(page, 20000);
    await linha.locator(".lista-info").click();
    await expect(faixa(page)).toHaveText(/Conexão lenta/, { timeout: 8000 });

    rede.atraso = 0;
    await page.getByRole("button", { name: "← Voltar" }).click();
    await expect(page.locator(".lista-deck").first()).toBeVisible({ timeout: 15000 });
    // Nenhum evento do navegador: a leitura que respondeu no prazo é a prova.
    await expect(faixa(page)).toHaveCount(0);
  });
});

/**
 * Deck em que só um card tem quiz pronto: o outro dispararia a auto-cura
 * (POST /study/cards/enrich, a chamada de IA mais demorada do app) antes
 * de a sessão começar.
 */
async function abrirDeckComCardSemQuiz(page, { atrasoRedeMs = 0, atrasoIaMs = 0 } = {}) {
  const chamadas = { enrich: 0 };
  const CARDS = [
    { id: 100, front: "Com quiz", back: "CERTA 1", source: "ai", repetitions: 0, options: ["a", "b", "c"], explanation: "e" },
    { id: 101, front: "Sem quiz", back: "CERTA 2", source: "manual", repetitions: 0, options: null, explanation: null },
  ];
  const DECK10 = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 2, memorization_pct: 0 };
  const STATS2 = { total_cards: 2, criticos: 0, hoje: 0, novos: 2, validando: 0, dominados: 0, new_cards: 2, validating: 0, dominated: 0, due_now: 2 };
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/study/cards/enrich") {
      chamadas.enrich += 1;
      await new Promise(r => setTimeout(r, atrasoIaMs));
      return json({ enriched: [{ card_id: 101, options: ["x", "y", "z"], explanation: "gerada" }], falhas: [] });
    }
    if (atrasoRedeMs > 0) await new Promise(r => setTimeout(r, atrasoRedeMs));
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json([{ ...PASTA, children: [] }]);
    if (p === "/decks") return json([DECK10]);
    if (p === "/study/decks/stats") return json({ 10: STATS2 });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    if (/^\/decks\/\d+\/cards$/.test(p)) return json(CARDS);
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(STATS2);
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  return chamadas;
}

test.describe("Rede lenta — IA antes do estudo", () => {
  test("com a rede lenta, a auto-cura do quiz nem é tentada", async ({ page }) => {
    const chamadas = await abrirDeckComCardSemQuiz(page);
    await page.goto("/?folder=2");
    const linha = page.locator(".lista-deck").first();
    await expect(linha).toBeVisible({ timeout: 15000 });
    await linha.getByTitle(/Baixar deck/).click();
    await expect(linha.getByTitle(/Disponível offline/)).toBeVisible();
    await linha.locator(".lista-info").click();
    await expect(page.locator(".item-card").first()).toBeVisible({ timeout: 15000 });

    // A rede fica lenta AQUI: a leitura dos cards vai estourar o prazo e
    // ser servida da cópia; a IA, que demoraria 25s, não pode nem entrar.
    await ficarLenta(page, 25000);
    const inicio = Date.now();
    await page.getByRole("button", { name: /Aprender|Estudar hoje|Estudar críticos/ }).click();
    await expect(page.locator(".quiz-opcao").first()).toBeVisible({ timeout: 8000 });
    expect((Date.now() - inicio) / 1000).toBeLessThan(6);
    expect(chamadas.enrich, "a IA não pode ser chamada com a rede lenta").toBe(0);
    // A sessão começou só com o card que tinha quiz.
    await expect(page.locator(".quiz-progresso-contador")).toContainText(/de 1\b/);
  });

  test("com a rede boa mas a IA demorando, a sessão começa mesmo assim", async ({ page }) => {
    // 40s de IA: sem prazo, "Preparando seu material…" ficava lá até o
    // servidor desistir. O prazo é 20s; a sessão começa com o que tem quiz.
    test.setTimeout(60000);
    const chamadas = await abrirDeckComCardSemQuiz(page, { atrasoIaMs: 40000 });
    await page.goto("/?folder=2");
    await expect(page.locator(".lista-deck .lista-info").first()).toBeVisible({ timeout: 15000 });
    await page.locator(".lista-deck .lista-info").first().click();
    await expect(page.locator(".item-card").first()).toBeVisible({ timeout: 15000 });

    const inicio = Date.now();
    await page.getByRole("button", { name: /Aprender|Estudar hoje|Estudar críticos/ }).click();
    await expect(page.locator(".quiz-opcao").first()).toBeVisible({ timeout: 30000 });
    const esperou = (Date.now() - inicio) / 1000;
    expect(esperou).toBeGreaterThan(15); // tentou de verdade...
    expect(esperou).toBeLessThan(26);    // ...mas não esperou os 40s
    expect(chamadas.enrich, "tentou a IA de verdade").toBeGreaterThanOrEqual(1); // 2 em dev: StrictMode monta duas vezes
    // E IA lenta não é rede lenta: nada de faixa.
    await expect(faixa(page)).toHaveCount(0);
  });
});
