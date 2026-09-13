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
let fora = typeof navigator !== "undefined" && navigator.onLine === false;

const ouvintes = new Set();

function avisar() {
  for (const ouvinte of ouvintes) ouvinte(!fora);
}

/** true quando dá pra falar com o servidor, até prova em contrário. */
export function estaOnline() {
  return !fora;
}

export function assinar(ouvinte) {
  ouvintes.add(ouvinte);
  return () => ouvintes.delete(ouvinte);
}

/** Uma request falhou por rede. Chamado pelo api.js. */
export function marcarQueda() {
  if (fora) return;
  fora = true;
  avisar();
}

/** Uma request respondeu. Chamado pelo api.js. */
export function marcarOk() {
  if (!fora) return;
  fora = false;
  avisar();
}

if (typeof window !== "undefined") {
  // O evento `offline` é confiável no sentido que interessa: se o
  // navegador diz que caiu, caiu mesmo. Já o `online` é só um palpite
  // otimista -- vale limpar a faixa na hora, e a próxima falha marca de
  // novo se ainda não der.
  window.addEventListener("offline", marcarQueda);
  window.addEventListener("online", marcarOk);
}
