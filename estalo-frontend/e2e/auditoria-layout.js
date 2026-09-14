/**
 * A auditoria de layout, compartilhada entre os viewports.
 *
 * Nasceu em layout-mobile.spec.js (leia o cabeçalho de lá: o nome do deck
 * chegou a 0px de largura no celular sem ninguém notar). Quando o tablet
 * entrou na auditoria, o que era do celular ficou lá e o que é de
 * qualquer tela veio pra cá: os dados de mentira, a API simulada, a
 * sonda que mede em vez de olhar, e as quatro checagens.
 *
 * Não é um spec (o Playwright só roda *.spec.js): é só importado.
 */
import { expect } from "@playwright/test";

// Mínimo de alvo de toque adotado no projeto. As referências de mercado
// são 44px (Apple HIG / WCAG 2.5.5) e 48dp (Material). Ficamos em 40:
// chegar a 44 custaria ~12px do nome do deck em cada linha da lista, e a
// legibilidade do título vale mais que os 4px. Se um dia sobrar largura,
// é só subir este número.
export const ALVO_MIN = 40;

// Caminhos que são, sem ambiguidade, chamadas de API -- e NÃO rotas do SPA
// ("/deck/10" é tela, "/decks" é API; "/login" é tela, "/auth/login" é API).
//
// Casar por CAMINHO, e não por origem, é proposital: o endereço da API vem
// de VITE_API_URL, que muda conforme o ambiente. Na máquina do
// desenvolvedor existe um .env.local (saída do `vercel env pull`) apontando
// pra API de PRODUÇÃO; no CI ele não existe e o padrão é localhost:8000.
// Casar por origem faria o teste passar aqui e falhar lá -- ou pior,
// bater em produção de verdade durante um teste.
export const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

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
export function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** Responde toda chamada de API com dados locais. */
export async function simularApi(page) {
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
export async function abrirContaVazia(page, rota = "/") {
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
export async function abrirLogado(page, rota = "/", { modoLista = false } = {}) {
  await simularApi(page);
  await page.goto("/login");
  await page.evaluate(({ t, modoLista }) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
    // Gravado AQUI, antes de o Dashboard montar: ele persiste o modo
    // atual num efeito ao montar, e gravar depois de um goto("/") corria
    // contra esse efeito -- sob carga, o "grid" dele vencia e o teste da
    // lista abria em blocos.
    if (modoLista) localStorage.setItem("dashboard_view_mode", "list");
  }, { t: tokenFalso(), modoLista });
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

  const vazando = [], zerados = [], alvosPequenos = [], invisiveis = [];
  const semHover = matchMedia("(hover: none)").matches;

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
    // Botão que só aparece no hover, numa tela sem hover: existe, ocupa
    // lugar na linha e ninguém consegue chegar nele. O tablet tinha
    // renomear/mover/excluir assim -- a checagem de tamanho não pegava
    // porque `visivel()` os ignora, de propósito. Aqui é o contrário.
    if (semHover && clicavel && !el.disabled && r.width > 0 && r.height > 0
        && cs.visibility !== "hidden" && Number(cs.opacity) <= 0.05 && (el.offsetParent !== null || cs.position === "fixed")) {
      invisiveis.push(nome(el));
    }
  }

  return {
    rolaLateral: document.documentElement.scrollWidth > vw + 1,
    excesso: Math.max(0, document.documentElement.scrollWidth - vw),
    vazando: [...new Set(vazando)],
    zerados: [...new Set(zerados)],
    alvosPequenos: [...new Set(alvosPequenos)],
    invisiveis: [...new Set(invisiveis)],
  };
};

/** Aplica as cinco checagens, com mensagem que diz exatamente o que quebrou. */
export async function conferirLayout(page, tela) {
  const r = await page.evaluate(SONDA, ALVO_MIN);

  expect(r.rolaLateral, `[${tela}] a página rola na horizontal (${r.excesso}px a mais que a tela)`).toBe(false);
  expect(r.vazando, `[${tela}] elemento(s) vazando pra fora da tela`).toEqual([]);
  expect(r.zerados, `[${tela}] texto espremido até 0px de largura — fica invisível no aparelho`).toEqual([]);
  expect(r.alvosPequenos, `[${tela}] alvo(s) de toque menores que ${ALVO_MIN}px`).toEqual([]);
  expect(r.invisiveis, `[${tela}] botão(ões) que só aparecem no hover — inalcançáveis no toque`).toEqual([]);
}

