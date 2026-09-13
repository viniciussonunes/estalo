/**
 * Tela de entrar / criar conta.
 *
 * Por que existe: a tela tinha 87 linhas e nenhuma rede de proteção. Os
 * problemas que ela guardava não aparecem olhando um print --
 * `autocomplete` que falta, erro que o leitor de tela não anuncia, "Erro
 * 502" vazando cru na cara de quem só queria entrar. Tudo isso é
 * verificável, então passa a ser verificado.
 *
 * Não depende do backend: a API é simulada aqui (mesma regra das outras
 * specs -- o job de e2e do CI roda sem banco e sem segredo nenhum).
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

/**
 * Simula a API de autenticação. `resposta` decide o que /auth/login faz:
 *   "ok"       -> entra
 *   "senha"    -> 401 com a mensagem que o backend realmente devolve
 *   "servidor" -> 500 sem corpo útil
 *   "queda"    -> conexão abortada (o caso de rede)
 */
async function simularApi(page, resposta = "ok") {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (corpo, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(corpo) });

    if (p === "/auth/login") {
      if (resposta === "queda") return route.abort("internetdisconnected");
      if (resposta === "servidor") return route.fulfill({ status: 500, body: "" });
      if (resposta === "senha") return json({ detail: "Email ou senha incorretos" }, 401);
      if (resposta === "bloqueado") {
        return route.fulfill({
          status: 429,
          contentType: "application/json",
          headers: { "Retry-After": "60" },
          body: JSON.stringify({ detail: "Muitas tentativas seguidas. Tente de novo em cerca de 1 minuto." }),
        });
      }
      return json({ access_token: "t.t.t", token_type: "bearer" });
    }
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders" || p === "/decks") return json([]);
    return json({});
  });
  await page.goto("/login");
  await expect(page.locator(".cartao-auth")).toBeVisible();
}

