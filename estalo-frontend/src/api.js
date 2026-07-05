// api.js — o ponto único de contato com o backend.
//
// Toda conversa com a API passa por aqui. Isso centraliza duas coisas chatas
// que senão você repetiria em toda tela: o endereço base e o crachá (token).

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Calculado uma vez (não muda durante a sessão) — nome IANA do fuso do
// navegador (ex: "America/Sao_Paulo"), mandado em toda request pra o
// backend saber onde cai a meia-noite de "hoje" pra esse usuário (streak,
// crítico/hoje, elegibilidade de resposta). Nunca é usado pra armazenar
// nada — o banco continua sempre em UTC.
const FUSO_HORARIO = Intl.DateTimeFormat().resolvedOptions().timeZone;

// O crachá fica guardado no navegador (localStorage), então o login
// "gruda" mesmo se você recarregar a página.
export const token = {
  get: () => localStorage.getItem("estalo_token"),
  set: (t) => localStorage.setItem("estalo_token", t),
  clear: () => localStorage.removeItem("estalo_token"),
};

// Função base: monta a requisição, anexa o crachá e trata erro.
async function request(path, { method = "GET", body, form } = {}) {
  const headers = { "X-User-Timezone": FUSO_HORARIO };
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

  const resp = await fetch(`${BASE}${path}`, { method, headers, body: payload });

  if (!resp.ok) {
    // Tenta ler a mensagem de erro que o backend mandou.
    let detalhe = `Erro ${resp.status}`;
    try {
      const j = await resp.json();
      if (j.detail) detalhe = j.detail;
    } catch {
      /* resposta sem corpo JSON */
    }
    throw new Error(detalhe);
  }

  // 204 = sucesso sem conteúdo (ex: exclusão). Não tenta ler JSON.
  if (resp.status === 204) return null;
  return resp.json();
}

// --- Funções específicas que as telas usam ---

export const api = {
  registrar: (email, password) =>
    request("/auth/register", { method: "POST", body: { email, password } }),

  login: (email, password) =>
    request("/auth/login", { method: "POST", form: { username: email, password } }),

  eu: () => request("/auth/me"),

  listarPastas: () => request("/folders"),

  criarPasta: (name, parent_id = null, color = null) =>
    request("/folders", { method: "POST", body: { name, parent_id, color } }),

  renomearPasta: (id, name, color) =>
    request(`/folders/${id}`, { method: "PATCH", body: { name, color } }),

  excluirPasta: (id) => request(`/folders/${id}`, { method: "DELETE" }),

  listarDecks: () => request("/decks"),

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

  responderCard: (cardId, quality, ignorarElegibilidade = false) =>
    request(`/study/cards/${cardId}/answer`, {
      method: "POST",
      body: { quality, ignorar_elegibilidade: ignorarElegibilidade },
    }),

  statsEstudo: (deckId) => request(`/study/decks/${deckId}/stats`),

  heatmapStats: () => request("/study/heatmap-stats"),

  streak: () => request("/study/streak"),

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
    return request(`/study/decks/stats?ids=${deckIds.join(",")}`);
  },

  listarCards: (deckId) => request(`/decks/${deckId}/cards`),

  criarCard: (deckId, front, back) =>
    request(`/decks/${deckId}/cards`, { method: "POST", body: { front, back } }),

  excluirCard: (cardId) => request(`/cards/${cardId}`, { method: "DELETE" }),

  gerarCardsIA: (deckId, text, quantity) =>
    request(`/decks/${deckId}/cards/generate`, { method: "POST", body: { text, quantity } }),

  gerarQuiz: (deckId) =>
    request(`/study/decks/${deckId}/quiz`, { method: "POST" }),

  gerarRevelar: (deckId) =>
    request(`/study/decks/${deckId}/reveal`, { method: "POST" }),
};
