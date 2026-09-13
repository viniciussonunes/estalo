// api.js — o ponto único de contato com o backend.
//
// Toda conversa com a API passa por aqui. Isso centraliza duas coisas chatas
// que senão você repetiria em toda tela: o endereço base e o crachá (token).

import { emitirToastErro } from "./toastBus.js";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Calculado uma vez (não muda durante a sessão) — nome IANA do fuso do
// navegador (ex: "America/Sao_Paulo"), mandado em toda request pra o
// backend saber onde cai a meia-noite de "hoje" pra esse usuário (streak,
// crítico/hoje, elegibilidade de resposta). Nunca é usado pra armazenar
// nada — o banco continua sempre em UTC.
const FUSO_HORARIO = Intl.DateTimeFormat().resolvedOptions().timeZone;

// Lançada quando o backend recusa uma chamada por limite diário de tokens
// de IA estourado (HTTP 429 -- ver Quota Manager em app/services/ai.py).
// Classe própria (não um Error genérico) pra quem chama poder decidir
// tratar isso de um jeito diferente de "deu erro qualquer" (ver
// pedirTutor em Aprender.jsx).
export class QuotaExceededException extends Error {
  constructor(message) {
    super(message);
    this.name = "QuotaExceededException";
  }
}

// Lançada quando o fetch falha por REDE (servidor inalcançável, sem
// internet) -- distinta de um erro de negócio vindo do backend. Classe
// própria pra quem chama poder decidir re-tentar (ver comRetry em
// Aprender.jsx): erro de rede é transitório, erro de negócio (4xx) não.
export class NetworkException extends Error {
  constructor() {
    super("Sem conexão com o servidor.");
    this.name = "NetworkException";
  }
}

// O crachá fica guardado no navegador (localStorage), então o login
// "gruda" mesmo se você recarregar a página.
export const token = {
  get: () => localStorage.getItem("estalo_token"),
  set: (t) => localStorage.setItem("estalo_token", t),
  clear: () => localStorage.removeItem("estalo_token"),

  /**
   * Id do usuário dono do token atual (claim `sub` do JWT), ou null.
   *
   * Lê o payload SEM validar assinatura -- e tudo bem: isto não é controle
   * de acesso (quem valida é o backend, em toda request). É só pra a fila
   * offline saber de QUEM é cada resposta guardada, e não tentar enviar as
   * respostas de uma conta usando o token de outra que logou depois no
   * mesmo navegador (ver outbox.js).
   */
  usuarioId: () => {
    const t = localStorage.getItem("estalo_token");
    if (!t) return null;
    try {
      const payload = JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      return payload.sub ?? null;
    } catch {
      return null;
    }
  },
};

