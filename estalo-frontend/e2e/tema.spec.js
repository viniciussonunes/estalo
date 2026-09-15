/**
 * O botão de tema em todas as telas.
 *
 * Por que existe: o botão morava dentro do Dashboard e era o ÚNICO lugar
 * do app onde dava pra trocar o tema. Quem estivesse estudando à noite --
 * na tela do Aprender, justamente quem mais precisa -- tinha que voltar
 * pro início pra escurecer.
 *
 * O teste guarda duas coisas: que o botão está presente em cada tela, e
 * que todas compartilham UM estado só. Esse segundo ponto é o que
 * quebraria em silêncio se alguém trocasse o contexto por um `useTheme()`
 * chamado em cada tela: a tela mudaria, mas o botão da outra ficaria
 * mostrando o ícone velho.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };
const DECK = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 2, memorization_pct: 0 };
const STATS = { total_cards: 2, criticos: 1, hoje: 0, novos: 1, validando: 0, dominados: 0, new_cards: 1, validating: 0, dominated: 0, due_now: 1 };
const CARDS = [
  { id: 100, front: "Pergunta 1", back: "Resposta 1", source: "manual", repetitions: 0, options: ["a", "b", "c"], explanation: "exp" },
  { id: 101, front: "Pergunta 2", back: "Resposta 2", source: "manual", repetitions: 1, options: ["a", "b", "c"], explanation: "exp" },
];

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

async function abrirLogado(page, rota = "/") {
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
    if (p === "/study/global-reviews") return json([]);
    if (/^\/decks\/\d+\/cards$/.test(p)) return json(CARDS);
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(STATS);
    // O Revelar espera uma LISTA. Devolver {} (o catch-all) fazia a tela
    // quebrar de verdade e cair no ErrorBoundary -- o cabeçalho sumia
    // junto e o teste "não achava" o botão de tema.
    if (/^\/study\/decks\/\d+\/reveal$/.test(p)) {
      return json([{ card_id: 100, front: "Pergunta 1", explanation: "Uma explicação." }]);
    }
    if (/^\/study\/decks\/\d+\/next$/.test(p)) {
      return json({ card_id: 100, front: CARDS[0].front, back: CARDS[0].back, due_date: "2026-01-01T00:00:00", repetitions: 0, revisoes_hoje: 0 });
    }
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
    localStorage.setItem("tema_estalo", "light");
  }, tokenFalso());
  await page.goto(rota);
}

const botao = (page) => page.getByRole("button", { name: "Trocar tema" });
const estaEscuro = (page) => page.evaluate(() => document.documentElement.classList.contains("tema-escuro"));

/** Leva o app até a tela pedida pelos caminhos reais do usuário. */
async function irPara(page, tela) {
  if (tela === "início") return abrirLogado(page, "/");
  if (tela === "criar deck") return abrirLogado(page, "/criar-deck");

  await abrirLogado(page, "/?folder=2");
  await page.locator(".lista-deck .lista-info").first().click();
  if (tela === "cards do deck") return;

  if (tela === "aprender") {
    await page.getByRole("button", { name: /Aprender|Estudar hoje|Estudar críticos/ }).click();
    await expect(page.locator(".quiz-opcao").first()).toBeVisible();
    return;
  }
  // Os dois modos secundários moram atrás de "Outros modos" (ver
  // modos-de-estudo.spec.js pelo motivo).
  if (tela === "estudo clássico") {
    await page.getByRole("button", { name: "Outros modos" }).click();
    await page.getByRole("button", { name: /Frente e verso/ }).click();
    return;
  }
  if (tela === "revelar") {
    await page.getByRole("button", { name: "Outros modos" }).click();
    await page.getByRole("button", { name: /Só ler/ }).click();
    return;
  }
  throw new Error(`tela desconhecida: ${tela}`);
}

const TELAS = ["início", "cards do deck", "aprender", "estudo clássico", "revelar", "criar deck"];

test.describe("Tema", () => {
  for (const tela of TELAS) {
    test(`dá pra trocar o tema na tela "${tela}"`, async ({ page }) => {
      await irPara(page, tela);

      const alvo = botao(page);
      await expect(alvo, `a tela "${tela}" ficou sem o botão de tema`).toBeVisible();

      expect(await estaEscuro(page)).toBe(false);
      await alvo.click();
      expect(await estaEscuro(page), `clicar na tela "${tela}" não escureceu`).toBe(true);
    });
  }

  test("o tema escolhido numa tela vale nas outras", async ({ page }) => {
    // A prova de que existe um estado só. Com um useTheme() por tela,
    // cada uma teria o seu: a classe do <html> até mudaria, mas o botão
    // da outra tela continuaria no ícone antigo, e o próximo clique lá
    // andaria a partir do valor errado.
    await irPara(page, "aprender");
    await botao(page).click();
    expect(await estaEscuro(page)).toBe(true);

    await page.getByRole("button", { name: /Voltar/ }).click();
    await expect(page.locator(".lista-cards, .cards-lista-topo").first()).toBeVisible();

    expect(await estaEscuro(page), "voltar pro deck perdeu o tema escuro").toBe(true);
    // E o botão de lá tem que estar mostrando o estado novo, não o antigo.
    await expect(botao(page)).toHaveAttribute("title", /Escuro/);
  });

  test("a escolha sobrevive a recarregar a página", async ({ page }) => {
    await irPara(page, "início");
    await botao(page).click();
    expect(await estaEscuro(page)).toBe(true);

    await page.reload();
    await expect(botao(page)).toBeVisible();
    expect(await estaEscuro(page), "o tema não foi guardado").toBe(true);
  });

  test("o nome do botão não muda quando o tema muda", async ({ page }) => {
    // Mesma regra do olho da senha: nome fixo, estado no title. Um botão
    // que se renomeia a cada clique soa como três botões diferentes pra
    // quem usa leitor de tela.
    await irPara(page, "início");
    await expect(botao(page)).toHaveAttribute("title", /Claro/);
    await botao(page).click();
    await expect(botao(page)).toHaveAttribute("title", /Escuro/);
    await botao(page).click();
    await expect(botao(page)).toHaveAttribute("title", /Sistema/);
  });
});
