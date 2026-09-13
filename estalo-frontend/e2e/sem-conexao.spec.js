/**
 * Como o app se comporta quando não dá pra falar com o servidor.
 *
 * Existe por causa de um relato: "aparecem mensagens de sem internet toda
 * hora". Reproduzido em 2026-09-13, e o problema não era o excesso de
 * avisos -- era o app estar lendo a realidade errada.
 *
 * `navigator.onLine` só diz se existe *alguma* rede ligada. Wi-Fi
 * conectado sem internet, portal cativo de hotel, sinal fantasma de
 * celular: em todos, `onLine` é `true` e nenhuma request completa. O app
 * ficava no pior dos dois mundos -- a faixa calma NÃO aparecia (ela olhava
 * onLine) e um toast VERMELHO saía a cada tela, porque cada navegação
 * refaz as chamadas e cada falha disparava o aviso.
 *
 * Medido antes: abrir o início, entrar numa pasta e voltar = 3 toasts,
 * zero faixa. E a tela tinha funcionado inteira, desenhada da cópia local.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };
const DECK = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 2, memorization_pct: 0 };
const STATS = { total_cards: 2, criticos: 1, hoje: 0, novos: 1, validando: 0, dominados: 0, new_cards: 1, validating: 0, dominated: 0, due_now: 1 };
const CARDS = [
  { id: 100, front: "P1", back: "R1", source: "manual", repetitions: 1, options: ["a", "b", "c"], explanation: "e" },
  { id: 101, front: "P2", back: "R2", source: "manual", repetitions: 1, options: ["a", "b", "c"], explanation: "e" },
];

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/**
 * Deixa o app pronto e com um deck baixado. `ref.corta` derruba a API a
 * qualquer momento -- SEM mexer em navigator.onLine, que é justamente o
 * ponto: o navegador continua jurando que está online.
 */
async function prepararComDeckBaixado(page) {
  const ref = { corta: false };
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    if (ref.corta) return route.abort("internetdisconnected");
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev", created_at: "2026-03-05T14:20:00" });
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
  await page.goto("/?folder=2");
  await expect(page.locator(".lista-deck").first()).toBeVisible();
  await page.locator(".lista-deck").filter({ hasText: "Intune" }).getByTitle(/Baixar deck/).click();
  await expect(page.locator(".lista-deck").filter({ hasText: "Intune" }).getByTitle(/Disponível offline/)).toBeVisible();
  return ref;
}

const faixa = (page) => page.locator(".offline-banner");
const toasts = (page) => page.locator(".toast-global");

test.describe("Sem conexão com o servidor", () => {
  test("navegar várias telas não vira uma fila de avisos", async ({ page }) => {
    // O relato original, medido. Antes: 3 toasts, zero faixa.
    const ref = await prepararComDeckBaixado(page);
    ref.corta = true;

    for (const rota of ["/", "/?folder=2", "/"]) {
      await page.goto(rota);
      await page.waitForTimeout(900);
      await expect(toasts(page), `a tela ${rota} soltou aviso de erro`).toHaveCount(0);
    }
    // Um sinal só, calmo, que dura enquanto durar o problema.
    await expect(faixa(page)).toBeVisible();
  });

  test("o aviso aparece mesmo com o navegador jurando que está online", async ({ page }) => {
    // Wi-Fi de hotel, portal cativo, sinal fantasma. navigator.onLine
    // continua true aqui de propósito -- ninguém mexeu nele.
    const ref = await prepararComDeckBaixado(page);
    ref.corta = true;
    await page.goto("/");
    await page.waitForTimeout(900);

    expect(await page.evaluate(() => navigator.onLine), "o teste só vale com onLine=true").toBe(true);
    await expect(faixa(page)).toBeVisible();
  });

  test("a tela que funcionou pela cópia local não mostra erro nenhum", async ({ page }) => {
    // O pior sintoma: o app desenhava tudo do retrato local e AINDA ASSIM
    // dava erro vermelho na cara de quem não tinha perdido nada.
    const ref = await prepararComDeckBaixado(page);
    ref.corta = true;
    await page.goto("/");
    await page.waitForTimeout(900);

    await expect(page.locator(".pasta-card, .lista-pasta").first()).toBeVisible();
    await expect(page.locator(".visao-geral")).toBeVisible();
    await expect(toasts(page)).toHaveCount(0);
    await expect(page.locator(".erro")).toHaveCount(0);
  });

  test("quando o servidor volta, a faixa some sozinha", async ({ page }) => {
    const ref = await prepararComDeckBaixado(page);
    ref.corta = true;
    await page.goto("/");
    await expect(faixa(page)).toBeVisible();

    ref.corta = false;
    await page.goto("/");
    await page.waitForTimeout(900);
    // Não depende de nenhum evento do navegador: a request que respondeu
    // é a prova de que voltou.
    await expect(faixa(page)).toHaveCount(0);
    await expect(toasts(page)).toHaveCount(0);
  });

  test("os botões que precisam de rede ficam travados nesse estado", async ({ page }) => {
    // Antes ficavam clicáveis: dependiam de navigator.onLine, que estava
    // true. Clicar dava erro depois do clique, que é o pior momento.
    const ref = await prepararComDeckBaixado(page);
    ref.corta = true;
    await page.goto("/?folder=2");
    await expect(page.locator(".lista-deck").first()).toBeVisible();

    await expect(page.getByRole("button", { name: "+ Novo Deck" })).toBeDisabled();
    const linha = page.locator(".lista-deck").filter({ hasText: "Intune" });
    await expect(linha.getByRole("button", { name: "Excluir deck" })).toBeDisabled();
  });
});
