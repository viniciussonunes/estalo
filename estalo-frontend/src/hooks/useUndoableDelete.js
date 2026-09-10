import { useState, useRef, useCallback, useEffect } from "react";

/**
 * Exclusão adiada com desfazer, pra substituir `confirm()` + exclusão
 * imediata nas telas de Dashboard/Cards.
 *
 * Fluxo: quem chama `disparar()` já aplicou a remoção otimista no próprio
 * estado (a UI já reflete "excluído"); este hook só cuida do relógio — se
 * `delayMs` passar sem o usuário apertar "Desfazer" no toast, `commit()`
 * roda (a chamada de verdade à API). Se ele desfizer antes, `onUndo()` roda
 * em vez disso e a API nunca é chamada.
 *
 * Suporta várias exclusões pendentes ao mesmo tempo (pilha de toasts) — cada
 * uma com seu próprio timer, pra apagar dois cards em sequência não force o
 * primeiro a confirmar antes da hora nem perca o desfazer do segundo.
 */
export default function useUndoableDelete(delayMs = 5000) {
  const [pendentes, setPendentes] = useState([]); // [{ id, message }] — só o que o toast precisa pra renderizar
  const registro = useRef(new Map()); // id -> { timer, commit, onUndo } — o resto fica fora do state de propósito

  // Se a tela desmontar (usuário navegou embora) com exclusões ainda no ar,
  // confirma todas na hora em vez de deixar o timer perdido — a intenção do
  // clique já foi manifestada, só a JANELA de desfazer é que acabou.
  useEffect(() => {
    return () => {
      registro.current.forEach(({ timer, commit }) => {
        clearTimeout(timer);
        commit();
      });
      registro.current.clear();
    };
  }, []);

  const disparar = useCallback((message, { commit, onUndo }) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const timer = setTimeout(() => {
      registro.current.delete(id);
      setPendentes(p => p.filter(t => t.id !== id));
      commit();
    }, delayMs);
    registro.current.set(id, { timer, commit, onUndo });
    setPendentes(p => [...p, { id, message }]);
  }, [delayMs]);

  const desfazer = useCallback((id) => {
    const item = registro.current.get(id);
    if (!item) return; // já commitou ou já foi desfeito -- clique tardio, ignora
    clearTimeout(item.timer);
    registro.current.delete(id);
    setPendentes(p => p.filter(t => t.id !== id));
    item.onUndo();
  }, []);

  return { pendentes, disparar, desfazer };
}
