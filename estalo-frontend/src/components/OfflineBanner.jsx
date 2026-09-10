import { createPortal } from "react-dom";
import useOnline from "../hooks/useOnline.js";

// Faixa fixa no rodapé enquanto o navegador está offline. Diferente do
// toast (que some sozinho): fica na tela o tempo todo que durar a queda,
// pra o usuário saber que qualquer coisa que ele fizer agora pode não
// salvar -- e some sozinha quando a conexão volta.
//
// Nível 1 do roadmap de offline: só avisa. O Nível 2 (fila de
// sincronização) troca a mensagem pra "será salvo quando a conexão
// voltar" -- aí sim vai ser verdade.
export default function OfflineBanner() {
  const online = useOnline();
  if (online) return null;

  return createPortal(
    <div className="offline-banner" role="status" aria-live="polite">
      <span className="offline-banner-ponto" aria-hidden="true" />
      Sem conexão. O que você fizer agora pode não ser salvo até a internet voltar.
    </div>,
    document.body,
  );
}