// Função base: monta a requisição, anexa o crachá e trata erro.
async function request(path, { method = "GET", body, form, headers: extra } = {}) {
  const headers = { "X-User-Timezone": FUSO_HORARIO, ...extra };
  const t = token.get();
  if (t) headers["Authorization"] = `Bearer ${t}`;

  let payload;
  if (form) {
    // O login do FastAPI espera dados de formulário, não JSON.
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form).toString();
  } else if (body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let resp;
  try {
    resp = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  } catch (falhaDeRede) {
    // fetch só lança aqui por falha de REDE de verdade (servidor
    // inalcançável, sem internet) -- nunca por causa de um status de erro
    // HTTP normal (isso vira resp.ok=false abaixo, sempre tratado por quem
    // chamou). É exatamente o caso que hoje passava batido pro usuário:
    // a internet cai no meio de uma sessão e ninguém avisa -- só um
    // console.error que ninguém vê. Aqui sim generaliza pra toda chamada
    // da API de uma vez, sem precisar mexer tela por tela.
    // Só dispara o toast quando o navegador acha que ESTÁ online -- ou
    // seja, "você tem internet mas o servidor não respondeu" (aí o toast é
    // o único sinal). Se está offline de verdade (navigator.onLine false),
    // a faixa fixa do OfflineBanner já está na tela dizendo isso -- não
    // precisa também de um toast, ainda mais durante um retry que pode se
    // recuperar sozinho.
    if (typeof navigator === "undefined" || navigator.onLine) {
      emitirToastErro("Sem conexão com o servidor. Verifique sua internet e tente de novo.");
    }
    // NetworkException (não Error cru): mensagem amigável já embutida
    // (`.message` = "Sem conexão com o servidor.", pega pelos <p class="erro">
    // de Cards.jsx/CriarDeck.jsx no lugar do "Failed to fetch" do navegador)
    // e tipo identificável pra quem quiser re-tentar (comRetry em Aprender.jsx).
    throw new NetworkException();
  }

  if (!resp.ok) {
    // Tenta ler a mensagem de erro que o backend mandou.
    let detalhe = `Erro ${resp.status}`;
    try {
      const j = await resp.json();
      if (j.detail) detalhe = j.detail;
    } catch {
      /* resposta sem corpo JSON */
    }
    if (resp.status === 429) throw new QuotaExceededException(detalhe);
    throw new Error(detalhe);
  }

  // 204 = sucesso sem conteúdo (ex: exclusão). Não tenta ler JSON.
  if (resp.status === 204) return null;
  return resp.json();
}

/**
 * Tenta a rede; se cair por falta de conexão, usa a cópia offline (só
 * existe pros decks que o usuário baixou de propósito, ver offlineDecks.js).
 *
 * Fica AQUI, e não em cada tela, pra Aprender/Cards não precisarem saber
 * que existe modo offline -- elas continuam só pedindo os cards.
 *
 * O import é dinâmico de propósito: offlineDecks.js importa `api` deste
 * mesmo arquivo, e um import estático nos dois sentidos criaria um ciclo.
 */
async function _comQuedaParaOffline(promessa, lerLocal) {
  try {
    return await promessa;
  } catch (e) {
    if (!(e instanceof NetworkException)) throw e;
    const local = await lerLocal();
    if (local !== null && local !== undefined) return local;
    throw e; // não baixado: o erro de rede segue sendo a resposta honesta
  }
}

// --- Funções específicas que as telas usam ---

