/**
 * Paridade entre estar online e estar offline.
 *
 * Regra do produto: com os cards baixados, ficar sem internet NÃO deve
 * mudar a cara do app. O usuário entra, vê a mesma hierarquia de pastas,
 * a mesma trilha de navegação e os mesmos decks nos mesmos lugares --
 * a única diferença é que só dá pra ESTUDAR o que ele baixou.
 *
 * Por que virou teste: antes, offline o Dashboard trocava tudo por uma
 * lista chapada dos decks baixados. Além de perder hierarquia e trilha, a
 * lista ignorava a pasta do deck -- "Intune", que mora em MD-102,
 * aparecia na raiz E dentro de qualquer pasta que você abrisse.
 * Informação errada é pior que informação ausente, e nada apontava isso.
 *
 * O teste tira um "retrato" de cada tela nas duas condições e exige que
 * sejam iguais, com exceções nomeadas uma a uma.
 *
 * Não depende do backend (mesma exigência de navegacao.spec.js e
 * layout-mobile.spec.js): toda a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

// Hierarquia: Certificações > MD-102 > { Intune (baixado), Autopilot (não) }
const PASTA_MAE = { id: 1, name: "Certificações", parent_id: null, depth: 1, color: null };
const PASTA_FILHA = { id: 2, name: "MD-102", parent_id: 1, depth: 2, color: null };
const ARVORE = [{ ...PASTA_MAE, children: [{ ...PASTA_FILHA, children: [] }] }];

const DECK_BAIXADO = { id: 10, title: "Intune", description: null, folder_id: 2, created_at: "2026-01-01T00:00:00", total_cards: 2, memorization_pct: 0 };
const DECK_NAO_BAIXADO = { id: 11, title: "Autopilot", description: null, folder_id: 2, created_at: "2026-01-02T00:00:00", total_cards: 2, memorization_pct: 0 };
const DECKS = [DECK_BAIXADO, DECK_NAO_BAIXADO];

const STATS = { total_cards: 2, criticos: 0, hoje: 0, novos: 2, validando: 0, dominados: 0, new_cards: 2, validating: 0, dominated: 0, due_now: 0 };
const CARDS = [
  { id: 100, front: "P1", back: "R1", source: "manual", repetitions: 0, options: ["a", "b", "c"], explanation: "exp" },
  { id: 101, front: "P2", back: "R2", source: "manual", repetitions: 0, options: ["a", "b", "c"], explanation: "exp" },
];

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/**
 * Simula a API. `ref.offline` é lido a cada chamada.
 *
 * Por que não usar context.setOffline(): ele derrubaria também o carregamento
 * do próprio app. Em produção o service worker serve o app offline, mas o
 * servidor de dev usado nos testes não tem service worker (isso já é coberto
 * pela spec do PWA). Aqui o alvo é outro: a camada de DADOS -- se, com o app
 * carregado e a rede morta, a tela se desenha igual a partir do retrato local.
 * Então derrubamos só a API e forçamos navigator.onLine=false, que é o sinal
 * que o app usa pra decidir o que desabilitar.
 */
async function simularApi(page, ref) {
  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    if (ref.offline) return route.abort("internetdisconnected");

    const json = (c) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(c) });
    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev" });
    if (p === "/folders") return json(ARVORE);
    if (p === "/decks") return json(DECKS);
    if (p === "/study/decks/stats") return json({ 10: STATS, 11: STATS });
    if (p === "/study/heatmap-stats") return json({});
    if (p === "/study/streak") return json({ current_streak: 0, longest_streak: 0 });
    if (/^\/decks\/\d+\/cards$/.test(p)) return json(CARDS);
    if (/^\/study\/decks\/\d+\/stats$/.test(p)) return json(STATS);
    return json({});
  });
}

/** O que o usuário vê numa tela — a base da comparação. */
const RETRATO = () => {
  const textos = (s) => [...document.querySelectorAll(s)].map((e) => e.textContent.trim()).filter(Boolean);
  const existe = (s) => document.querySelector(s) !== null;
  return {
    trilha: textos(".breadcrumb-item").join(" / "),
    pastasNaBarraLateral: textos(".sidebar-no-btn"),
    pastasNaTela: textos(".pasta-card-nome, .lista-pasta .lista-nome"),
    decksNaTela: textos(".lista-deck .lista-nome"),
    temBusca: existe(".busca-global-input"),
    temOrdenacao: existe(".ordenacao-select"),
    temMetricas: existe(".visao-geral"),
    temHeatmap: existe(".heatmap-grid"),
    temFaixaRevisao: existe(".hero-revisao"),
  };
};

