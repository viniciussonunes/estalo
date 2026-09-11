import { useEffect } from "react";
import { contar, sincronizar } from "../outbox.js";
import { useToast } from "./ToastContext.jsx";

// De quanto em quanto tempo re-tenta, ENQUANTO houver fila e a aba estiver
// aberta. Cobre o caso "conexão instável" sem depender do evento `online`
// (que só dispara em mudança de estado da rede, não quando o servidor
// estava fora e voltou).
const INTERVALO_RETENTATIVA_MS = 30_000;

/**
 * Liga a fila offline (outbox.js) ao ciclo de vida do app: dispara a
 * sincronização nos momentos certos. Montado uma única vez, no topo da
 * árvore (ver main.jsx).
 *
 * Gatilhos: ao montar (abrir o app), quando a conexão volta (`online`),
 * quando a aba volta a ficar visível, e num intervalo enquanto sobrar fila.
 *
 * NÃO avisa nada quando dá certo -- de propósito. Sincronizar é mecânica
 * interna: o usuário não pediu, não pode agir sobre isso, e anunciar cada
 * etapa transforma o normal em evento. A regra aqui é "calado quando
 * funciona, fala só quando falha de verdade" -- e falha de verdade, aqui,
 * é resposta DESCARTADA (o servidor recusou em definitivo, ex: o card foi
 * apagado). Essa o usuário precisa saber, porque o progresso dela não
 * contou e nada vai fazer contar depois.
 */
export default function useOutboxSync() {
  const mostrarToast = useToast();

  useEffect(() => {
    async function tentar() {
      const { descartadas } = await sincronizar();
      if (descartadas === 0) return;
      mostrarToast(
        descartadas === 1
          ? "1 resposta de estudo não pôde ser salva e foi descartada."
          : `${descartadas} respostas de estudo não puderam ser salvas e foram descartadas.`,
      );
    }

    tentar(); // ao abrir o app

    const aoVoltarConexao = () => tentar();
    const aoFicarVisivel = () => { if (document.visibilityState === "visible") tentar(); };
    window.addEventListener("online", aoVoltarConexao);
    document.addEventListener("visibilitychange", aoFicarVisivel);
    const timer = setInterval(() => { if (contar() > 0) tentar(); }, INTERVALO_RETENTATIVA_MS);

    return () => {
      window.removeEventListener("online", aoVoltarConexao);
      document.removeEventListener("visibilitychange", aoFicarVisivel);
      clearInterval(timer);
    };
  }, [mostrarToast]);
}
