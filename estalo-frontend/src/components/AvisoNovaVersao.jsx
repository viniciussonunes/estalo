import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { aoSairNovaVersao, aplicarNovaVersao } from "../atualizacao.js";

/**
 * Faixa que aparece quando existe uma versão nova baixada e esperando.
 *
 * Antes disso, uma correção publicada podia não chegar em quem estava com
 * o app aberto: o service worker em modo `autoUpdate` só troca quando
 * todas as abas fecham, e num app instalado na tela inicial isso leva
 * dias. Quem descobriu foi o próprio usuário, achando que um recurso
 * recém-publicado não tinha subido -- estava lá, só não nele.
 *
 * Segue a regra da casa (a mesma do OfflineBanner): não anuncia o normal.
 * Só existe quando há algo pra fazer, e traz a ação junto -- avisar sem
 * dar o botão empurraria a pessoa pro "recarregue com Ctrl+Shift+R", que
 * é instrução de suporte técnico, não de produto.
 *
 * Não some sozinha e não tem "dispensar": ficar numa versão velha é
 * justamente o problema. Ela é uma faixa fina no rodapé, não um modal --
 * não bloqueia nada, e quem estiver no meio de uma sessão de estudo pode
 * ignorar até terminar.
 */
export default function AvisoNovaVersao() {
  const [temNovaVersao, setTemNovaVersao] = useState(false);
  const [aplicando, setAplicando] = useState(false);

  useEffect(() => aoSairNovaVersao(() => setTemNovaVersao(true)), []);

  if (!temNovaVersao) return null;

  return createPortal(
    <div className="aviso-versao" role="status" aria-live="polite">
      <span>Nova versão disponível</span>
      <button
        className="aviso-versao-botao"
        onClick={() => { setAplicando(true); aplicarNovaVersao(); }}
        disabled={aplicando}
      >
        {aplicando ? "Atualizando…" : "Atualizar"}
      </button>
    </div>,
    document.body,
  );
}
