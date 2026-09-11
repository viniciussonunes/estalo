// outbox.js — a "caixa de saída" das respostas de estudo.
//
// Nível 2 do roadmap de resiliência offline. A ideia: uma resposta é
// gravada PRIMEIRO aqui, no próprio aparelho, e só depois enviada. Se não
// houver conexão, ela fica guardada e sobe sozinha quando a internet
// voltar (ou no próximo boot do app). Enquanto isso o usuário pode fechar
// o app à vontade: o que está aqui sobrevive, porque mora no localStorage.
//
// Por que localStorage e não IndexedDB: cada entrada é um punhado de
// campos (uns 150 bytes); mesmo centenas de respostas não chegam perto do
// limite. E o projeto inteiro já guarda estado assim (token, tema,
// snapshot de sessão) -- não vale introduzir um segundo mecanismo.
//
// O que torna isso seguro de re-tentar:
//   - cada entrada carrega um `id` que vai como X-Request-ID; o backend
//     devolve o resultado original em vez de reprocessar (idempotência);
//   - cada entrada carrega `respondidoEm`, e o backend ancora histórico e
//     SM-2 nessa data -- 3 dias de estudo offline não colapsam em "hoje".
import { api, token, NetworkException } from "./api.js";

const CHAVE = "estalo_outbox_respostas";

// Teto de segurança: se algo der muito errado (fila nunca esvazia), não
// deixa o localStorage crescer sem limite. Descarta as MAIS ANTIGAS -- as
// recentes são as que ainda têm chance de importar pro usuário.
const MAX_ENTRADAS = 500;

let sincronizando = false;

// Plano B pra quando o localStorage não aceita gravar (janela anônima,
// armazenamento cheio): a resposta fica pelo menos em memória, e ainda tem
// chance de subir enquanto a aba estiver aberta. Sem isso ela sumiria na
// hora, em silêncio -- que é justamente o pior desfecho possível aqui.
let filaMemoria = [];

function _ler() {
  try {
    const raw = localStorage.getItem(CHAVE);
    if (!raw) return [];
    const lista = JSON.parse(raw);
    return Array.isArray(lista) ? lista : [];
  } catch {
    return []; // localStorage indisponível ou conteúdo corrompido
  }
}

/** Grava a fila persistente. Devolve false se o navegador não deixou. */
function _gravar(lista) {
  try {
    localStorage.setItem(CHAVE, JSON.stringify(lista.slice(-MAX_ENTRADAS)));
    return true;
  } catch {
    return false;
  }
}

/** Tudo que está aguardando envio: o que está no disco + o plano B em memória. */
function _tudo() {
  return [..._ler(), ...filaMemoria];
}

/** Quantas respostas do usuário logado estão aguardando envio. */
export function contar() {
  const uid = token.usuarioId();
  return _tudo().filter(e => e.userId === uid).length;
}

/**
 * Guarda uma resposta pra ser enviada. `respondidoEm` é carimbado AQUI (o
 * momento real em que a pessoa respondeu), não na hora do envio.
 *
 * Devolve `true` se conseguiu gravar em disco (sobrevive a fechar o app) e
 * `false` se caiu no plano B em memória (sobrevive só enquanto a aba viver).
 */
export function enfileirar({ cardId, quality, ignorarElegibilidade = false }) {
  const entrada = {
    id: crypto.randomUUID(),          // vira o X-Request-ID
    userId: token.usuarioId(),
    cardId,
    quality,
    ignorarElegibilidade,
    respondidoEm: new Date().toISOString(),
  };
  if (_gravar([..._ler(), entrada])) return true;
  filaMemoria.push(entrada);
  return false;
}

/**
 * Tenta esvaziar a fila do usuário atual.
 *
 * Para no PRIMEIRO erro de rede (não adianta insistir nas outras se a
 * conexão caiu) e deixa o resto guardado pra próxima tentativa. Erro de
 * negócio (4xx -- card apagado, resposta já não faz sentido) descarta a
 * entrada: ela nunca vai passar, e mantê-la travaria a fila pra sempre.
 *
 * Devolve { enviadas, descartadas, restantes }.
 */
export async function sincronizar() {
  if (sincronizando) return { enviadas: 0, descartadas: 0, restantes: contar() };
  const uid = token.usuarioId();
  if (!uid) return { enviadas: 0, descartadas: 0, restantes: 0 }; // deslogado

  sincronizando = true;
  let enviadas = 0;
  let descartadas = 0;
  try {
    // Ordem cronológica: respostas do mesmo card precisam ser aplicadas na
    // sequência em que aconteceram pro SM-2 fazer sentido.
    const minhas = _tudo().filter(e => e.userId === uid);
    const concluidas = new Set();

    for (const entrada of minhas) {
      try {
        await api.responderCard(
          entrada.cardId,
          entrada.quality,
          entrada.ignorarElegibilidade,
          entrada.id,
          entrada.respondidoEm,
        );
        concluidas.add(entrada.id);
        enviadas++;
      } catch (e) {
        if (e instanceof NetworkException) break; // conexão caiu: para e guarda o resto
        console.error("[outbox] descartando resposta que o servidor recusou:", e.message);
        concluidas.add(entrada.id);
        descartadas++;
      }
    }

    if (concluidas.size > 0) {
      // Relê antes de gravar: uma resposta nova pode ter sido enfileirada
      // enquanto o await acima estava em voo.
      _gravar(_ler().filter(e => !concluidas.has(e.id)));
      filaMemoria = filaMemoria.filter(e => !concluidas.has(e.id));
    }
  } finally {
    sincronizando = false;
  }

  return { enviadas, descartadas, restantes: contar() };
}
