/**
 * Modal de trocar senha.
 *
 * Por que importa mais do que parece: até 2026-09-13 não existia jeito
 * nenhum de trocar de senha no Estalo, e continua não existindo
 * recuperação. Ou seja, este formulário é a ÚNICA porta -- e um erro de
 * digitação numa senha mascarada tranca a pessoa fora da própria conta,
 * sem volta. Daí a confirmação obrigatória, que é o que estes testes
 * prendem.
 *
 * Não depende do backend: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** `resposta` decide o que /auth/change-password devolve. */
async function abrirDashboard(page, resposta = "ok") {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (c, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(c) });

    if (p === "/auth/change-password") {
      if (resposta === "atual-errada") return json({ detail: "A senha atual está incorreta" }, 400);
      if (resposta === "obvia") {
        return json({ detail: "Essa senha é uma das mais usadas do mundo e seria adivinhada em segundos. Escolha outra." }, 400);
      }
      return route.fulfill({ status: 204, body: "" });
    }
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders" || p === "/decks") return json([]);
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Trocar senha" }).first()).toBeVisible();
}

async function abrirModal(page) {
  await page.getByRole("button", { name: "Trocar senha" }).first().click();
  await expect(page.getByRole("dialog", { name: "Trocar senha" })).toBeVisible();
}

/** Pelo rótulo, exato: "Nova senha" e "Repita a nova senha" se
 *  confundiriam em qualquer busca por substring. */
function campo(page, rotulo) {
  return page.getByLabel(rotulo, { exact: true });
}

test.describe("Trocar senha", () => {
  test("troca a senha e confirma que trocou", async ({ page }) => {
    await abrirDashboard(page);
    await abrirModal(page);

    await campo(page, "Senha atual").fill("a-antiga-2026");
    await campo(page, "Nova senha").fill("a-nova-boa-2026");
    await campo(page, "Repita a nova senha").fill("a-nova-boa-2026");
    await page.locator(".modal-painel").getByRole("button", { name: "Trocar senha" }).click();

    await expect(page.getByRole("dialog")).toHaveCount(0);
    // Aqui o aviso é bem-vindo: mudou uma credencial, e nada mais na tela
    // mostraria isso. (Diferente do sync offline, que é mecânica interna.)
    await expect(page.locator(".toast-global")).toContainText("Senha trocada");
  });

  test("confirmação que não bate barra antes de sair da tela", async ({ page }) => {
    let chamou = false;
    await page.route("**/auth/change-password", (route) => { chamou = true; route.abort(); });
    await abrirDashboard(page);
    await abrirModal(page);

    await campo(page, "Senha atual").fill("a-antiga-2026");
    await campo(page, "Nova senha").fill("a-nova-boa-2026");
    await campo(page, "Repita a nova senha").fill("a-nova-boa-2027");
    await page.locator(".modal-painel").getByRole("button", { name: "Trocar senha" }).click();

    await expect(page.getByRole("alert")).toContainText(/confirmação não bate/i);
    // Sem recuperação de senha no app, mandar uma senha com typo é perder
    // a conta. Nem chega a sair daqui.
    expect(chamou, "não devia ter chamado a API").toBe(false);
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("senha nova curta é barrada sem ida ao servidor", async ({ page }) => {
    let chamou = false;
    await page.route("**/auth/change-password", (route) => { chamou = true; route.abort(); });
    await abrirDashboard(page);
    await abrirModal(page);

    await campo(page, "Senha atual").fill("a-antiga-2026");
    await campo(page, "Nova senha").fill("curta");
    await campo(page, "Repita a nova senha").fill("curta");
    await page.locator(".modal-painel").getByRole("button", { name: "Trocar senha" }).click();

    await expect(page.getByRole("alert")).toContainText("8 caracteres");
    expect(chamou).toBe(false);
  });

  test("recusa do servidor aparece dentro do modal, sem fechar", async ({ page }) => {
    await abrirDashboard(page, "atual-errada");
    await abrirModal(page);

    await campo(page, "Senha atual").fill("chute-errado");
    await campo(page, "Nova senha").fill("a-nova-boa-2026");
    await campo(page, "Repita a nova senha").fill("a-nova-boa-2026");
    await page.locator(".modal-painel").getByRole("button", { name: "Trocar senha" }).click();

    await expect(page.getByRole("alert")).toContainText(/senha atual está incorreta/i);
    // Fechar aqui apagaria o que a pessoa digitou junto com o erro.
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("a lista de senhas óbvias mora no servidor, e a frase dele chega inteira", async ({ page }) => {
    // O cliente só checa TAMANHO (ver src/senha.js): duplicar a lista de
    // senhas óbvias criaria duas listas pra manter em sincronia. Este teste
    // garante que a recusa do servidor não se perde no caminho.
    await abrirDashboard(page, "obvia");
    await abrirModal(page);

    await campo(page, "Senha atual").fill("a-antiga-2026");
    await campo(page, "Nova senha").fill("12345678");
    await campo(page, "Repita a nova senha").fill("12345678");
    await page.locator(".modal-painel").getByRole("button", { name: "Trocar senha" }).click();

    await expect(page.getByRole("alert")).toContainText(/mais usadas do mundo/i);
  });

  test("avisa que não existe recuperação de senha", async ({ page }) => {
    await abrirDashboard(page);
    await abrirModal(page);
    // Dito na hora de escolher a senha, não depois de perdê-la.
    await expect(page.locator(".modal-senha-aviso")).toContainText(/recuperação de senha/i);
  });

  test("cada olho diz de qual campo é", async ({ page }) => {
    await abrirDashboard(page);
    await abrirModal(page);
    // Três campos de senha: três botões chamados só "Mostrar senha" seriam
    // indistinguíveis num leitor de tela.
    for (const nome of ["Mostrar senha atual", "Mostrar nova senha", "Mostrar repita a nova senha"]) {
      await expect(page.getByRole("button", { name: nome })).toBeVisible();
    }
  });
});
