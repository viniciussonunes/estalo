import { test, expect } from "@playwright/test";

test.describe("Navegação inicial", () => {
  test("carrega a home sem erros e redireciona pro login sem sessão", async ({ page }) => {
    const erros = [];
    page.on("pageerror", (err) => erros.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") erros.push(msg.text()); });

    await page.goto("/");

    // Sem token salvo, o RequireAuth manda pro /login em vez de travar/quebrar.
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator(".marca-nome")).toHaveText("Estalo");
    await expect(page.locator(".cartao-auth")).toBeVisible();

    expect(erros, `Erros de console/JS na home: ${erros.join(" | ")}`).toEqual([]);
  });

  test("navega direto pra uma rota interna (/deck/1) sem 404 nem crash", async ({ page }) => {
    const erros = [];
    page.on("pageerror", (err) => erros.push(err.message));
    page.on("console", (msg) => { if (msg.type() === "error") erros.push(msg.text()); });

    const resposta = await page.goto("/deck/1");

    // O rewrite de SPA da Vercel garante 200 (index.html) em qualquer rota,
    // nunca 404 — quem decide o que renderizar é o React Router no cliente.
    expect(resposta.status()).toBeLessThan(400);

    // Sem sessão, RequireAuth redireciona pro login em vez de deixar a
    // tela em branco ou travada.
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator(".cartao-auth")).toBeVisible();

    expect(erros, `Erros de console/JS em /deck/1: ${erros.join(" | ")}`).toEqual([]);
  });
});
