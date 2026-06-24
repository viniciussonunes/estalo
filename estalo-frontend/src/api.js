// api.js — o ponto único de contato com o backend.
//
// Toda conversa com a API passa por aqui. Isso centraliza duas coisas chatas
// que senão você repetiria em toda tela: o endereço base e o crachá (token).

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

// O crachá fica guardado no navegador (localStorage), então o login
// "gruda" mesmo se você recarregar a página.
export const token = {
  get: () => localStorage.getItem("estalo_token"),
  set: (t) => localStorage.setItem("estalo_token", t),
  clear: () => localStorage.removeItem("estalo_token"),
};

// Função base: monta a requisição, anexa o crachá e trata erro.
async function request(path, { method = "GET", body, form } = {}) {
  const headers = {};
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

  listarDecks: () => request("/decks"),

  criarDeck: (title, description) =>
    request("/decks", { method: "POST", body: { title, description } }),

  excluirDeck: (id) => request(`/decks/${id}`, { method: "DELETE" }),
};
