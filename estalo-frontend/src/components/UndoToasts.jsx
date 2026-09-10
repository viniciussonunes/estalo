import { createPortal } from "react-dom";

// Pilha de toasts "X excluído — Desfazer", ancorada no canto inferior da
// tela. `role="status"`/`aria-live="polite"` avisa leitor de tela sem
// roubar o foco (a exclusão já foi decidida, isso é só a janela de
// arrependimento). Ver useUndoableDelete.js pro relógio por trás.
//
// Renderiza via portal direto em <body>, fora da árvore de `.pagina`.
// Motivo nada óbvio: `.pagina` tem `animation: fadeIn ... both` (ver
// styles.css) animando `transform` -- com fill-mode "both" isso deixa
// `.pagina` permanentemente como containing block de qualquer
// `position: fixed` descendente (regra do CSS, não é bug de navegador),
// então um toast fixed dentro de `.pagina` fica ancorado nela, não na
// viewport real, e pode acabar fora da área visível. O portal evita esse
// problema por completo em vez de depender de nenhuma página nunca mexer
// nessa animação.
export default function UndoToasts({ pendentes, aoDesfazer }) {
  if (pendentes.length === 0) return null;

  return createPortal(
    <div className="undo-toasts" role="status" aria-live="polite">
      {pendentes.map(t => (
        <div key={t.id} className="undo-toast">
          <span className="undo-toast-texto">{t.message}</span>
          <button className="undo-toast-botao" onClick={() => aoDesfazer(t.id)}>
            Desfazer
          </button>
        </div>
      ))}
    </div>,
    document.body
  );
}
