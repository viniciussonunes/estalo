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
 * NÃO depende do backend: toda chamada de API é interceptada e respondida
 * com dados de mentira aqui do lado. Isso é requisito -- o job de e2e do
 * CI roda sem banco, sem chave de IA e sem segredo nenhum (ver
 * .github/workflows/frontend-ci.yml), igual navegacao.spec.js.
 */
import { test, expect } from "@playwright/test";

// Pixel 7 / Galaxy S22 — tela Android comum. Não é o menor celular do
// mercado de propósito: se quebra AQUI, quebra em todo lugar.
test.use({
  viewport: { width: 412, height: 915 },
  isMobile: true,
  hasTouch: true,
  deviceScaleFactor: 2,
});

// Mínimo de alvo de toque adotado no projeto. As referências de mercado
// são 44px (Apple HIG / WCAG 2.5.5) e 48dp (Material). Ficamos em 40:
// chegar a 44 custaria ~12px do nome do deck em cada linha da lista, e a
// legibilidade do título vale mais que os 4px. Se um dia sobrar largura,
// é só subir este número.
const ALVO_MIN = 40;

// Caminhos que são, sem ambiguidade, chamadas de API -- e NÃO rotas do SPA
// ("/deck/10" é tela, "/decks" é API; "/login" é tela, "/auth/login" é API).
//
// Casar por CAMINHO, e não por origem, é proposital: o endereço da API vem
// de VITE_API_URL, que muda conforme o ambiente. Na máquina do
// desenvolvedor existe um .env.local (saída do `vercel env pull`) apontando
// pra API de PRODUÇÃO; no CI ele não existe e o padrão é localhost:8000.
// Casar por origem faria o teste passar aqui e falhar lá -- ou pior,
// bater em produção de verdade durante um teste.
const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

// ---------------------------------------------------------------- dados

// Nomes longos de propósito: é com título curto que o layout engana.
const PASTA_MAE = { id: 1, name: "MD-102 - Administrador de Endpoint Associado", parent_id: null, depth: 1, color: null };
const PASTA_FOLHA = { id: 2, name: "Reforço de véspera", parent_id: 1, depth: 2, color: null };

const DECKS = [
  { id: 10, title: "Endpoint Manager - Políticas de Conformidade", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 2, memorization_pct: 0 },
  { id: 11, title: "Autopilot", description: null, folder_id: 2, created_at: "2026-01-02T00:00:00", total_cards: 2, memorization_pct: 50 },
];

const STATS = { total_cards: 2, criticos: 1, hoje: 1, novos: 1, validando: 0, dominados: 0, new_cards: 1, validating: 0, dominated: 0, due_now: 1 };

const CARDS = [
  {
    id: 100, front: "Qual serviço do Intune aplica configurações de conformidade em dispositivos registrados?",
    back: "As políticas de conformidade do Microsoft Intune, avaliadas no check-in do dispositivo.",
    source: "ai", repetitions: 0,
    options: ["Compliance Manager do Microsoft 365", "Azure Policy aplicado ao locatário", "Configuration Manager em co-gerenciamento"],
    explanation: "As políticas de conformidade do Intune avaliam o dispositivo no check-in e reportam o estado.",
  },
  {
    id: 101, front: "O que é o Windows Autopilot?", back: "Provisionamento zero-touch de dispositivos novos.",
    source: "manual", repetitions: 1,
    options: ["Uma ferramenta de imagem de disco", "Um antivírus gerenciado", "Um servidor de atualizações"],
    explanation: "O Autopilot configura o dispositivo já na primeira inicialização, sem imagem.",
  },
];

/** JWT falso e bem-formado: api.js decodifica o payload pra saber de quem
 *  é a fila offline (token.usuarioId). Não precisa de assinatura válida --
 *  quem valida é o backend, que aqui nem é chamado. */
function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** Responde toda chamada de API com dados locais. */
async function simularApi(page) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;

    // Só XHR/fetch pra um caminho de API. A checagem de tipo garante que
    // navegação e assets do próprio app nunca são capturados por engano.
    const ehChamadaDeApi = ["xhr", "fetch"].includes(req.resourceType()) && CAMINHOS_API.test(p);
    if (!ehChamadaDeApi) return route.continue();

    const json = (corpo) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(corpo) });

    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json([{ ...PASTA_MAE, children: [{ ...PASTA_FOLHA, children: [] }] }]);
    if (p === "/decks") return json(DECKS);
    if (p === "/study/decks/stats") return json({ 10: STATS, 11: STATS });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 3, longest_streak: 9 });
    if (p === "/study/global-reviews") return json([]);
    if (/^\/decks\/\d+\/cards$/.test(p)) return json(CARDS);
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(STATS);
    if (/^\/study\/decks\/\d+\/next$/.test(p)) return json({ card_id: 100, front: CARDS[0].front, back: CARDS[0].back, due_date: "2026-01-01T00:00:00", repetitions: 0, revisoes_hoje: 0 });
    if (/^\/study\/cards\/\d+\/answer$/.test(p)) return json({ card_id: 100, interval: 1, ease_factor: 2.5, repetitions: 1, next_due: "2026-01-02T00:00:00", status: "validando" });
    return json({});
  });
}

