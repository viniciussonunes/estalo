/**
 * Área da conta.
 *
 * Está sendo montada por partes. Esta suíte cresce junto: por enquanto
 * cobre a identidade e o caminho até ela.
 *
 * O buraco concreto que a identidade fecha: no celular o email era
 * escondido por CSS e não sobrava NADA identificando a conta. Quem usa uma
 * conta pessoal e outra de estudo descobria pelo conteúdo -- ou não
 * descobria.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;
const USUARIO = { id: 1, email: "estudante@estalo.dev", created_at: "2026-03-05T14:20:00" };
// Cota padrão do projeto (DEFAULT_DAILY_LIMIT no backend).
const COTA_TRANQUILA = { consumido: 5000, limite: 50000, restante: 45000, renova_em: "2026-09-14T00:00:00" };

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

async function abrirLogado(page, usuario = USUARIO, cota = COTA_TRANQUILA) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json(usuario);
    if (p === "/auth/me/quota") {
      if (cota === null) return route.abort("internetdisconnected");
      return json(cota);
    }
    if (p === "/folders" || p === "/decks") return json([]);
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate(([t, u]) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify(u));
  }, [tokenFalso(), usuario]);
  await page.goto("/");
  await expect(page.locator(".primeiro-uso")).toBeVisible();
}

test.describe("Área da conta", () => {
  test("o email no cabeçalho leva pra conta", async ({ page }) => {
    await abrirLogado(page);
    await page.getByRole("button", { name: /Sua conta/ }).click();

    await expect(page).toHaveURL(/\/conta/);
    await expect(page.locator(".conta-email")).toHaveText("estudante@estalo.dev");
    await expect(page.locator(".conta-desde")).toHaveText("No Estalo desde março de 2026");
  });

  test("dá pra voltar de onde veio", async ({ page }) => {
    await abrirLogado(page);
    await page.getByRole("button", { name: /Sua conta/ }).click();
    await expect(page).toHaveURL(/\/conta/);
    await page.getByRole("button", { name: /Voltar/ }).click();
    await expect(page.locator(".primeiro-uso")).toBeVisible();
  });

  test("no celular sobra a inicial, e ela continua sendo a porta", async ({ page }) => {
    // O ponto do item: o email some por falta de espaço, mas antes não
    // ficava nada no lugar -- não dava pra saber em que conta você estava.
    await page.setViewportSize({ width: 412, height: 915 });
    await abrirLogado(page);

    await expect(page.locator(".usuario-email")).toBeHidden();
    await expect(page.locator(".botao-conta-avatar")).toHaveText("E");
    await page.locator(".botao-conta").click();
    await expect(page.locator(".conta-email")).toHaveText("estudante@estalo.dev");
  });

  test("mostra o uso de IA do dia, sem falar em tokens", async ({ page }) => {
    // Antes disto o limite era invisível até você BATER nele, com um modal
    // no meio de um Tutor. Não havia tela nenhuma onde olhar antes.
    await abrirLogado(page);
    await page.getByRole("button", { name: /Sua conta/ }).click();

    await expect(page.locator(".conta-cota-pct")).toHaveText("10%");
    await expect(page.locator(".conta-cota")).toContainText("Sobra bastante por hoje");
    // "Tokens" não diz nada a ninguém, e o número exato não ajuda a
    // decidir nada -- o que importa é se dá pra continuar hoje.
    await expect(page.locator(".conta-cota")).not.toContainText(/token/i);
    await expect(page.locator(".conta-cota")).not.toContainText("5000");
  });

  test("avisa quando resta pouco", async ({ page }) => {
    await abrirLogado(page, USUARIO, { consumido: 45000, limite: 50000, restante: 5000, renova_em: "2026-09-14T00:00:00" });
    await page.getByRole("button", { name: /Sua conta/ }).click();

    await expect(page.locator(".conta-cota-pct")).toHaveText("90%");
    await expect(page.locator(".conta-cota-pct")).toHaveClass(/apertado/);
    await expect(page.locator(".conta-cota")).toContainText("Resta pouco por hoje");
  });

  test("cota que não carrega não vira erro na tela", async ({ page }) => {
    // Offline, por exemplo. Um erro vermelho na área da conta por causa de
    // um número acessório seria pior que a ausência dele.
    await abrirLogado(page, USUARIO, null);
    await page.getByRole("button", { name: /Sua conta/ }).click();

    await expect(page.locator(".conta-email")).toBeVisible();
    await expect(page.locator(".conta-cota")).toHaveCount(0);
    await expect(page.locator(".erro")).toHaveCount(0);
  });

  test("a troca de senha mora aqui, e não mais no cabeçalho", async ({ page }) => {
    await abrirLogado(page);
    // Saiu do cabeçalho de TODAS as telas: era o que entulhava o topo no
    // celular. Este assert é o que impede alguém de recolocar lá "porque
    // é mais rápido de achar".
    await expect(page.getByRole("button", { name: "Trocar senha" })).toHaveCount(0);

    await page.getByRole("button", { name: /Sua conta/ }).click();
    await expect(page.getByRole("button", { name: "Trocar senha" })).toBeVisible();
    await expect(page.locator(".conta-acao").filter({ hasText: "Senha" }).first())
      .toContainText("Não existe recuperação de senha");
  });

  test("sem nada baixado, explica como baixar", async ({ page }) => {
    await abrirLogado(page);
    await page.getByRole("button", { name: /Sua conta/ }).click();
    await expect(page.locator(".conta-baixados")).toContainText("Nenhum deck baixado");
  });

  test("lista o que está guardado no aparelho e deixa remover", async ({ page }) => {
    // Antes disto, ver e desfazer download só dava deck a deck: era
    // preciso navegar até cada um. Quem quisesse liberar espaço não tinha
    // por onde começar.
    await abrirLogado(page);
    await page.evaluate(() => {
      localStorage.setItem("estalo_decks_offline", JSON.stringify({
        "1:10": { deck: { id: 10, title: "Intune" }, baixadoEm: "2026-09-01T10:00:00.000Z", totalCards: 40 },
        "1:11": { deck: { id: 11, title: "Autopilot" }, baixadoEm: "2026-09-02T10:00:00.000Z", totalCards: 8 },
        // De OUTRO usuário no mesmo navegador: não pode aparecer aqui.
        "2:99": { deck: { id: 99, title: "Deck de outra conta" }, baixadoEm: "2026-09-02T10:00:00.000Z", totalCards: 5 },
      }));
    });
    await page.goto("/conta");

    await expect(page.locator(".baixados-item")).toHaveCount(2);
    await expect(page.locator(".conta-baixados")).toContainText("2 decks · 48 cards");
    await expect(page.locator(".conta-baixados")).not.toContainText("Deck de outra conta");

    await page.locator(".baixados-item").filter({ hasText: "Intune" })
      .getByRole("button", { name: /Remover Intune/ }).click();

    await expect(page.locator(".baixados-item")).toHaveCount(1);
    await expect(page.locator(".conta-baixados")).not.toContainText("Intune");
  });

  test("dá pra conferir e remover downloads sem internet", async ({ page }) => {
    // É tudo local. E é justamente sem conexão que alguém vai querer saber
    // o que tem guardado.
    await abrirLogado(page);
    await page.evaluate(() => {
      localStorage.setItem("estalo_decks_offline", JSON.stringify({
        "1:10": { deck: { id: 10, title: "Intune" }, baixadoEm: "2026-09-01T10:00:00.000Z", totalCards: 40 },
      }));
    });
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "onLine", { get: () => false, configurable: true });
    });
    await page.goto("/conta");

    await expect(page.locator(".baixados-item")).toHaveCount(1);
    const remover = page.getByRole("button", { name: /Remover Intune/ });
    await expect(remover).toBeEnabled();
    await remover.click();
    await expect(page.locator(".baixados-item")).toHaveCount(0);
  });

  test("sair mora aqui, e não mais no cabeçalho", async ({ page }) => {
    await abrirLogado(page);
    // Saiu do topo de todas as telas junto com "Trocar senha" -- era o que
    // deixava o cabeçalho quebrando linha no celular.
    await expect(page.getByRole("button", { name: /^Sair/ })).toHaveCount(0);

    await page.getByRole("button", { name: /Sua conta/ }).click();
    await page.getByRole("button", { name: "Sair da conta" }).click();

    // Volta pro login e o crachá some do aparelho.
    await expect(page.locator(".cartao-auth")).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem("estalo_token"))).toBeNull();
  });

  test("sair não apaga os decks baixados", async ({ page }) => {
    // A sessão acaba; o que está guardado no aparelho, não. Quem estuda
    // offline não pode perder o download por ter saído da conta.
    await abrirLogado(page);
    await page.evaluate(() => {
      localStorage.setItem("estalo_decks_offline", JSON.stringify({
        "1:10": { deck: { id: 10, title: "Intune" }, baixadoEm: "2026-09-01T10:00:00.000Z", totalCards: 40 },
      }));
    });
    await page.goto("/conta");
    await page.getByRole("button", { name: "Sair da conta" }).click();
    await expect(page.locator(".cartao-auth")).toBeVisible();

    const registro = await page.evaluate(() => localStorage.getItem("estalo_decks_offline"));
    expect(registro, "o download foi apagado junto com a sessão").toContain("Intune");
  });

  test("usuário comum não vê o painel de administração", async ({ page }) => {
    await abrirLogado(page);
    await page.getByRole("button", { name: /Sua conta/ }).click();
    await expect(page.getByRole("button", { name: "Abrir painel" })).toHaveCount(0);
  });

  test("admin ganha o link — a rota existia e nada levava até ela", async ({ page }) => {
    // /admin funciona desde sempre e só era alcançável digitando a URL.
    await abrirLogado(page, { ...USUARIO, is_admin: true });
    await page.getByRole("button", { name: /Sua conta/ }).click();
    await page.getByRole("button", { name: "Abrir painel" }).click();
    await expect(page).toHaveURL(/\/admin/);
  });

  test("identidade sem data de cadastro não quebra a página", async ({ page }) => {
    // Identidade em cache de uma versão anterior do app pode não ter
    // created_at (ver estalo_ultimo_usuario em App.jsx). Faltar a linha é
    // aceitável; derrubar a página inteira, não.
    await abrirLogado(page, { id: 1, email: "antigo@estalo.dev" });
    await page.getByRole("button", { name: /Sua conta/ }).click();

    await expect(page.locator(".conta-email")).toHaveText("antigo@estalo.dev");
    await expect(page.locator(".conta-desde")).toHaveCount(0);
  });
});
