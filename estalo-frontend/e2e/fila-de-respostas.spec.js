/**
 * A fila de respostas de estudo (outbox.js) diante de um servidor hostil.
 *
 * Por que existe: a fila descartava QUALQUER resposta que o servidor não
 * aceitasse de primeira, e isso incluía o caso mais cruel -- 401. Cenário
 * real: a pessoa estuda offline no celular; nesse meio-tempo o token
 * expira, ou ela troca a senha em outro aparelho (token_version derruba as
 * sessões). Volta a conexão, a fila sobe, leva 401 em tudo, e o estudo da
 * sessão inteira vai pro lixo com um toast de consolo. A resposta era
 * válida; faltava um crachá novo.
 *
 * Reproduzido em 2026-10-13 numa varredura: 2 respostas na fila, 2
 * tentativas, fila zerada, nada reenviado. Mesmo roteiro com 500.
 *
 * Agora 401/403/429/5xx ADIAM (e reenviar é seguro: o X-Request-ID torna
 * a chamada idempotente no backend); 404/422 continuam sendo descartados,
 * porque nunca vão passar e travariam a fila pra sempre.
 *
 * O 401 tem um segundo efeito, de outra camada: ele encerra a sessão (ver
 * sessao-expirada.spec.js). Então a fila fica guardada esperando o próximo
 * login -- quem destrava o 401 é logar de novo, não tentar de novo.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const CHAVE_FILA = "estalo_outbox_respostas";

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

const DUAS_RESPOSTAS = [
  { id: "r1", userId: "1", cardId: 100, quality: 4, ignorarElegibilidade: true, respondidoEm: "2026-10-13T10:00:00.000Z" },
  { id: "r2", userId: "1", cardId: 101, quality: 5, ignorarElegibilidade: true, respondidoEm: "2026-10-13T10:01:00.000Z" },
];

/**
 * Abre o app com duas respostas já na fila, como se tivessem sido dadas
 * offline. `ref.statusDoAnswer` controla o que o servidor responde; mudar
 * pra 200 simula o problema passando.
 */
async function abrirComFilaPendente(page, statusInicial) {
  const ref = { statusDoAnswer: statusInicial, tentativas: 0, recebidas: [] };
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(c) });
    if (/^\/study\/cards\/\d+\/answer$/.test(p)) {
      ref.tentativas += 1;
      if (ref.statusDoAnswer !== 200) return json({ detail: "recusado" }, ref.statusDoAnswer);
      ref.recebidas.push(JSON.parse(req.postData() || "{}"));
      return json({ card_id: 100, interval: 1, ease_factor: 2.5, repetitions: 2, next_due: "2026-10-14T00:00:00", status: "validando" });
    }
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders" || p === "/decks") return json([]);
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate(({ t, fila, chave }) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
    localStorage.setItem(chave, JSON.stringify(fila));
  }, { t: tokenFalso(), fila: DUAS_RESPOSTAS, chave: CHAVE_FILA });
  await page.goto("/");
  return ref;
}

const tamanhoDaFila = (page) =>
  page.evaluate((chave) => JSON.parse(localStorage.getItem(chave) || "[]").length, CHAVE_FILA);

test.describe("Fila de respostas de estudo", () => {
  test("token expirado não joga o estudo fora", async ({ page }) => {
    const servidor = await abrirComFilaPendente(page, 401);
    await page.waitForTimeout(1200);

    expect(await tamanhoDaFila(page), "as respostas precisam continuar guardadas").toBe(2);
    // Para na primeira recusa em vez de martelar a fila inteira.
    expect(servidor.tentativas).toBe(1);
    // O 401 também encerra a sessão (ver sessao-expirada.spec.js): a fila
    // fica esperando o próximo login, e é o login que a destrava.
    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
    expect(await tamanhoDaFila(page), "deslogar não pode levar o estudo junto").toBe(2);
  });

  test("servidor fora do ar (500): adia e sobe sozinha quando ele volta", async ({ page }) => {
    // Diferente do 401, aqui a sessão continua válida -- é o servidor que
    // tropeçou. Nada se perde e nada precisa de login novo.
    const servidor = await abrirComFilaPendente(page, 500);
    await page.waitForTimeout(1200);
    expect(await tamanhoDaFila(page)).toBe(2);
    await expect(page.locator(".toast-global")).toHaveCount(0); // nada se perdeu: nada a anunciar

    servidor.statusDoAnswer = 200;
    // Mesmo gatilho que o app usa quando a aba volta ao foco.
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await expect.poll(() => tamanhoDaFila(page), { timeout: 10000 }).toBe(0);

    // Com a data ORIGINAL -- o SM-2 precisa saber quando a pessoa respondeu.
    expect(servidor.recebidas.map(r => r.respondido_em)).toEqual([
      "2026-10-13T10:00:00.000Z", "2026-10-13T10:01:00.000Z",
    ]);
  });

  test("card apagado (404) é descartado, senão travaria a fila pra sempre", async ({ page }) => {
    await abrirComFilaPendente(page, 404);
    await page.waitForTimeout(1500);

    expect(await tamanhoDaFila(page)).toBe(0);
    // Esse caso continua avisando: aqui algo se perdeu de verdade.
    await expect(page.locator(".toast-global")).toContainText(/descartada/);
  });
});
