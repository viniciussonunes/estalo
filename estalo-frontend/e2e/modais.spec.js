/**
 * Comportamento de teclado e de foco dos modais.
 *
 * Por que existe: os cinco modais do app eram cinco cópias do mesmo HTML,
 * cada uma com seus próprios buracos. Nenhum fechava com Esc de verdade
 * (o único que tentava desligava o atalho quando o foco estava num campo
 * -- ou seja, sempre), o Tab saía do modal e ia navegar a página atrás, e
 * o overlay `position: fixed` não era fixo: `.pagina` tem uma animação com
 * `transform`, que cria bloco de contenção, então com a página rolada o
 * modal era desenhado lá em cima, fora da tela.
 *
 * Nada disso aparece num print da tela parada. Só medindo.
 *
 * Não depende do backend: toda a API é simulada aqui (mesma regra de
 * navegacao.spec.js, layout-mobile.spec.js e paridade-offline.spec.js).
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

const PASTA = { id: 2, name: "MD-102", parent_id: null, depth: 1, color: null };
const DECK = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 30, memorization_pct: 0 };
const STATS = { total_cards: 30, criticos: 0, hoje: 0, novos: 30, validando: 0, dominados: 0, new_cards: 30, validating: 0, dominated: 0, due_now: 0 };

// Cards suficientes pra página rolar: é a rolagem que expõe o overlay preso
// no bloco de contenção da .pagina.
const CARDS = Array.from({ length: 30 }, (_, i) => ({
  id: 100 + i,
  front: `Pergunta ${i + 1} sobre gerenciamento de dispositivos no Intune`,
  back: `Resposta ${i + 1}`,
  source: "manual",
  repetitions: 0,
  options: ["a", "b", "c"],
  explanation: "exp",
}));

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
    if (/^\/decks\/\d+\/cards$/.test(p)) return json(CARDS);
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(STATS);
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto(rota);
}

/** Abre a tela de cards do deck (o caminho real: pela lista do Dashboard). */
async function abrirTelaDeCards(page) {
  await abrirLogado(page, "/?folder=2");
  await page.locator(".lista-deck .lista-info").first().click();
  await expect(page.getByRole("button", { name: /Adicionar card/ })).toBeVisible();
  // Espera a lista INTEIRA: os testes de rolagem dependem de a página já
  // ter a altura final. Sem isso, sob carga, o teste rolava uma página
  // ainda pela metade e media 126px em vez de milhares (aconteceu).
  await expect(page.locator(".item-card")).toHaveCount(CARDS.length);
}

/** Qual elemento está focado agora, em texto legível. */
const FOCADO = () => {
  const el = document.activeElement;
  if (!el) return "nenhum";
  const dentro = !!el.closest(".modal-painel");
  const classe = typeof el.className === "string" ? el.className.trim().split(/\s+/)[0] : "";
  return `${dentro ? "dentro" : "FORA"}:${el.tagName.toLowerCase()}${classe ? "." + classe : ""}`;
};

/**
 * Rola até o fim e SÓ volta quando a rolagem parou.
 *
 * `mouse.wheel` devolve o controle antes de a rolagem terminar: sob carga
 * (a suíte inteira em paralelo) a leitura veio 802 em vez de 4037 e o teste
 * falhou sozinho. Espera o valor estabilizar em vez de chutar um timeout.
 */
async function rolarAteOFim(page) {
  let anterior = -1;
  for (let i = 0; i < 40; i++) {
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const y = await page.evaluate(() => window.scrollY);
    if (y > 0 && y === anterior) return y;
    anterior = y;
    await page.waitForTimeout(50);
  }
  return anterior;
}

