// offlineDecks.js — os decks que o usuário baixou pra estudar sem internet.
//
// Nível 3B do roadmap de resiliência offline. O Nível 2 já garantia que a
// RESPOSTA não se perde; aqui o que passa a sobreviver é o CONTEÚDO: dá
// pra abrir o app no avião e estudar um deck do zero.
//
// Dois armazenamentos, de propósito:
//
//   - localStorage guarda o REGISTRO (id, título, quando baixou). É
//     pequeno, é síncrono, e o Dashboard precisa dele na hora de desenhar
//     a lista e os ícones -- ler isso de forma assíncrona faria a tela
//     piscar a cada render.
//   - Cache API guarda os DADOS dos cards (podem ser centenas de cards com
//     alternativas e explicações -- muito pro limite de ~5MB do
//     localStorage, e é exatamente pra isso que a Cache API existe).
//
// Não usa IndexedDB porque a Cache API resolve com API menor e sem
// dependência nova; o projeto inteiro é sem bibliotecas de estado.
import { api, token } from "./api.js";

const CHAVE_REGISTRO = "estalo_decks_offline";
const CACHE_DADOS = "estalo-deck-dados";

// URL sintética (nunca vai à rede) usada só como chave dentro da Cache API,
// que indexa por Request. Inclui o usuário pra não misturar contas no mesmo
// navegador -- mesma preocupação do outbox.js.
function _chaveCache(userId, deckId) {
  return `/offline/u${userId}/deck/${deckId}`;
}

function _lerRegistro() {
  try {
    return JSON.parse(localStorage.getItem(CHAVE_REGISTRO) || "{}");
  } catch {
    return {};
  }
}

function _gravarRegistro(reg) {
  try {
    localStorage.setItem(CHAVE_REGISTRO, JSON.stringify(reg));
    return true;
  } catch {
    return false;
  }
}

function _chaveRegistro(userId, deckId) {
  return `${userId}:${deckId}`;
}

/** Decks baixados pelo usuário logado: { [deckId]: { deck, baixadoEm, totalCards } } */
export function listarBaixados() {
  const uid = token.usuarioId();
  if (!uid) return {};
  const reg = _lerRegistro();
  const meus = {};
  for (const [chave, valor] of Object.entries(reg)) {
    const [u, d] = chave.split(":");
    if (u === String(uid)) meus[d] = valor;
  }
  return meus;
}

export function estaBaixado(deckId) {
  const uid = token.usuarioId();
  return uid ? Boolean(_lerRegistro()[_chaveRegistro(uid, deckId)]) : false;
}

/**
 * Baixa (ou atualiza) um deck pra uso offline: busca os cards e as stats e
 * guarda tudo localmente. Precisa de internet -- é a chamada que o usuário
 * dispara de propósito, e também a que roda sozinha ao abrir um deck já
 * baixado estando online (decisão do usuário: manter atualizado sem ele
 * precisar pensar nisso).
 */
export async function baixarDeck(deck) {
  const uid = token.usuarioId();
  if (!uid) throw new Error("Sem usuário logado.");

  const [cards, stats] = await Promise.all([
    api.listarCards(deck.id),
    api.statsEstudo(deck.id).catch(() => null), // stats é enfeite: se falhar, o deck ainda serve pra estudar
  ]);

  const cache = await caches.open(CACHE_DADOS);
  await cache.put(
    _chaveCache(uid, deck.id),
    new Response(JSON.stringify({ cards, stats }), {
      headers: { "Content-Type": "application/json" },
    }),
  );

  const reg = _lerRegistro();
  reg[_chaveRegistro(uid, deck.id)] = {
    deck,
    baixadoEm: new Date().toISOString(),
    totalCards: cards.length,
  };
  _gravarRegistro(reg);
  return cards.length;
}

/** Remove o deck do armazenamento offline (não mexe em nada no servidor). */
export async function removerDeck(deckId) {
  const uid = token.usuarioId();
  if (!uid) return;
  const reg = _lerRegistro();
  delete reg[_chaveRegistro(uid, deckId)];
  _gravarRegistro(reg);
  try {
    const cache = await caches.open(CACHE_DADOS);
    await cache.delete(_chaveCache(uid, deckId));
  } catch {
    // Cache API indisponível -- o registro já saiu, que é o que a UI lê.
  }
}

/** Cards guardados de um deck, ou null se ele não foi baixado. */
export async function cardsOffline(deckId) {
  const uid = token.usuarioId();
  if (!uid) return null;
  try {
    const cache = await caches.open(CACHE_DADOS);
    const resp = await cache.match(_chaveCache(uid, deckId));
    if (!resp) return null;
    return (await resp.json()).cards ?? null;
  } catch {
    return null;
  }
}

/** Stats guardadas de um deck, ou null. */
export async function statsOffline(deckId) {
  const uid = token.usuarioId();
  if (!uid) return null;
  try {
    const cache = await caches.open(CACHE_DADOS);
    const resp = await cache.match(_chaveCache(uid, deckId));
    if (!resp) return null;
    return (await resp.json()).stats ?? null;
  } catch {
    return null;
  }
}
