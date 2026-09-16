// api.js — o ponto único de contato com o backend.
//
// Toda conversa com a API passa por aqui. Isso centraliza duas coisas chatas
// que senão você repetiria em toda tela: o endereço base e o crachá (token).

import { marcarLenta, marcarQueda, registrarResposta } from "./conexao.js";

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
  constructor(message = "Sem conexão com o servidor.") {
    super(message);
    this.name = "NetworkException";
  }
}

// Uma leitura passou do prazo e foi abortada (só acontece quando existe
// cópia local pra servir no lugar -- ver _comQuedaParaOffline). Subclasse
// de NetworkException de propósito: pra quem trata "caiu", rede lenta
// demais é a mesma coisa.
export class ConexaoLentaException extends NetworkException {
  constructor() {
    super("Conexão lenta demais com o servidor.");
    this.name = "ConexaoLentaException";
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
async function request(path, { method = "GET", body, form, headers: extra, prazoMs } = {}) {
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

  // prazoMs: quem chama só o usa quando tem uma alternativa pra servir no
  // lugar (a cópia local) -- sem alternativa, esperar é a resposta honesta.
  const controle = prazoMs ? new AbortController() : null;
  const cronometro = controle ? setTimeout(() => controle.abort(), prazoMs) : null;
  const inicio = Date.now();
  let resp;
  try {
    resp = await fetch(`${BASE}${path}`, { method, headers, body: payload, signal: controle?.signal });
    // Respondeu: existe servidor do outro lado. Tira a faixa de offline
    // se ela estiver na tela -- ou põe a de "lenta", se demorou demais.
    // Só leituras julgam a demora (ver conexao.js).
    registrarResposta(Date.now() - inicio, method === "GET");
  } catch (falhaDeRede) {
    if (controle?.signal.aborted) {
      // Passou do prazo. Não é queda: o servidor pode até responder daqui
      // a 20s, mas quem estuda não vai esperar pra descobrir. Só leituras
      // mudam o estado da conexão -- uma IA demorada numa rede boa não é
      // rede lenta (ver conexao.js).
      if (method === "GET") marcarLenta();
      throw new ConexaoLentaException();
    }
    // fetch só lança aqui por falha de REDE de verdade (servidor
    // inalcançável, sem internet) -- nunca por causa de um status de erro
    // HTTP normal (isso vira resp.ok=false abaixo, sempre tratado por quem
    // chamou).
    //
    // Aqui NÃO se avisa nada: só se registra o fato. Quem conta pro
    // usuário é a faixa de offline, uma vez, enquanto durar. Antes saía um
    // toast vermelho por request falhada -- e como cada navegação refaz as
    // chamadas, virava um aviso por tela. Pior: saía mesmo quando a tela
    // funcionava inteira a partir da cópia local (ver
    // _comQuedaParaOffline abaixo), ou seja, erro na cara do usuário por
    // algo que não falhou pra ele. Ver src/conexao.js.
    marcarQueda();
    // NetworkException (não Error cru): mensagem amigável já embutida
    // (`.message` = "Sem conexão com o servidor.", pega pelos <p class="erro">
    // de Cards.jsx/CriarDeck.jsx no lugar do "Failed to fetch" do navegador)
    // e tipo identificável pra quem quiser tratar diferente.
    throw new NetworkException();
  } finally {
    if (cronometro) clearTimeout(cronometro);
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
 * E se a rede só DEMORAR: com cópia local disponível, a leitura tem prazo
 * (PRAZO_COM_COPIA_MS) -- passou, aborta e serve a cópia, silencioso. Sem
 * cópia, não há prazo: esperar é a única resposta honesta, e um erro aos
 * 3s seria pior que os cards chegarem aos 25s. A rede continua sendo
 * tentada primeiro em toda leitura, então a volta ao normal é automática:
 * a primeira que responde no prazo já desliga a faixa de "lenta".
 *
 * Fica AQUI, e não em cada tela, pra Aprender/Cards não precisarem saber
 * que existe modo offline -- elas continuam só pedindo os cards.
 *
 * O import é dinâmico de propósito: offlineDecks.js importa `api` deste
 * mesmo arquivo, e um import estático nos dois sentidos criaria um ciclo.
 */
const PRAZO_COM_COPIA_MS = 3000;

async function _comQuedaParaOffline(caminho, lerLocal) {
  const local = await lerLocal();
  const temCopia = local !== null && local !== undefined;
  try {
    return await request(caminho, temCopia ? { prazoMs: PRAZO_COM_COPIA_MS } : {});
  } catch (e) {
    if (!(e instanceof NetworkException)) throw e;
    if (temCopia) return local;
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

  // Quanto de IA esta conta já usou hoje. Antes disso o usuário só
  // descobria o limite batendo nele (ver QuotaLimitModal).
  minhaCota: () => request("/auth/me/quota"),

  //
  // Guarda o crachá novo que o backend devolve, e isso NÃO é detalhe:
  // trocar a senha derruba todos os tokens da geração anterior -- o desta
  // aba inclusive. Sem trocar aqui, quem acabou de mudar a senha levaria
  // 401 na request seguinte e cairia no login.
  trocarSenha: async (senhaAtual, senhaNova) => {
    const r = await request("/auth/change-password", {
      method: "POST",
      body: { senha_atual: senhaAtual, senha_nova: senhaNova },
    });
    if (r?.access_token) token.set(r.access_token);
    return r;
  },

  // As quatro chamadas que desenham o Dashboard caem no retrato local
  // quando não há rede -- é o que faz a tela offline ser IGUAL à online
  // (mesma hierarquia, mesma trilha, decks nas pastas certas), em vez de
  // virar uma lista chapada. Ver "Retrato da conta" em offlineDecks.js.
  listarPastas: () => _comQuedaParaOffline(
    "/folders",
    async () => (await import("./offlineDecks.js")).pastasOffline(),
  ),

  criarPasta: (name, parent_id = null, color = null) =>
    request("/folders", { method: "POST", body: { name, parent_id, color } }),

  renomearPasta: (id, name, color) =>
    request(`/folders/${id}`, { method: "PATCH", body: { name, color } }),

  excluirPasta: (id) => request(`/folders/${id}`, { method: "DELETE" }),

  listarDecks: () => _comQuedaParaOffline(
    "/decks",
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
    `/study/decks/${deckId}/stats`,
    async () => (await import("./offlineDecks.js")).statsOffline(deckId),
  ),

  heatmapStats: () => _comQuedaParaOffline(
    "/study/heatmap-stats",
    async () => (await import("./offlineDecks.js")).heatmapOffline(),
  ),

  streak: () => _comQuedaParaOffline(
    "/study/streak",
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
  // prazoMs: a auto-cura do quiz roda ANTES de a sessão começar (ver
  // _repararSemQuiz em Aprender.jsx), e o backend pode levar até ~55s
  // (2 tentativas + reserva de provedor). Quem estuda não espera isso:
  // passou o prazo, a sessão começa com os cards que já têm quiz -- e o
  // servidor termina o trabalho mesmo assim, pra próxima vez.
  enriquecerCards: (cardIds, { prazoMs } = {}) =>
    request("/study/cards/enrich", { method: "POST", body: { card_ids: cardIds }, prazoMs }),

  // Carrega stats de vários decks numa única chamada; retorna Map<id, stats>.
  // Antes disparava 1 request HTTP por deck (statsMultiplos em paralelo) —
  // GET /study/decks/stats calcula tudo no backend com queries em
  // quantidade fixa, independente de quantos decks existam.
  statsMultiplos: (deckIds) => {
    if (deckIds.length === 0) return Promise.resolve({});
    return _comQuedaParaOffline(
      `/study/decks/stats?ids=${deckIds.join(",")}`,
      async () => (await import("./offlineDecks.js")).statsOfflineTodos(),
    );
  },

  listarCards: (deckId) => _comQuedaParaOffline(
    `/decks/${deckId}/cards`,
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