export const api = {
  registrar: (email, password) =>
    request("/auth/register", { method: "POST", body: { email, password } }),

  login: (email, password) =>
    request("/auth/login", { method: "POST", form: { username: email, password } }),

  eu: () => request("/auth/me"),

  // As quatro chamadas que desenham o Dashboard caem no retrato local
  // quando não há rede -- é o que faz a tela offline ser IGUAL à online
  // (mesma hierarquia, mesma trilha, decks nas pastas certas), em vez de
  // virar uma lista chapada. Ver "Retrato da conta" em offlineDecks.js.
  listarPastas: () => _comQuedaParaOffline(
    request("/folders"),
    async () => (await import("./offlineDecks.js")).pastasOffline(),
  ),

  criarPasta: (name, parent_id = null, color = null) =>
    request("/folders", { method: "POST", body: { name, parent_id, color } }),

  renomearPasta: (id, name, color) =>
    request(`/folders/${id}`, { method: "PATCH", body: { name, color } }),

  excluirPasta: (id) => request(`/folders/${id}`, { method: "DELETE" }),

  listarDecks: () => _comQuedaParaOffline(
    request("/decks"),
    async () => (await import("./offlineDecks.js")).decksOffline(),
  ),

  criarDeck: (title, description = null, folder_id = null) =>
    request("/decks", { method: "POST", body: { title, description, folder_id } }),

  renomearDeck: (id, title) =>
    request(`/decks/${id}`, { method: "PATCH", body: { title } }),

  moverDeck: (id, folder_id) =>
    request(`/decks/${id}/move`, { method: "PATCH", body: { folder_id } }),

  excluirDeck: (id) => request(`/decks/${id}`, { method: "DELETE" }),

  atualizarCard: (id, front, back) =>
    request(`/cards/${id}`, { method: "PATCH", body: { front, back } }),

  proximoCard: (deckId) => request(`/study/decks/${deckId}/next`),

  // Fila Única de Revisão ("Estudar Tudo"): mesmo contrato de proximoCard,
  // só que sem deckId — o backend varre todos os decks do usuário e devolve
  // 1 card por chamada, já agrupado por pasta/deck (ver GET /study/global-reviews).
  // folderId opcional escopa a mesma fila pra uma pasta + subpastas
  // ("Estudar Pasta") em vez de todos os decks do usuário.
  proximaRevisaoGlobal: (folderId) =>
    request(folderId ? `/study/global-reviews?folder_id=${folderId}` : "/study/global-reviews"),

  // requestId (UUID) opcional -> header X-Request-ID: o backend guarda em
  // ReviewHistory.request_id e, numa segunda chamada com o MESMO id,
  // devolve o resultado original sem reprocessar (ver responder_card em
  // routers/study.py). É o que torna o retry seguro -- reenviar a mesma
  // resposta não duplica histórico nem reaplica o SM-2.
  // respondidoEm (ISO) opcional: quando a resposta veio da fila offline
  // (outbox.js), é a data em que a pessoa REALMENTE respondeu. O backend
  // ancora nela o histórico (streak/heatmap no dia certo) e o próximo
  // intervalo do SM-2. Ausente = servidor usa o próprio relógio.
  responderCard: (cardId, quality, ignorarElegibilidade = false, requestId = null, respondidoEm = null) =>
    request(`/study/cards/${cardId}/answer`, {
      method: "POST",
      body: {
        quality,
        ignorar_elegibilidade: ignorarElegibilidade,
        ...(respondidoEm ? { respondido_em: respondidoEm } : {}),
      },
      headers: requestId ? { "X-Request-ID": requestId } : undefined,
    }),

  statsEstudo: (deckId) => _comQuedaParaOffline(
    request(`/study/decks/${deckId}/stats`),
    async () => (await import("./offlineDecks.js")).statsOffline(deckId),
  ),

  heatmapStats: () => _comQuedaParaOffline(
    request("/study/heatmap-stats"),
    async () => (await import("./offlineDecks.js")).heatmapOffline(),
  ),

  streak: () => _comQuedaParaOffline(
    request("/study/streak"),
    async () => (await import("./offlineDecks.js")).streakOffline(),
  ),

  // Tutor Inteligente: explicação didática sob demanda pra um card (ver
  // botão "Perguntar ao Tutor" em Aprender.jsx). Primeira chamada gera via
  // IA e o backend cacheia (Card.tutor_explanation); chamadas seguintes
  // pro mesmo card voltam instantâneas.
  tutorExplicarCard: (cardId) =>
    request(`/study/cards/${cardId}/tutor`, { method: "POST" }),

  // Botão "Explicar" do Modo Revelar -- endpoint separado do Tutor
  // Inteligente acima: resposta sempre curta (≤3 frases) e sem cache,
  // pensada pra aparecer inline sem quebrar o fluxo de revelar cards em
  // sequência (ver POST /cards/{id}/tutor, routers/cards.py).
  explicarConceito: (cardId) =>
    request(`/cards/${cardId}/tutor?action=explain`, { method: "POST" }),

  // Mentoria Ativa: analisa a tentativa de resposta do usuário depois de
  // errar (ver botão "Errei" em Estudo.jsx) -- mesma rota do "Explicar"
  // acima, action=analyze em vez de explain. Resposta traz explanation +
  // tipo_erro (omissao/imprecisao/erro_conceitual) + gap_cognitivo.
  analisarFeedback: (cardId, userAttempt) =>
    request(`/cards/${cardId}/tutor?action=analyze`, {
      method: "POST",
      body: { user_attempt: userAttempt },
    }),

  // Resumo de uma rodada do Modo Aprender já encerrada (pro gráfico de
  // evolução do Dashboard). Chamado uma única vez, depois do Promise.all
  // de responderCard (ver _salvarProgresso em Aprender.jsx).
  logarSessao: (totalCards, acertosPrimeira, duracaoSeg, modo) =>
    request("/study/session/log", {
      method: "POST",
      body: { total_cards: totalCards, acertos_primeira: acertosPrimeira, duracao_seg: duracaoSeg, modo },
    }),

  // Auto-cura: pede pro backend gerar quiz (options/explanation) pra cards
  // que já existem mas nasceram sem alternativas. Ver Aprender.jsx (chamado
  // quando a fila recém-carregada tem cards sem quiz pronto).
  enriquecerCards: (cardIds) =>
    request("/study/cards/enrich", { method: "POST", body: { card_ids: cardIds } }),

  // Carrega stats de vários decks numa única chamada; retorna Map<id, stats>.
  // Antes disparava 1 request HTTP por deck (statsMultiplos em paralelo) —
  // GET /study/decks/stats calcula tudo no backend com queries em
  // quantidade fixa, independente de quantos decks existam.
  statsMultiplos: (deckIds) => {
    if (deckIds.length === 0) return Promise.resolve({});
    return _comQuedaParaOffline(
      request(`/study/decks/stats?ids=${deckIds.join(",")}`),
      async () => (await import("./offlineDecks.js")).statsOfflineTodos(),
    );
  },

  listarCards: (deckId) => _comQuedaParaOffline(
    request(`/decks/${deckId}/cards`),
    async () => (await import("./offlineDecks.js")).cardsOffline(deckId),
  ),

  criarCard: (deckId, front, back) =>
    request(`/decks/${deckId}/cards`, { method: "POST", body: { front, back } }),

  excluirCard: (cardId) => request(`/cards/${cardId}`, { method: "DELETE" }),

  gerarCardsIA: (deckId, text, quantity) =>
    request(`/decks/${deckId}/cards/generate`, { method: "POST", body: { text, quantity } }),

  gerarQuiz: (deckId) =>
    request(`/study/decks/${deckId}/quiz`, { method: "POST" }),

  gerarRevelar: (deckId) =>
    request(`/study/decks/${deckId}/reveal`, { method: "POST" }),

  // Painel /admin: gestão de cota de IA por usuário. Backend exige estar
  // em ADMIN_EMAILS (403 pra qualquer outro logado) -- ver AdminPage.jsx.
  adminListarUsuarios: () => request("/admin/users"),

  adminAtualizarLimite: (userId, dailyLimit) =>
    request(`/admin/users/${userId}/limit`, {
      method: "PATCH",
      body: { daily_limit: dailyLimit },
    }),

  // Tutor Inteligente Evolutivo: explica por que UMA alternativa errada
  // específica está incorreta (diferente de tutorExplicarCard, que explica
  // o card em geral). Cache versionado por (card, alternativa) no backend
  // -- a mesma pergunta pro mesmo erro não gasta IA de novo.
  explicarErroCard: (cardId, alternativaEscolhida) =>
    request(`/study/cards/${cardId}/error-explanation`, {
      method: "POST",
      body: { alternativa_escolhida: alternativaEscolhida },
    }),

  // Feedback (👍/👎) sobre a explicação de erro atual. 👎 exige `motivo` e
  // pode devolver uma versão refinada (ver `versao`/`limite_atingido` na
  // resposta).
  feedbackErroCard: (cardId, alternativaEscolhida, positivo, motivo = null) =>
    request(`/study/cards/${cardId}/error-explanation/feedback`, {
      method: "POST",
      body: { alternativa_escolhida: alternativaEscolhida, positivo, motivo },
    }),
};
