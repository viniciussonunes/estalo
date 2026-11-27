// audioDecks.js — o áudio de um deck: gerar, comprimir, guardar, ouvir.
//
// Mesma divisão de offlineDecks.js, pelos mesmos motivos: o REGISTRO
// (duração, tamanho, quando gravou) vai no localStorage, porque a tela
// precisa dele síncrono pra desenhar sem piscar; os BYTES vão na Cache
// API, porque um episódio de cinco minutos são megabytes e o
// localStorage tem teto de ~5MB pro domínio inteiro.
//
// --- Fase 3: o servidor comprime e guarda ---
// Até 27/11/2026 o backend devolvia PCM cru (~3,6 MB por bloco) e ESTA
// camada comprimia pra MP3 com lamejs. O áudio só existia no aparelho de
// quem gravou. Agora o servidor comprime (lameenc), guarda cada bloco no
// Vercel Blob privado e devolve o MP3 (~0,6 MB por bloco). Pedir um bloco
// que já está guardado devolve o guardado SEM gastar cota -- então baixar
// o áudio num segundo aparelho é este mesmo laço, só que rápido e de
// graça. O lamejs saiu do app.
//
// --- Por que o cliente conduz a fila ---
// Um episódio não cabe no maxDuration de 60s de uma função serverless
// (ver app/routers/audio.py). Então é esta função que pede bloco por
// bloco, em ordem. Fechar a aba interrompe -- e é por isso que o roteiro
// mora no servidor: ao voltar, os blocos que já viraram áudio continuam
// no aparelho e a fila recomeça de onde parou.
//
// --- Por que cada bloco é guardado na hora, e não só no fim ---
// A frase acima era mentira até 06/11/2026: os pedaços ficavam numa
// variável em memória e só iam pra Cache API DEPOIS do último bloco.
// Falhar no bloco 4 de 6 (503 do provedor, cota estourando no meio, aba
// fechada, rede caindo) jogava fora os três primeiros -- cuja cota já
// tinha sido debitada. Tentar de novo pedia tudo desde o bloco 0 e pagava
// duas vezes: num deck de dez blocos, ~27.000 dos 50.000 tokens do dia
// pra entregar um episódio.
//
// Agora cada bloco vira MP3 e é guardado assim que nasce, com a versão do
// roteiro gravada junto (`X-Roteiro`). Retomar é pular o que já existe; o
// que não bate com o roteiro atual é ignorado, pra um roteiro reescrito
// nunca herdar áudio do antigo.
import { api, token } from "./api.js";

const CHAVE_REGISTRO = "estalo_audio_decks";
const CACHE_AUDIO = "estalo-deck-audio";

// A taxa que o TTS do Gemini devolve hoje. É só o PISO: a taxa real vem no
// cabeçalho X-Taxa-Amostragem de cada bloco (e o backend precisa expô-la
// no CORS pra este código conseguir ler -- ver expose_headers em main.py).
const TAXA_PADRAO = 24000;

// Uma mensagem só pros dois jeitos de o armazenamento recusar o áudio
// pronto: a Cache API cheia e o localStorage cheio. Do ponto de vista de
// quem esperou a geração inteira, é o mesmo problema e a mesma saída.
const ERRO_SEM_ESPACO =
  "O áudio ficou pronto, mas não cabe neste aparelho. Libere espaço — " +
  "apagar um deck baixado ou um áudio de outro deck costuma bastar — e grave de novo.";

function _chaveCache(userId, deckId, parte = "completo") {
  return `/audio/u${userId}/deck/${deckId}/${parte}`;
}

function _chaveRegistro(userId, deckId) {
  return `${userId}:${deckId}`;
}

/** A Cache API, ou null se o navegador não der (aba privada antiga). */
async function _abrirCache() {
  try {
    return await caches.open(CACHE_AUDIO);
  } catch {
    return null;
  }
}

/**
 * Guarda um bloco já codificado. Falhar aqui NÃO é fatal: o bloco também
 * está na memória da aba, e o que se perde é só poder retomar. Quem
 * reclama de armazenamento cheio é a gravação do episódio inteiro, no fim
 * de gerarAudio -- lá o áudio é o produto, não um atalho.
 */
