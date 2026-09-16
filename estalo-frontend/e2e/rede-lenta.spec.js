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
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

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