test.describe("Paridade online x offline", () => {
  /** Carrega tudo online (o que grava o retrato local) e baixa "Intune". */
  async function prepararComDeckBaixado(page) {
    const ref = { offline: false };
    await simularApi(page, ref);
    await page.goto("/login");
    await page.evaluate((t) => localStorage.setItem("estalo_token", t), tokenFalso());

    await page.goto("/?folder=2");
    await expect(page.locator(".lista-deck").first()).toBeVisible();
    await page.locator(".lista-deck").filter({ hasText: "Intune" }).getByTitle(/Baixar deck/).click();
    await expect(page.locator(".lista-deck").filter({ hasText: "Intune" }).getByTitle(/Disponível offline/)).toBeVisible();
    return ref;
  }

  /** Corta a rede de verdade do ponto de vista do app: API morta e
   *  navigator.onLine=false a partir da próxima navegação. */
  async function cortarRede(page, ref) {
    ref.offline = true;
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "onLine", { get: () => false, configurable: true });
    });
  }

  /**
   * Abre a rota do zero. Recarregar (e não navegar por clique) é essencial:
   * o Dashboard só busca dados ao MONTAR, então clicando na barra lateral
   * ele reusaria o que já estava em memória e o teste passaria mesmo sem
   * retrato nenhum -- foi exatamente esse falso "ok" que apareceu na
   * primeira versão desta spec. Abrir o app já offline é o caso real.
   */
  async function irPara(page, rota) {
    await page.goto(rota);
    await page.waitForTimeout(900);
  }

  async function retratoDe(page, rota) {
    await irPara(page, rota);
    return page.evaluate(RETRATO);
  }

  test("as telas ficam idênticas offline, exceto o que exige rede", async ({ page }) => {
    const ref = await prepararComDeckBaixado(page);
    const rotas = ["/", "/?folder=1", "/?folder=2"];

    const online = {};
    for (const r of rotas) online[r] = await retratoDe(page, r);

    await cortarRede(page, ref);
    for (const r of rotas) {
      const offline = await retratoDe(page, r);
      expect(offline, `a tela ${r} mudou de cara offline`).toEqual(online[r]);
    }
  });

  test("offline, o deck baixado estuda e o não baixado aparece indisponível", async ({ page }) => {
    const ref = await prepararComDeckBaixado(page);
    await cortarRede(page, ref);
    await irPara(page, "/?folder=2");
    await expect(page.locator(".lista-deck").first()).toBeVisible();

    const baixado = page.locator(".lista-deck").filter({ hasText: "Intune" });
    const naoBaixado = page.locator(".lista-deck").filter({ hasText: "Autopilot" });

    // O não baixado continua VISÍVEL (não some da lista) mas não estuda.
    await expect(naoBaixado).toBeVisible();
    await expect(naoBaixado.getByRole("button", { name: "Estudar" })).toBeDisabled();
    await expect(baixado.getByRole("button", { name: "Estudar" })).toBeEnabled();
  });

  test("offline, o deck baixado abre e o quiz roda", async ({ page }) => {
    const ref = await prepararComDeckBaixado(page);
    await cortarRede(page, ref);
    await irPara(page, "/?folder=2");
    await page.locator(".lista-deck").filter({ hasText: "Intune" }).getByRole("button", { name: "Estudar" }).click();
    await expect(page.locator(".quiz-opcao").first()).toBeVisible({ timeout: 15000 });
  });

  test("sem as estatísticas, a tela não comemora — diz que não sabe", async ({ page }) => {
    // Zero pendentes e "não sei quantos" são coisas diferentes. Se a carga
    // morre entre /decks e /study/decks/stats e depois cai a rede, o
    // retrato tem os decks mas nenhuma stat -- e a tela dizia "Parabéns!
    // Está tudo em dia ✓". Um estudante que acredita nisso pula o dia.
    // Mesma régua do Dashboard de conta nunca carregada: informação
    // errada é pior que informação ausente.
    const ref = { offline: false };
    await simularApi(page, ref);
    await page.goto("/login");
    await page.evaluate((t) => localStorage.setItem("estalo_token", t), tokenFalso());

    // Carrega tudo MENOS as stats, pra o retrato nascer sem elas.
    // Regex, e não glob: a URL leva query (?ids=10,11) e o glob
    // "**/study/decks/stats" não casaria -- a primeira versão deste teste
    // falhou exatamente por isso, deixando as stats passarem.
    await page.route(/\/study\/decks\/stats/, (route) => route.abort("internetdisconnected"));
    await page.goto("/");
    await page.waitForTimeout(900);

    await cortarRede(page, ref);
    await irPara(page, "/");

    await expect(page.locator(".hero-revisao")).toContainText("Revisões ainda não conferidas");
    await expect(page.locator(".hero-revisao")).not.toContainText(/tudo em dia/i);
    // E o número não vira 0: vira "não sei".
    await expect(page.locator(".visao-geral")).toContainText("—");
  });

  test("offline, o que muda dados fica desabilitado em vez de falhar depois do clique", async ({ page }) => {
    const ref = await prepararComDeckBaixado(page);
    await cortarRede(page, ref);
    await irPara(page, "/?folder=2");
    await expect(page.locator(".lista-deck").first()).toBeVisible();

    await expect(page.getByRole("button", { name: "+ Novo Deck" })).toBeDisabled();
    // Busca pelo nome acessível (aria-label), que NÃO muda com a conexão --
    // só a dica do title muda. Um leitor de tela precisa saber o que o
    // botão é, independentemente de estar disponível agora.
    const linha = page.locator(".lista-deck").filter({ hasText: "Intune" });
    for (const acao of ["Renomear deck", "Mover deck", "Excluir deck"]) {
      await expect(linha.getByRole("button", { name: acao }), `"${acao}" deveria estar travado offline`).toBeDisabled();
    }
  });
});