test.describe("Tela de entrar", () => {
  test("o botão do olho revela e esconde a senha", async ({ page }) => {
    await simularApi(page);
    const campo = page.locator(".campo-senha input");
    await campo.fill("minha senha");
    await expect(campo).toHaveAttribute("type", "password");

    const olho = page.getByRole("button", { name: "Mostrar senha" });
    await olho.click();
    await expect(campo, "clicar no olho deveria revelar a senha").toHaveAttribute("type", "text");
    // O valor não pode se perder na troca de tipo.
    await expect(campo).toHaveValue("minha senha");

    await olho.click();
    await expect(campo).toHaveAttribute("type", "password");
  });

  test("o olho é um botão só, com estado — não um botão que muda de nome", async ({ page }) => {
    await simularApi(page);
    const olho = page.getByRole("button", { name: "Mostrar senha" });
    await expect(olho).toHaveAttribute("aria-pressed", "false");
    await olho.click();
    // Continua se chamando "Mostrar senha": quem usa leitor de tela ouve o
    // mesmo controle, e o aria-pressed diz se está ligado. Trocar o nome
    // faria parecer que apareceu outro botão no lugar.
    await expect(page.getByRole("button", { name: "Mostrar senha" })).toHaveAttribute("aria-pressed", "true");
  });

  test("os campos se identificam pro gerenciador de senhas", async ({ page }) => {
    await simularApi(page);
    await expect(page.getByPlaceholder("voce@email.com")).toHaveAttribute("autocomplete", "username");
    // No login é a senha existente...
    await expect(page.locator(".campo-senha input")).toHaveAttribute("autocomplete", "current-password");
    // ...e no cadastro é uma nova, o que faz o gerenciador OFERECER uma
    // senha forte em vez de tentar preencher a antiga.
    await page.getByRole("button", { name: "Criar conta" }).click();
    await expect(page.locator(".campo-senha input")).toHaveAttribute("autocomplete", "new-password");
  });

  test("a mensagem do backend passa inteira, e é anunciada", async ({ page }) => {
    await simularApi(page, "senha");
    await page.getByPlaceholder("voce@email.com").fill("estudante@estalo.dev");
    await page.locator(".campo-senha input").fill("errada");
    await page.getByRole("button", { name: "Entrar" }).last().click();

    const alerta = page.getByRole("alert");
    await expect(alerta).toHaveText("Email ou senha incorretos");
    // role="alert" é o que faz o leitor de tela falar o erro sozinho. Sem
    // isso a pessoa clica em Entrar, nada acontece e nada explica.
    await expect(page.locator(".campo-senha input")).toHaveAttribute("aria-invalid", "true");
  });

  test("erro de servidor não vira 'Erro 500' na cara do usuário", async ({ page }) => {
    await simularApi(page, "servidor");
    await page.getByPlaceholder("voce@email.com").fill("estudante@estalo.dev");
    await page.locator(".campo-senha input").fill("segredo123");
    await page.getByRole("button", { name: "Entrar" }).last().click();

    const alerta = page.getByRole("alert");
    await expect(alerta).toBeVisible();
    await expect(alerta, "o código HTTP cru não diz nada a quem só quer entrar").not.toContainText("Erro 5");
    await expect(alerta).toContainText(/servidor não respondeu/i);
  });

  test("rede caída avisa uma vez só, dentro do formulário", async ({ page }) => {
    await simularApi(page, "queda");
    await page.getByPlaceholder("voce@email.com").fill("estudante@estalo.dev");
    await page.locator(".campo-senha input").fill("segredo123");
    await page.getByRole("button", { name: "Entrar" }).last().click();

    await expect(page.getByRole("alert")).toContainText(/internet|servidor/i);
    // O toast global de rede é útil no meio do app, onde não há onde
    // colocar a mensagem. Aqui ele seria a MESMA notícia duas vezes, no
    // mesmo instante -- ver `semToastDeRede` em api.js.
    await expect(page.locator(".toast-global"), "erro repetido: formulário e toast dizendo o mesmo").toHaveCount(0);
  });

  test("conta travada por tentativas explica a espera, sem virar modal de cota", async ({ page }) => {
    // O backend responde 429 quando trava a conta (ver login_throttle.py no
    // estalo-backend). No frontend, 429 vira QuotaExceededException -- que
    // nasceu pro limite de IA e tem um modal próprio. Aqui não pode virar
    // modal nenhum: é uma frase no formulário, dizendo quanto esperar.
    await simularApi(page, "bloqueado");
    await page.getByPlaceholder("voce@email.com").fill("estudante@estalo.dev");
    await page.locator(".campo-senha input").fill("segredo123");
    await page.getByRole("button", { name: "Entrar" }).last().click();

    await expect(page.getByRole("alert")).toContainText(/tentativas seguidas/i);
    await expect(page.getByRole("alert")).toContainText(/1 minuto/);
    await expect(page.getByRole("dialog"), "não é caso de modal").toHaveCount(0);
  });

  test("cadastro avisa o mínimo de senha antes de tentar", async ({ page }) => {
    let chamouRegistro = false;
    await page.route("**/auth/register", (route) => { chamouRegistro = true; route.abort(); });
    await simularApi(page);

    await page.getByRole("button", { name: "Criar conta" }).click();
    // A exigência fica visível no campo, não escondida até o erro.
    await expect(page.locator(".campo-dica")).toContainText("8 caracteres");

    await page.getByPlaceholder("voce@email.com").fill("novo@estalo.dev");
    await page.locator(".campo-senha input").fill("curta");
    await page.getByRole("button", { name: "Criar conta e entrar" }).click();

    await expect(page.getByRole("alert")).toContainText("8 caracteres");
    // Barra aqui: não gasta uma ida ao servidor pra ouvir o que a tela já
    // sabia. (O servidor continua sendo a autoridade -- ver senha.js.)
    expect(chamouRegistro, "não devia ter chamado /auth/register").toBe(false);
  });

  test("no login a dica de tamanho não aparece", async ({ page }) => {
    // Dizer "curta demais" na tela de ENTRAR contaria a um atacante que
    // aquela senha nem poderia existir. A regra é do cadastro.
    await simularApi(page);
    await expect(page.locator(".campo-dica")).toHaveCount(0);
  });

  test("login que dá certo entra no app", async ({ page }) => {
    await simularApi(page, "ok");
    await page.getByPlaceholder("voce@email.com").fill("estudante@estalo.dev");
    await page.locator(".campo-senha input").fill("segredo123");
    await page.getByRole("button", { name: "Entrar" }).last().click();
    await expect(page.locator(".cartao-auth")).toHaveCount(0);
  });
});
