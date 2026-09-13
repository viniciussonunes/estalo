import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

/**
 * Modal único do app. Nasceu pra corrigir três problemas que os cinco
 * modais espalhados tinham, cada um do seu jeito:
 *
 * 1. **Esc não fechava.** Só a tela de Cards tinha Escape -- e mesmo lá o
 *    atalho se desligava quando o foco estava num input, que é justamente
 *    onde o foco fica quando o modal está aberto. Na prática, nenhum
 *    fechava pelo teclado.
 * 2. **O foco vazava.** Com Tab, você saía do modal e ia navegar a página
 *    atrás dele -- clicando em botões que não deveriam estar alcançáveis,
 *    sem nenhuma pista visual de onde estava. Para quem usa leitor de tela
 *    ou não usa mouse, o modal simplesmente não prendia.
 * 3. **`position: fixed` não era fixo.** `.pagina` tinha `animation:
 *    fadeIn ... both`, e o `both` deixava colado pra sempre o estado final
 *    da animação -- que inclui um `transform`. Transform diferente de
 *    `none` cria bloco de contenção, então todo descendente `fixed` se
 *    ancorava na `.pagina`, não na janela: com a página rolada, abrir o
 *    modal dava um tranco de milhares de pixels. A causa foi corrigida no
 *    CSS (`both` -> `backwards`, ver `.pagina` em styles.css); o modal
 *    continua sendo renderizado em `document.body` porque é o certo pra
 *    uma camada que cobre a tela inteira -- e porque não deve depender de
 *    nenhuma tela manter a `.pagina` limpa de transform.
 *
 * Uso: <Modal aberto={x} aoFechar={fn} titulo="..."> conteúdo </Modal>
 */

const FOCAVEIS = [
  "a[href]", "button:not([disabled])", "input:not([disabled])",
  "select:not([disabled])", "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

// Pilha de modais abertos: só o de cima responde ao Esc. Hoje o app não
// empilha, mas o custo de acertar isso agora é uma linha.
const pilha = [];

export default function Modal({ aberto, aoFechar, titulo, className = "", children }) {
  const painelRef = useRef(null);
  const focoAnterior = useRef(null);
  const idTitulo = useId();

  // aoFechar quase sempre chega como arrow function nova a cada render. Se
  // ela entrasse nas dependências, o efeito remontaria a cada tecla
  // digitada -- e o `painelRef.focus()` da montagem roubaria o foco do
  // campo que a pessoa está preenchendo. Guardar num ref mantém o efeito
  // preso só ao abrir/fechar.
  const fechar = useRef(aoFechar);
  fechar.current = aoFechar;

  useEffect(() => {
    if (!aberto) return;

    const marca = {};
    pilha.push(marca);
    focoAnterior.current = document.activeElement;
    painelRef.current?.focus();

    function aoTeclar(e) {
      if (pilha[pilha.length - 1] !== marca) return;

      if (e.key === "Escape") {
        e.stopPropagation();
        fechar.current();
        return;
      }
      if (e.key !== "Tab") return;

      // Trap: Tab no último volta pro primeiro, Shift+Tab no primeiro vai
      // pro último. Consulta o DOM a cada tecla porque o conteúdo do modal
      // muda enquanto ele está aberto (abas, respostas da IA chegando).
      const alvos = [...(painelRef.current?.querySelectorAll(FOCAVEIS) ?? [])]
        .filter(el => el.offsetParent !== null);
      if (alvos.length === 0) { e.preventDefault(); painelRef.current?.focus(); return; }

      const primeiro = alvos[0];
      const ultimo = alvos[alvos.length - 1];
      const atual = document.activeElement;

      if (!painelRef.current?.contains(atual)) { e.preventDefault(); primeiro.focus(); return; }
      if (!e.shiftKey && atual === ultimo) { e.preventDefault(); primeiro.focus(); }
      else if (e.shiftKey && atual === primeiro) { e.preventDefault(); ultimo.focus(); }
    }

    // Captura: chega antes de qualquer handler de tecla das telas (o atalho
    // 'C' de Cards, as teclas 1-4 do Aprender), que não devem disparar com
    // um modal na frente.
    document.addEventListener("keydown", aoTeclar, true);

    // Sem trava de rolagem do fundo, de propósito: `overflow: hidden` no
    // body, aqui, joga a página pro topo (medido: de 4037 pra 0) e o
    // usuário perde o lugar ao fechar. Travar direito exige `position:
    // fixed` no body com compensação do scroll -- risco maior que o
    // incômodo de o fundo rolar atrás de um modal que cobre a tela.
    return () => {
      document.removeEventListener("keydown", aoTeclar, true);
      pilha.splice(pilha.indexOf(marca), 1);
      // Devolve o foco pro botão que abriu -- sem isso, fechar o modal
      // joga o foco no <body> e o Tab seguinte recomeça do topo da página.
      focoAnterior.current?.focus?.();
    };
  }, [aberto]);

  if (!aberto) return null;

  return createPortal(
    <div className="modal-overlay" onMouseDown={e => { if (e.target === e.currentTarget) aoFechar(); }}>
      <div
        ref={painelRef}
        className={`modal-painel ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={idTitulo}
        tabIndex={-1}
      >
        <div className="modal-cabecalho">
          <h2 className="modal-titulo" id={idTitulo}>{titulo}</h2>
          <button className="modal-fechar" onClick={aoFechar} aria-label="Fechar">×</button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  );
}