async function _guardarBloco(cache, uid, deckId, indice, blob, amostras, taxa, versao) {
  if (!cache) return;
  try {
    await cache.put(
      _chaveCache(uid, deckId, `bloco-${indice}`),
      new Response(blob, {
        headers: {
          "Content-Type": "audio/mpeg",
          // Quantas amostras este bloco tem, pra duração do episódio
          // continuar certa quando ele for reaproveitado, e em que taxa
          // foi codificado. Estes cabeçalhos são nossos, numa Response
          // que nós construímos -- não passam por CORS nenhum.
          "X-Amostras": String(amostras),
          "X-Taxa": String(taxa),
          // A versão do roteiro. Sem isto, um roteiro reescrito ("Gravar
          // de novo") herdaria os blocos do antigo e o episódio sairia
          // com pedaços de duas conversas diferentes.
          "X-Roteiro": versao,
        },
      }),
    );
  } catch {
    /* aparelho sem espaço: segue em memória, só não vai dar pra retomar */
  }
}

/** O bloco guardado deste roteiro, ou null se não há (ou é de outro). */
async function _lerBloco(cache, uid, deckId, indice, versao) {
  if (!cache) return null;
  try {
    const r = await cache.match(_chaveCache(uid, deckId, `bloco-${indice}`));
    if (!r || (r.headers.get("X-Roteiro") || "") !== versao) return null;
    return {
      blob: await r.blob(),
      amostras: Number(r.headers.get("X-Amostras")) || 0,
      taxa: Number(r.headers.get("X-Taxa")) || TAXA_PADRAO,
    };
  } catch {
    return null;
  }
}

/**
 * Apaga o que este deck guardou na Cache API.
 *
 * Varre as chaves em vez de montar os nomes: só a varredura acha os blocos
 * parciais de uma gravação que nunca terminou, sem precisar saber quantos
 * eram. O prefixo termina em "/" de propósito -- sem isso, o deck 10
 * apagaria os blocos do deck 100.
 */
