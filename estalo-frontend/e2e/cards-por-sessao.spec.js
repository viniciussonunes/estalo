/**
 * "Cards por sessão": o tamanho do lote da Revisão Geral, escolhido pela
 * pessoa.
 *
 * Era 15 fixo no código. Não é um teto de quanto dá pra estudar -- desde
 * o "Continuar · N restantes", o lote seguinte vem a um clique -- é o
 * tamanho de uma sentada, e isso varia por pessoa e por rotina.
 *
 * O ponto delicado é o "15+" do cartão da Home (e do botão Continuar):
 * ele era o número 15 escrito no código. Mostrar "15+" pra quem
 * configurou 30 seria mentir sobre o que a sessão vai servir.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** `decks` com stats que somam `pendentes` cards vencidos, pro cartão herói. */
function montarDecks(pendentes) {
  const deck = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: pendentes, memorization_pct: 0 };
  const stats = { total_cards: pendentes, criticos: pendentes, hoje: 0, novos: 0, validando: 0, dominados: 0, new_cards: 0, validating: 0, dominated: 0, due_now: pendentes };
  return { deck, stats };
}

/**
 * `ref.preferencia` é o que o /auth/me devolve; o PATCH atualiza e
 * devolve o UserOut inteiro, como o backend de verdade faz.
 */
async function abrirLogado(page, { preferencia = 15, pendentes = 0, rota = "/" } = {}) {
  const ref = { preferencia, salvos: [] };
  const { deck, stats } = montarDecks(pendentes);
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(c) });
    const eu = () => ({ id: 1, email: "estudante@estalo.dev", created_at: "2026-03-05T14:20:00", is_admin: false, cards_por_sessao: ref.preferencia });
    if (p === "/auth/me/preferencias") {
      const pedido = JSON.parse(req.postData() || "{}").cards_por_sessao;
      ref.salvos.push(pedido);
      ref.preferencia = pedido;
      return json(eu());
    }
    if (p === "/auth/me") return json(eu());
    if (p === "/auth/me/quota") return json({ consumido: 0, limite: 50000, restante: 50000, renova_em: "2026-10-15T03:00:00" });
    if (p === "/folders") return json([{ ...PASTA, children: [] }]);
    if (p === "/decks") return json(pendentes > 0 ? [deck] : []);
    if (p === "/study/decks/stats") return json(pendentes > 0 ? { 10: stats } : {});
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto(rota);
  return ref;
}

const campo = (page) => page.locator(".conta-estudo-campo input");
const salvar = (page) => page.locator(".conta-estudo-campo button");

test.describe("Cards por sessão", () => {
  test("mostra o número atual e só habilita Salvar depois de mudar", async ({ page }) => {
    await abrirLogado(page, { rota: "/conta" });
    await expect(campo(page)).toHaveValue("15");
    await expect(salvar(page)).toBeDisabled();

    await campo(page).fill("25");
    await expect(salvar(page)).toBeEnabled();
  });

  test("salvar manda o número e confirma na tela", async ({ page }) => {
    const servidor = await abrirLogado(page, { rota: "/conta" });
    await campo(page).fill("25");
    await salvar(page).click();

    await expect(page.locator(".toast-global")).toContainText("25 cards por vez");
    expect(servidor.salvos).toEqual([25]);
    await expect(salvar(page)).toBeDisabled(); // já é o valor atual
  });

  test("número fora da faixa não chega a ser enviado", async ({ page }) => {
    const servidor = await abrirLogado(page, { rota: "/conta" });
    for (const invalido of ["0", "4", "51", "300"]) {
      await campo(page).fill(invalido);
      await expect(page.locator(".conta-estudo-nota.erro")).toContainText("de 5 a 50");
      await expect(salvar(page)).toBeDisabled();
    }
    expect(servidor.salvos).toEqual([]);
  });

  test("o aviso de cota só aparece em sessão longa", async ({ page }) => {
    await abrirLogado(page, { rota: "/conta" });
    await expect(page.locator(".conta-estudo-nota")).toHaveCount(0);
    await campo(page).fill("30");
    await expect(page.locator(".conta-estudo-nota")).toContainText(/cota de IA/);
    await campo(page).fill("12");
    await expect(page.locator(".conta-estudo-nota")).toHaveCount(0);
  });

  test("o cartão da Home conta na medida escolhida, não em 15", async ({ page }) => {
    // Com 40 pendentes e lote de 15, a Home dizia "15+". Quem configurou
    // 30 precisa ver "30+": é o que a sessão vai realmente servir.
    await abrirLogado(page, { preferencia: 30, pendentes: 40 });
    await expect(page.locator(".hero-revisao-contador")).toHaveText("30+");
    await expect(page.locator(".hero-revisao-sub")).toContainText("30+ cards vencidos");
  });

  test("abaixo do lote, mostra o número exato", async ({ page }) => {
    await abrirLogado(page, { preferencia: 30, pendentes: 8 });
    await expect(page.locator(".hero-revisao-contador")).toHaveText("8");
  });

  test("sem internet, o ajuste fica indisponível em vez de falhar no clique", async ({ page }) => {
    await abrirLogado(page, { rota: "/conta" });
    await page.route("**/*", async (route) => {
      const req = route.request();
      const p = new URL(req.url()).pathname;
      if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
      return route.abort("internetdisconnected");
    });
    await page.goto("/conta");
    await expect(page.locator(".offline-banner")).toBeVisible();
    await expect(campo(page)).toBeDisabled();
    await expect(salvar(page)).toBeDisabled();
  });
});

