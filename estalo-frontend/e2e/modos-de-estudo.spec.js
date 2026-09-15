/**
 * Os modos de estudo, explicados.
 *
 * O topo da tela de cards tinha três botões lado a lado -- "Revelar",
 * "Estudo clássico" e o CTA ("Aprender" / "Estudar hoje" / "Estudar
 * críticos") -- e nada dizia o que cada um fazia. Quem chegava escolhia
 * por tentativa; ninguém sabia, por exemplo, que o Revelar não grava
 * nada. No celular os três ainda quebravam em duas linhas.
 *
 * Agora é um botão principal + "Outros modos", que abre um modal com os
 * três nomeados pelo que fazem, e dizendo se contam ou não pro ritmo de
 * revisão. Os dois secundários ficam a um clique a mais -- de propósito.
 *
 * Não depende do backend: a API é simulada em auditoria-layout.js.
 */
import { test, expect } from "@playwright/test";
import { abrirLogado } from "./auditoria-layout.js";

async function abrirDeck(page) {
  await abrirLogado(page, "/?folder=2");
  await expect(page.locator(".lista-deck .lista-info").first()).toBeVisible({ timeout: 15000 });
  await page.locator(".lista-deck .lista-info").first().click();
  await expect(page.locator(".cards-lista-topo")).toBeVisible({ timeout: 15000 });
}

test.describe("Modos de estudo", () => {
  test("o topo tem um botão principal e 'Outros modos', não três botões soltos", async ({ page }) => {
    await abrirDeck(page);
    const topo = page.locator(".modos-estudo-topo");
    await expect(topo.getByRole("button", { name: "Outros modos" })).toBeVisible();
    await expect(topo.getByRole("button", { name: /Aprender|Estudar hoje|Estudar críticos/ })).toBeVisible();
    // Os nomes antigos, sem explicação, saíram do topo.
    await expect(topo.getByRole("button", { name: "Revelar" })).toHaveCount(0);
    await expect(topo.getByRole("button", { name: "Estudo clássico" })).toHaveCount(0);
  });

  test("o modal nomeia os três pelo que fazem e diz o que conta pro ritmo", async ({ page }) => {
    await abrirDeck(page);
    await page.getByRole("button", { name: "Outros modos" }).click();
    const modal = page.locator(".modal-modos");
    await expect(modal).toBeVisible();
    await expect(modal.getByRole("heading")).toHaveText("Como você quer estudar?");

    const opcoes = modal.locator(".modo-opcao");
    await expect(opcoes).toHaveCount(3);
    await expect(opcoes.nth(0)).toContainText("Aprender");
    await expect(opcoes.nth(0)).toContainText("conta pro seu ritmo");
    await expect(opcoes.nth(1)).toContainText("Frente e verso");
    await expect(opcoes.nth(1)).toContainText("Também conta");
    await expect(opcoes.nth(2)).toContainText("Só ler");
    await expect(opcoes.nth(2)).toContainText("Não mexe no seu ritmo");
  });

  test("cada opção leva pra tela certa", async ({ page }) => {
    await abrirDeck(page);
    await page.getByRole("button", { name: "Outros modos" }).click();
    await page.getByRole("button", { name: /Só ler/ }).click();
    await expect(page).toHaveURL(/\/revelar$/);

    await page.getByRole("button", { name: "← Voltar" }).click();
    await expect(page.locator(".cards-lista-topo")).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: "Outros modos" }).click();
    await page.getByRole("button", { name: /Frente e verso/ }).click();
    await expect(page).toHaveURL(/\/estudo$/);

    await page.getByRole("button", { name: "← Voltar" }).click();
    await expect(page.locator(".cards-lista-topo")).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: "Outros modos" }).click();
    await page.getByRole("button", { name: /^Aprender/ }).click();
    await expect(page).toHaveURL(/\/aprender$/);
  });

  test("Esc fecha o modal sem sair da tela", async ({ page }) => {
    await abrirDeck(page);
    await page.getByRole("button", { name: "Outros modos" }).click();
    await expect(page.locator(".modal-modos")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".modal-modos")).toBeHidden();
    await expect(page.locator(".cards-lista-topo")).toBeVisible();
  });
});
