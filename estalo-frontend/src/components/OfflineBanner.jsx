import { createPortal } from "react-dom";
import useOnline from "../hooks/useOnline.js";

// Faixa fixa que aparece só enquanto está sem conexão.
//
// Curta de propósito: ela só NOMEIA o estado. Explicar o que funciona e o
// que não funciona seria um parágrafo grudado na tela o tempo todo -- e
// essa informação já está onde dói, no próprio botão que fica apagado
// (ver useOnline nas telas de estudo/criação). O selo de "offline" dentro
// da sessão (SeloOffline.jsx) cobre o "estou respondendo sem conexão".
export default function OfflineBanner() {
  const online = useOnline();
  if (online) return null;

  return createPortal(
    <div className="offline-banner" role="status" aria-live="polite">
      <span className="offline-banner-ponto" aria-hidden="true" />
      Sem conexão · Modo offline
    </div>,
    document.body,
  );
}