test.describe("Modais", () => {
  test("Esc fecha, inclusive com o foco dentro de um campo", async ({ page }) => {
    await abrirTelaDeCards(page);
    await page.getByRole("button", { name: /Adicionar card/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    // O caso que estava quebrado: digitando no campo, o Esc era ignorado.
    const campo = page.locator(".modal-painel textarea").first();
    await campo.click();
    await campo.fill("um começo de pergunta");
    await page.keyboard.press("Escape");

    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("o Tab não escapa do modal", async ({ page }) => {
    await abrirTelaDeCards(page);
    await page.getByRole("button", { name: /Adicionar card/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    // 25 tabuladas dão a volta várias vezes num modal com ~8 focáveis.
    // Se o foco vazar uma única vez, a lista registra "FORA:".
    const visitados = [];
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press("Tab");
      visitados.push(await page.evaluate(FOCADO));
    }
    expect(visitados.filter(v => v.startsWith("FORA")), "o foco saiu do modal").toEqual([]);
  });

  test("ao fechar, o foco volta pro botão que abriu", async ({ page }) => {
    await abrirTelaDeCards(page);
    const gatilho = page.getByRole("button", { name: /Adicionar card/ });
    await gatilho.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");

    // Sem isso o foco cai no <body> e o próximo Tab recomeça do topo da
    // página -- quem navega por teclado perde o lugar a cada modal.
    await expect(gatilho).toBeFocused();
  });

  test("abrir o modal não arranca a página do lugar", async ({ page }) => {
    // O `position: fixed` do overlay não era fixo: `.pagina` tem
    // `animation: fadeIn ... both` e o fadeIn mexe em `transform`, o que
    // cria bloco de contenção -- medido com uma sonda `fixed` dentro da
    // `.pagina`: com a página em 4037, a sonda aparecia em y=-4037.
    //
    // O sintoma não era "modal invisível", era um tranco: ancorado no topo
    // do documento, o modal fazia o navegador rolar a página inteira pra
    // mostrar o campo que recebe foco. Medido no código antigo: abrir com
    // a página em 4037 jogava pra 1995. Fecha o modal e você não sabe mais
    // onde estava lendo.
    //
    // O modal é aberto pelo atalho 'C', e não por clique: clicar faz o
    // Playwright rolar a página até o botão sozinho, o que mascararia
    // qualquer rolagem causada pelo modal.
    await abrirTelaDeCards(page);
    const antes = await rolarAteOFim(page);
    expect(antes, "a página precisa estar rolada pro teste valer").toBeGreaterThan(1000);

    await page.keyboard.press("c");
    await expect(page.locator(".modal-painel")).toBeVisible();
    await page.waitForTimeout(300);

    expect(await page.evaluate(() => window.scrollY), "a página rolou sozinha ao abrir o modal").toBe(antes);

    // Prova estrutural do conserto: o modal é desenhado fora da .pagina.
    expect(await page.locator(".pagina .modal-overlay").count(), "o modal voltou pra dentro da armadilha da .pagina").toBe(0);

    const caixa = await page.locator(".modal-painel").boundingBox();
    expect(caixa.y, "o modal foi desenhado fora da área visível").toBeGreaterThan(-1);
    expect(caixa.y).toBeLessThan(page.viewportSize().height);
  });

  test("dentro da .pagina, position:fixed é fixo de verdade", async ({ page }) => {
    // A raiz do problema acima, medida direto: `.pagina` tinha `animation:
    // fadeIn ... both`; o `both` deixa o transform do último quadro colado
    // no elemento pra sempre, e transform != none cria bloco de contenção.
    // Trocado por `backwards`. Este teste existe porque a regressão é
    // silenciosa: quem trocar de volta não vê nada de errado na tela, e o
    // próximo elemento fixo que alguém criar é que vai nascer quebrado.
    await abrirTelaDeCards(page);
    await rolarAteOFim(page);

    const r = await page.evaluate(() => {
      const pag = document.querySelector(".pagina");
      const sonda = document.createElement("div");
      sonda.style.cssText = "position:fixed;top:0;left:0;width:10px;height:10px";
      pag.appendChild(sonda);
      const y = sonda.getBoundingClientRect().top;
      sonda.remove();
      return { rolagem: window.scrollY, transform: getComputedStyle(pag).transform, sondaY: y };
    });

    expect(r.rolagem, "a página precisa estar rolada pro teste valer").toBeGreaterThan(1000);
    expect(r.transform, ".pagina voltou a carregar um transform e virou bloco de contenção").toBe("none");
    expect(r.sondaY, "um elemento fixed dentro da .pagina não está mais preso à janela").toBe(0);
  });

  test("o modal de mover deck também fecha com Esc", async ({ page }) => {
    // Segundo modal, em outra tela: garante que o comportamento é do
    // componente compartilhado, e não de um conserto pontual numa tela.
    await abrirLogado(page, "/?folder=2");
    await page.locator(".lista-deck").first().getByTitle("Mover deck").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("o modal se anuncia como diálogo, com nome", async ({ page }) => {
    await abrirTelaDeCards(page);
    await page.getByRole("button", { name: /Adicionar card/ }).click();
    // aria-modal + nome acessível: é o que faz um leitor de tela dizer
    // "diálogo, Adicionar cards" em vez de largar a pessoa no meio do nada.
    await expect(page.getByRole("dialog", { name: "Adicionar cards" })).toBeVisible();
  });
});
