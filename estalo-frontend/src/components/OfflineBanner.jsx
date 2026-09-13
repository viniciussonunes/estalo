import { createPortal } from "react-dom";
import useOnline from "../hooks/useOnline.js";

// Faixa fixa que aparece só enquanto não dá pra falar com o servidor.
//
// Passou a se basear no que as requests de verdade fazem, não em
// `navigator.onLine` (ver src/conexao.js). É o que faz ela aparecer no
// caso que mais confundia: Wi-Fi conectado sem internet, onde o navegador
// jura que está online, a faixa não aparecia e o usuário levava um toast
// vermelho de erro a cada tela.
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
