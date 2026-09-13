import { useSyncExternalStore } from "react";
import { assinar, estaOnline } from "../conexao.js";

/**
 * true enquanto dá pra falar com o servidor.
 *
 * Antes olhava só `navigator.onLine`, que mente com frequência: Wi-Fi sem
 * internet, portal cativo e sinal fantasma reportam `true` com a rede
 * inútil. O estado agora vem do que as requests de verdade fazem -- ver
 * src/conexao.js, que explica o sintoma que motivou a troca.
 *
 * Isso muda pra melhor os ~14 botões que dependem deste hook (Tutor,
 * "Gerar com IA", renomear, excluir…): eles passam a ficar indisponíveis
 * também quando existe rede mas o servidor não responde -- que é
 * exatamente quando clicar neles daria erro.
 */
export default function useOnline() {
  return useSyncExternalStore(assinar, estaOnline, () => true);
}