/**
 * Teto diário do modo Frente e verso.
 *
 * Esse modo tem um limite de 50 revisões por deck por dia no backend
 * (`limite_diario` em /next) que o frontend nunca configurou -- ninguém
 * sabe que existe. Ao bater nele, o backend manda `motivo:
 * "limite_diario"`, e a tela jogava fora: mostrava a MESMA tela de quem
 * terminou tudo, dizendo "Tudo revisado por hoje!" pra quem ainda tinha
 * card vencido esperando. O app afirmava algo falso.
 */
async function abrirFrenteEVerso(page, fimDeSessao) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (/^\/study\/decks\/\d+\/next$/.test(p)) return json(fimDeSessao);
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev", cards_por_sessao: 15 });
    if (p === "/folders") return json([{ ...PASTA, children: [] }]);
    if (p === "/decks") return json([montarDecks(3).deck]);
    if (p === "/study/decks/stats") return json({ 10: montarDecks(3).stats });
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(montarDecks(3).stats);
    if (/^\/decks\/\d+\/cards$/.test(p)) return json([]);
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  // A tela exige o deck no state do router (abrir /deck/10/estudo direto
  // volta pra raiz): entra pelo caminho real, como quem usa o app.
  await page.goto("/?folder=2");
  await page.locator(".lista-deck .lista-info").first().click();
  await expect(page.locator(".cards-lista-topo")).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "Outros modos" }).click();
  await page.getByRole("button", { name: /Frente e verso/ }).click();
}

test.describe("Frente e verso: fim de sessão", () => {
  test("bater no teto do dia não é 'tudo revisado'", async ({ page }) => {
    await abrirFrenteEVerso(page, { motivo: "limite_diario", revisoes_hoje: 50, limite_diario: 50 });

    const fim = page.locator(".estudo-concluido");
    await expect(fim).toBeVisible({ timeout: 15000 });
    await expect(fim).toContainText("Limite de hoje atingido");
    await expect(fim).toContainText("50 cards deste deck hoje");
    await expect(fim).toContainText(/Ainda há cards esperando/);
    await expect(fim).not.toContainText("Tudo revisado");
  });

  test("terminar de verdade continua comemorando", async ({ page }) => {
    await abrirFrenteEVerso(page, { motivo: "sem_cards", revisoes_hoje: 3, limite_diario: 50 });

    const fim = page.locator(".estudo-concluido");
    await expect(fim).toBeVisible({ timeout: 15000 });
    await expect(fim).toContainText("Tudo revisado por hoje!");
    await expect(fim).not.toContainText("Limite");
  });
});