async function _apagarDoCache(uid, deckId, { manterCompleto = false } = {}) {
  const cache = await _abrirCache();
  if (!cache) return;
  const prefixo = _chaveCache(uid, deckId, "");
  const completo = _chaveCache(uid, deckId);
  try {
    for (const pedido of await cache.keys()) {
      const caminho = new URL(pedido.url).pathname;
      if (!caminho.startsWith(prefixo)) continue;
      if (manterCompleto && caminho === completo) continue;
      await cache.delete(pedido);
    }
  } catch {
    /* sem Cache API: nada a apagar */
  }
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

/** Áudios guardados neste aparelho pelo usuário logado. */
export function listarAudios() {
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

export function audioGuardado(deckId) {
  const uid = token.usuarioId();
  return uid ? _lerRegistro()[_chaveRegistro(uid, deckId)] || null : null;
}

/**
 * Gera o áudio do deck inteiro, bloco a bloco -- e retoma de onde parou.
 *
 * `aoAvancar({ feitos, total })` é chamado a cada bloco pronto, pra tela
 * poder mostrar a barra. `sinal` é um AbortSignal: sair da tela
 * interrompe a fila no fim do bloco atual, nunca no meio -- abortar uma
 * síntese já paga não devolve a cota. O que ela devolve é o bloco: ele já
 * está guardado quando a interrupção chega, e a próxima tentativa pula
 * direto pra onde esta parou, sem pagar de novo.
 *
 * Lança com ERRO_SEM_ESPACO quando o áudio nasceu mas o aparelho não quis
 * guardar -- a única falha deste caminho que acontece DEPOIS de a cota já
 * ter sido gasta, e por isso a única que precisa dizer o que fazer.
 */
export async function gerarAudio(deckId, { aoAvancar, sinal } = {}) {
  const uid = token.usuarioId();
  if (!uid) throw new Error("Sem usuário logado.");

  const roteiro = await api.criarRoteiroDeAudio(deckId);
  const total = roteiro.total_blocos;
  // Identifica o roteiro: blocos guardados por uma versão anterior não
  // servem pra esta (ver _guardarBloco).
  const versao = String(roteiro.criado_em || "");
  const cache = await _abrirCache();

  const partes = [];
  let amostras = 0;
  let taxa = TAXA_PADRAO;

  for (let i = 0; i < total; i++) {
    if (sinal?.aborted) throw new DOMException("Geração interrompida", "AbortError");

    const guardado = await _lerBloco(cache, uid, deckId, i, versao);
    if (guardado) {
      // Já sintetizado e pago numa tentativa anterior. Não fala com o
      // servidor: é exatamente o que esta função existe pra não repetir.
      partes.push(guardado.blob);
      amostras += guardado.amostras;
      taxa = guardado.taxa;
      aoAvancar?.({ feitos: i + 1, total });
      continue;
    }

    // Já vem em MP3. Se o servidor tinha o bloco guardado, veio de lá e
    // não gastou cota; senão, nasceu agora (e ficou guardado lá também).
    const { bytes, cabecalhos } = await api.gravarBlocoDeAudio(deckId, i);
    taxa = Number(cabecalhos.get("X-Taxa-Amostragem")) || taxa;
    // O MP3 não diz a duração sem decodificar; o servidor manda junto.
    const amostrasDoBloco = Number(cabecalhos.get("X-Amostras")) || 0;

    const bloco = new Blob([bytes], { type: "audio/mpeg" });
    amostras += amostrasDoBloco;
    partes.push(bloco);
    // Guarda ANTES de pedir o próximo: é a linha que faz a fila poder
    // recomeçar sem nem perguntar ao servidor.
    await _guardarBloco(cache, uid, deckId, i, bloco, amostrasDoBloco, taxa, versao);

    aoAvancar?.({ feitos: i + 1, total });
  }

  const blob = new Blob(partes, { type: "audio/mpeg" });
  const registro = {
    duracao_s: Math.round(amostras / taxa),
    bytes: blob.size,
    gravadoEm: new Date().toISOString(),
    capitulos: roteiro.capitulos,
    totalBlocos: total,
  };

  // Daqui pra frente o áudio existe e já foi pago. Estas duas escritas
  // eram as únicas do arquivo sem rede de proteção: um aparelho cheio
  // devolvia um QuotaExceededError cru depois de a pessoa esperar a
  // geração inteira.
  try {
    if (!cache) throw new Error("sem Cache API");
    await cache.put(_chaveCache(uid, deckId), new Response(blob, {
      headers: { "Content-Type": "audio/mpeg" },
    }));
  } catch {
    throw new Error(ERRO_SEM_ESPACO);
  }

  const reg = _lerRegistro();
  reg[_chaveRegistro(uid, deckId)] = registro;
  if (!_gravarRegistro(reg)) {
    // O MP3 está no cache, mas é o REGISTRO que a tela lê pra saber que
    // ele existe. Sem registro, são megabytes presos num cache que a
    // interface não enxerga e nenhum botão alcança -- pior que não ter
    // gravado. Limpa e conta o que houve.
    await _apagarDoCache(uid, deckId);
    throw new Error(ERRO_SEM_ESPACO);
  }

  // Episódio inteiro guardado: os blocos soltos viraram cópia duplicada do
  // mesmo áudio e sairiam dobrando o espaço ocupado.
  await _apagarDoCache(uid, deckId, { manterCompleto: true });

  return registro;
}

/**
 * URL tocável do áudio guardado, ou null se não há cópia neste aparelho.
 *
 * Quem chama precisa chamar URL.revokeObjectURL quando trocar de tela --
 * sem isso o blob fica preso na memória da aba pelo resto da sessão.
 */
export async function urlDoAudio(deckId) {
  const uid = token.usuarioId();
  if (!uid) return null;
  try {
    const cache = await _abrirCache();
    const resp = cache && await cache.match(_chaveCache(uid, deckId));
    if (!resp) return null;
    return URL.createObjectURL(await resp.blob());
  } catch {
    return null;
  }
}

/**
 * Apaga a cópia deste aparelho. O roteiro no servidor não é tocado.
 *
 * Inclui os blocos parciais de uma gravação interrompida: é o que
 * "Gravar de novo" usa pra garantir que o roteiro reescrito não herde
 * nada do anterior.
 */
export async function removerAudio(deckId) {
  const uid = token.usuarioId();
  if (!uid) return;
  await _apagarDoCache(uid, deckId);
  const reg = _lerRegistro();
  delete reg[_chaveRegistro(uid, deckId)];
  _gravarRegistro(reg);
}
