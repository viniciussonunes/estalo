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

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

async function abrirLogado(page, usuario = USUARIO) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json(usuario);
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
