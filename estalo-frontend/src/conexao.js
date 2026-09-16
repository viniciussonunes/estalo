/**
 * Estado de conexão do app — baseado no que ACONTECE, não no que o
 * navegador acha.
 *
 * Por que existe (reproduzido em 2026-09-13, com o usuário relatando
 * "aparece mensagem de sem internet toda hora"):
 *
 * `navigator.onLine` só diz se existe *alguma* rede ligada. Wi-Fi
 * conectado sem internet, portal cativo de hotel, sinal fantasma de
 * celular -- em todos, `onLine` é `true` e nenhuma request completa. O app
 * ficava no pior dos dois mundos:
 *
 *   - a faixa calma ("Sem conexão · Modo offline") NÃO aparecia, porque
 *     ela olhava `navigator.onLine`;
 *   - e um toast VERMELHO de erro aparecia a cada tela, porque cada
 *     navegação refaz as chamadas e cada falha disparava o aviso.
 *
 * Medido: abrir o início, entrar numa pasta e voltar = 3 toasts, zero
 * faixa. E o app tinha funcionado inteiro, desenhado do retrato local --
 * o usuário levava erro na cara por algo que não falhou pra ele.
 *
 * Agora a verdade vem das requests: falhou por rede, está fora; respondeu,
 * está dentro. Os eventos do navegador continuam entrando como palpite
 * (são bons pra detectar a QUEDA na hora), mas quem tem a última palavra é
 * a request.
 */
// Três estados, não dois. O app só sabia "respondeu" ou "caiu", e o mundo
// real fica quase sempre no meio: rede que não cai, só demora. Medido com
// 25s por chamada num deck já baixado: 25s de "Carregando…" com a cópia
// local ali parada, e nenhuma faixa -- pra quem estuda, isso É offline.
//
//   "ok"    -> respondeu dentro do limite
//   "lenta" -> uma leitura passou do prazo (e foi servida da cópia local)
//              ou respondeu além do limite
//   "fora"  -> a request falhou por rede
//
// Só LEITURAS julgam lentidão (ver registrarResposta): uma geração de IA
// leva 20s numa rede ótima, e isso não é sinal de nada.
export const LIMITE_LENTA_MS = 3000;

let estado = typeof navigator !== "undefined" && navigator.onLine === false ? "fora" : "ok";
const ouvintes = new Set();

function avisar() {
  for (const ouvinte of ouvintes) ouvinte(estado);
}

function mudar(novo) {
  if (estado === novo) return;
  estado = novo;
  avisar();
}

/** "ok" | "lenta" | "fora" -- pra quem precisa distinguir (a faixa). */
export function estadoConexao() {
  return estado;
}

/** true quando dá pra contar com o servidor AGORA. Rede lenta conta como
 *  não: os botões que dependem de rede ficam apagados igual ao offline,
 *  em vez de a pessoa clicar e esperar 25s. */
export function estaOnline() {
  return estado === "ok";
}

export function assinar(ouvinte) {
  ouvintes.add(ouvinte);
  return () => ouvintes.delete(ouvinte);
}

/** Uma request falhou por rede. Chamado pelo api.js. */
export function marcarQueda() {
  mudar("fora");
}

/** Uma leitura estourou o prazo. Chamado pelo api.js. */
export function marcarLenta() {
  mudar("lenta");
}

/** Uma request respondeu. Chamado pelo api.js. */
export function marcarOk() {
  mudar("ok");
}

/**
 * Uma request respondeu, e demorou `duracaoMs`. Só as leituras julgam
 * lentidão (`julgar`); as outras servem apenas de prova de que o servidor
 * está lá -- se estava "fora", passa a "lenta" até uma leitura rápida
 * confirmar que voltou de verdade.
 */
export function registrarResposta(duracaoMs, julgar) {
  if (julgar) {
    mudar(duracaoMs > LIMITE_LENTA_MS ? "lenta" : "ok");
  } else if (estado === "fora") {
    mudar("lenta");
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("offline", marcarQueda);
  window.addEventListener("online", marcarOk);
}
