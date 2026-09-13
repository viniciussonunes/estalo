import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const ToastContext = createContext(null);

let idSeq = 0;

/**
 * Provider único, montado uma vez em main.jsx (envolve toda a árvore).
 * Diferente do toast de "Desfazer" (useUndoableDelete.js/UndoToasts.jsx,
 * que é sobre uma ação específica com prazo pra cancelar), este é o aviso
 * genérico de "algo deu errado" -- some sozinho depois de alguns segundos,
 * sem botão de ação, só um X pra fechar antes da hora.
 */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]); // [{ id, tipo: "erro"|"sucesso", mensagem }]
  // Mensagens iguais já visíveis não empilham de novo -- descoberto testando
  // o cenário real de queda de conexão: uma tela que dispara duas chamadas
  // em paralelo (ex: Cards.jsx, cards+stats) e ambas falham gerava DOIS
  // toasts idênticos lado a lado; numa queda mais longa isso vira parede de
  // avisos repetidos. Ref (não state) porque só precisa refletir a decisão
  // na hora do clique/erro seguinte, não redesenhar nada sozinho.
  const ativos = useRef(new Map()); // "tipo:mensagem" -> id

  const remover = useCallback((id, chave) => {
    if (chave) ativos.current.delete(chave);
    setToasts(ts => ts.filter(t => t.id !== id));
  }, []);

  const mostrar = useCallback((mensagem, tipo = "erro", duracaoMs = 6000) => {
    const chave = `${tipo}:${mensagem}`;
    if (ativos.current.has(chave)) return; // já tem um igual na tela agora
    const id = ++idSeq;
    ativos.current.set(chave, id);
    setToasts(ts => [...ts, { id, tipo, mensagem }]);
    setTimeout(() => remover(id, chave), duracaoMs);
  }, [remover]);


  return (
    <ToastContext.Provider value={mostrar}>
      {children}
      {createPortal(
        <div className="toasts-globais" role="status" aria-live="polite">
          {toasts.map(t => (
            <div key={t.id} className={`toast-global toast-${t.tipo}`}>
              <span className="toast-global-texto">{t.mensagem}</span>
              <button
                className="toast-global-fechar"
                onClick={() => remover(t.id, `${t.tipo}:${t.mensagem}`)}
                aria-label="Fechar aviso"
              >
                ×
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  );
}

/** Retorna `mostrar(mensagem, tipo?, duracaoMs?)` -- tipo default "erro". */
export function useToast() {
  const mostrar = useContext(ToastContext);
  if (!mostrar) throw new Error("useToast precisa estar dentro de <ToastProvider>");
  return mostrar;
}
