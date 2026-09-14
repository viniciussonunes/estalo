/**
 * Auditoria de layout no tablet.
 *
 * Mesma sonda e mesmas quatro checagens do celular (ver
 * layout-mobile.spec.js e auditoria-layout.js), em três larguras que o
 * CSS trata de forma diferente:
 *
 *   - 768 em pé: o iPad clássico, e exatamente onde `min-width: 768px`
 *     liga a barra lateral. É o primeiro pixel em que a tela tem que
 *     caber sidebar + conteúdo lado a lado;
 *   - 1024 deitado: o mesmo aparelho de lado;
 *   - 700 em pé: o vão entre o celular (`max-width: 640px`) e a sidebar
 *     (768). Nenhuma regra é feita pra ele -- é o layout "de ninguém",
 *     onde caem tablets pequenos e celulares grandes deitados.
 *
 * Tudo toque (isMobile/hasTouch): tablet não tem hover pra esconder
 * botão atrás.
 *
 * NÃO depende do backend: a API é simulada em auditoria-layout.js.
 */
import { test, expect } from "@playwright/test";
import { simularApi, abrirContaVazia, abrirLogado, conferirLayout } from "./auditoria-layout.js";

const APARELHOS = [
  { nome: "iPad em pé (768)",      viewport: { width: 768,  height: 1024 } },
  { nome: "iPad deitado (1024)",   viewport: { width: 1024, height: 768 } },
  { nome: "tablet pequeno (700)",  viewport: { width: 700,  height: 1000 } },
];

for (const aparelho of APARELHOS) {
  test.describe(`Layout no tablet — ${aparelho.nome}`, () => {
    test.use({ viewport: aparelho.viewport, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });

    test("tela de login", async ({ page }) => {
      await simularApi(page);
      await page.goto("/login");
      await expect(page.locator(".cartao-auth")).toBeVisible();
      await conferirLayout(page, "login");
    });

    test("dashboard (raiz)", async ({ page }) => {
      await abrirLogado(page, "/");
      await expect(page.locator(".pasta-card, .lista-pasta").first()).toBeVisible();
      await conferirLayout(page, "dashboard");
    });

    test("dentro de uma pasta, com a lista de decks", async ({ page }) => {
      await abrirLogado(page, "/?folder=2");
      await expect(page.locator(".lista-deck").first()).toBeVisible({ timeout: 15000 });
      await conferirLayout(page, "pasta com decks");
      const nome = page.locator(".lista-deck .lista-nome").first();
      const caixa = await nome.boundingBox();
      expect(caixa.width, "o nome do deck precisa de largura real na lista").toBeGreaterThan(80);
    });

    test("lista de cards de um deck", async ({ page }) => {
      await abrirLogado(page, "/?folder=2");
      await expect(page.locator(".lista-deck .lista-info").first()).toBeVisible({ timeout: 15000 });
      await page.locator(".lista-deck .lista-info").first().click();
      await expect(page.locator(".lista-cards, .cards-lista-topo").first()).toBeVisible({ timeout: 15000 });
      await conferirLayout(page, "cards do deck");
    });

    test("modo Aprender — pergunta e resposta", async ({ page }) => {
      await abrirLogado(page, "/?folder=2");
      // 15s, como no celular: com 27 testes em paralelo, os 5s padrão piscavam.
      await expect(page.locator(".lista-deck .lista-info").first()).toBeVisible({ timeout: 15000 });
      await page.locator(".lista-deck .lista-info").first().click();
      await page.getByRole("button", { name: /Aprender|Estudar hoje|Estudar críticos/ }).click();
      await expect(page.locator(".quiz-opcao").first()).toBeVisible();
      await conferirLayout(page, "aprender — pergunta");
      await page.locator(".quiz-opcao").first().click();
      await expect(page.locator(".quiz-explicacao")).toBeVisible();
      await conferirLayout(page, "aprender — resposta");
    });

    test("conta nova, ainda sem nada criado", async ({ page }) => {
      await abrirContaVazia(page);
      await expect(page.locator(".primeiro-uso")).toBeVisible();
      await conferirLayout(page, "conta nova");
    });

    test("área da conta", async ({ page }) => {
      await abrirLogado(page, "/conta");
      await expect(page.locator(".conta-identidade")).toBeVisible();
      await conferirLayout(page, "conta");
    });

    test("criar deck", async ({ page }) => {
      await abrirLogado(page, "/criar-deck");
      await expect(page.getByText("Criar deck")).toBeVisible();
      await conferirLayout(page, "criar deck");
    });

    test("as ações secundárias do deck ficam atrás do ⋯, e o nome sobrevive", async ({ page }) => {
      // Mesmo arranjo do celular, pelo mesmo motivo: sem hover, os três
      // botões de renomear/mover/excluir ou ficam sempre visíveis (e
      // comem o nome do deck) ou vão pro "⋯". Antes ficavam com opacity
      // 0 no tablet -- presentes, ocupando espaço, inalcançáveis.
      await abrirLogado(page, "/?folder=2");
      const linha = page.locator(".lista-deck").first();
      await expect(linha).toBeVisible({ timeout: 15000 });

      await expect(linha.getByTitle("Renomear deck")).toBeHidden();
      await linha.getByTitle("Mais ações").click();
      await expect(linha.getByTitle("Renomear deck")).toBeVisible();
      await expect(linha.getByTitle("Mover deck")).toBeVisible();
      await expect(linha.getByTitle("Excluir deck")).toBeVisible();
      await conferirLayout(page, "deck com ⋯ aberto");
      await linha.getByTitle("Fechar").click();
      await expect(linha.getByTitle("Mais ações")).toBeVisible();
    });

    test("lista de pastas com selo de urgência", async ({ page }) => {
      await abrirLogado(page, "/", { modoLista: true });
      await expect(page.locator(".lista-pasta").first()).toBeVisible({ timeout: 15000 });
      await conferirLayout(page, "lista com selo");
    });
  });
}