/**
 * Conta recém-criada: sem pasta e sem deck nenhum. É a primeira tela que um
 * usuário novo vê e tem layout próprio (o bloco de primeiros passos), então
 * precisa passar pela mesma auditoria das outras.
 */
async function abrirContaVazia(page, rota = "/") {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    const json = (corpo) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(corpo) });
    if (p === "/auth/me") return json({ id: 1, email: "novato@estalo.dev" });
    if (p === "/folders" || p === "/decks" || p === "/study/global-reviews") return json([]);
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    return json({});
  });
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "novato@estalo.dev" }));
  }, tokenFalso());
  await page.goto(rota);
}

/**
 * Entra "logado" sem passar pela tela de login (que não é o alvo aqui).
 *
 * Navega primeiro e só então grava o token: o localStorage é por origem, e
 * antes da primeira navegação a página ainda está em about:blank -- gravar
 * lá não chega no app.
 */
async function abrirLogado(page, rota = "/") {
  await simularApi(page);
  await page.goto("/login");
  await page.evaluate((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());
  await page.goto(rota);
}

// ---------------------------------------------------------------- sonda

/**
 * Roda no navegador e devolve tudo que está fora do padrão na tela atual.
 * Mede em vez de julgar por screenshot -- 8px de largura num nome "parece"
 * certo num print e é invisível de verdade no aparelho.
 */
const SONDA = (ALVO_MIN) => {
  const vw = document.documentElement.clientWidth;
  const nome = (el) => {
    const c = typeof el.className === "string" ? el.className.trim().split(/\s+/)[0] : "";
    return (c ? `.${c}` : el.tagName.toLowerCase()) + (el.title ? ` [${el.title.slice(0, 24)}]` : "");
  };
  const visivel = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && Number(cs.opacity) > 0.05;
  };

  const vazando = [], zerados = [], alvosPequenos = [];

  for (const el of document.querySelectorAll("body *")) {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);

    if (visivel(el) && r.right > vw + 1) {
      vazando.push(`${nome(el)} (+${Math.round(r.right - vw)}px)`);
    }

    // Texto que existe no DOM mas foi espremido até sumir. offsetParent
    // nulo = não renderizado (ancestral display:none, ex: a barra lateral
    // que o mobile esconde); <option> sempre mede 0.
    const texto = (el.textContent || "").trim();
    const folhaComTexto = el.children.length === 0 && texto.length > 0;
    const renderizado = el.offsetParent !== null || cs.position === "fixed";
    if (folhaComTexto && r.width === 0 && renderizado && el.tagName !== "OPTION") {
      zerados.push(`${nome(el)} → "${texto.slice(0, 40)}"`);
    }

    const clicavel = el.tagName === "BUTTON" || el.tagName === "A";
    if (clicavel && visivel(el) && !el.disabled) {
      const menor = Math.round(Math.min(r.width, r.height));
      if (menor < ALVO_MIN) alvosPequenos.push(`${nome(el)} (${menor}px)`);
    }
  }

  return {
    rolaLateral: document.documentElement.scrollWidth > vw + 1,
    excesso: Math.max(0, document.documentElement.scrollWidth - vw),
    vazando: [...new Set(vazando)],
    zerados: [...new Set(zerados)],
    alvosPequenos: [...new Set(alvosPequenos)],
  };
};

/** Aplica as quatro checagens, com mensagem que diz exatamente o que quebrou. */
async function conferirLayout(page, tela) {
  const r = await page.evaluate(SONDA, ALVO_MIN);

  expect(r.rolaLateral, `[${tela}] a página rola na horizontal (${r.excesso}px a mais que a tela)`).toBe(false);
  expect(r.vazando, `[${tela}] elemento(s) vazando pra fora da tela`).toEqual([]);
  expect(r.zerados, `[${tela}] texto espremido até 0px de largura — fica invisível no aparelho`).toEqual([]);
  expect(r.alvosPequenos, `[${tela}] alvo(s) de toque menores que ${ALVO_MIN}px`).toEqual([]);
}

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
