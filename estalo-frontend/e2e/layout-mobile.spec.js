/**
 * Auditoria de layout no celular.
 *
 * Por que existe: o nome do deck na lista chegou a ficar com 0px de
 * largura no celular -- dava pra ver ícone, barra e botões, mas não QUAL
 * deck era aquele. E não quebrou de uma vez: foi degradando (8px, depois
 * 0px conforme botões novos entravam na linha), sem ninguém notar, até
 * alguém abrir no telefone. Revisão de código não pega isso; medição pega.
 *
 * O que ele garante, em cada tela, num viewport de celular:
 *   1. a página não rola pra lado;
 *   2. nenhum texto visível foi espremido até 0px de largura;
 *   3. nada vaza pra fora da viewport;
 *   4. todo alvo de toque tem pelo menos ALVO_MIN px.
 *
 * A sonda, os dados de mentira e a API simulada moram em
 * auditoria-layout.js, compartilhados com layout-tablet.spec.js.
 *
 * NÃO depende do backend: toda chamada de API é interceptada e respondida
 * com dados de mentira lá. Isso é requisito -- o job de e2e do
 * CI roda sem banco, sem chave de IA e sem segredo nenhum (ver
 * .github/workflows/frontend-ci.yml), igual navegacao.spec.js.
 */
import { test, expect } from "@playwright/test";
import { simularApi, abrirContaVazia, abrirLogado, conferirLayout } from "./auditoria-layout.js";

// Pixel 7 / Galaxy S22 — tela Android comum. Não é o menor celular do
// mercado de propósito: se quebra AQUI, quebra em todo lugar.
test.use({
  viewport: { width: 412, height: 915 },
  isMobile: true,
  hasTouch: true,
  deviceScaleFactor: 2,
});

// --------------------------------------------------------------- testes

test.describe("Layout no celular", () => {
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
    await expect(page.locator(".lista-deck").first()).toBeVisible();
    await conferirLayout(page, "pasta com decks");
  });

  test("o nome do deck continua visível na lista", async ({ page }) => {
    // Regressão específica: este é o bug que motivou a suíte. Um assert
    // dedicado (e não só a sonda genérica) porque é o caso que já quebrou
    // e o que mais dói -- lista de decks sem saber qual é qual.
    await abrirLogado(page, "/?folder=2");
    const nome = page.locator(".lista-deck .lista-nome").first();
    await expect(nome).toBeVisible();
    const caixa = await nome.boundingBox();
    expect(caixa.width, "o nome do deck precisa de largura real na lista").toBeGreaterThan(80);
  });

  test("lista de cards de um deck", async ({ page }) => {
    // A tela de Cards exige o deck no state do router: abrir /deck/10
    // direto volta pra raiz. Entrar pelo Dashboard é o caminho real do
    // usuário -- e é só o que este teste precisa. (Antes ele carregava
    // /deck/10 primeiro, só pra ver o bounce: duas cargas de página a
    // mais, num teste que já era o mais lento da suíte.)
    await abrirLogado(page, "/?folder=2");
    // Espera a linha existir antes de clicar. Sem isso o teste piscava sob
    // carga (a suíte inteira em paralelo): o Dashboard redesenha a linha
    // quando as stats chegam, e um clique disparado nesse meio-tempo mira
    // um elemento que some -- 30s de timeout esperando um alvo que já foi
    // substituído.
    await expect(page.locator(".lista-deck .lista-info").first()).toBeVisible({ timeout: 15000 });
    await page.locator(".lista-deck .lista-info").first().click();
    // Timeout generoso: a tela de cards ainda busca a lista ao montar, e
    // com a suíte inteira em paralelo os 5s padrão do expect não bastavam
    // (~1 falha a cada 3 execuções). Não é bug do app, é máquina ocupada.
    await expect(page.locator(".lista-cards, .cards-lista-topo").first()).toBeVisible({ timeout: 15000 });
    await conferirLayout(page, "cards do deck");
  });

  test("modo Aprender — pergunta e resposta", async ({ page }) => {
    await abrirLogado(page, "/?folder=2");
    await expect(page.locator(".lista-deck .lista-info").first()).toBeVisible();
    await page.locator(".lista-deck .lista-info").first().click();
    // O CTA de estudo troca de texto conforme o estado do deck
    // ("Aprender" / "Estudar hoje (n)" / "🔴 Estudar críticos (n)") --
    // casar por regex evita o teste quebrar por causa dos dados de mentira.
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

    // Regressão de conteúdo, não de layout: o Card Herói dizia "Parabéns!
    // Está tudo em dia ✓" pra quem nunca estudou -- parabenizava por um
    // trabalho inexistente, e era a primeira frase que a pessoa lia.
    await expect(page.locator(".hero-revisao")).toHaveCount(0);

    await conferirLayout(page, "conta nova");
  });

  test("área da conta", async ({ page }) => {
    await abrirLogado(page, "/conta");
    await expect(page.locator(".conta-identidade")).toBeVisible();
    await conferirLayout(page, "conta");
  });

  test("na lista, dá pra ver qual pasta está crítica", async ({ page }) => {
    // Regressão que o usuário achou no telefone: ao esconder a barra
    // segmentada das linhas (pra o nome caber), sumiu o ÚNICO sinal de
    // criticidade das pastas -- decks têm o botão "🔴 N", pastas não
    // tinham nada. Três pastas com 7 críticos, 4 pra hoje e em dia ficavam
    // idênticas. O selo é o sinal que sobrevive no celular.
    await abrirLogado(page, "/", { modoLista: true });
    const linha = page.locator(".lista-pasta").first();
    await expect(linha).toBeVisible({ timeout: 15000 });

    // A pasta de teste tem decks com criticos: 1 (ver STATS).
    const selo = linha.locator(".selo-urgencia");
    await expect(selo).toBeVisible();
    await expect(selo).toHaveClass(/critico/);
    // Visível de verdade: fora do nome, pra o ellipsis de um nome longo
    // não engoli-lo (a primeira versão fazia isso, e o nome de teste é
    // longo de propósito).
    const caixa = await selo.boundingBox();
    expect(caixa.width).toBeGreaterThan(20);
    await conferirLayout(page, "lista com selo");
  });

  test("criar deck", async ({ page }) => {
    await abrirLogado(page, "/criar-deck");
    await expect(page.getByText("Criar deck")).toBeVisible();
    await conferirLayout(page, "criar deck");
  });

  test("as ações secundárias do deck ficam atrás do ⋯, sem sumir", async ({ page }) => {
    // No celular a linha só comporta Estudar + baixar; renomear/mover/
    // excluir vão pro "⋯". Este teste garante que elas continuam
    // ALCANÇÁVEIS -- esconder não pode virar remover.
    await abrirLogado(page, "/?folder=2");
    const linha = page.locator(".lista-deck").first();

    await expect(linha.getByTitle("Renomear deck")).toBeHidden();
    await linha.getByTitle("Mais ações").click();

    await expect(linha.getByTitle("Renomear deck")).toBeVisible();
    await expect(linha.getByTitle("Mover deck")).toBeVisible();
    await expect(linha.getByTitle("Excluir deck")).toBeVisible();

    await linha.getByTitle("Fechar").click();
    await expect(linha.getByTitle("Mais ações")).toBeVisible();
    await expect(linha.getByTitle("Renomear deck")).toBeHidden();
  });
});
