import { useState } from "react";
import useOnline from "../hooks/useOnline.js";

/** Seta pra baixo dentro de um traço -- "guardar no aparelho". */
function IcoBaixar() {
  return (
    <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 3v9m0 0l-3.2-3.2M10 12l3.2-3.2M4 16h12" />
    </svg>
  );
}

/** Check -- já está guardado aqui. */
function IcoBaixado() {
  return (
    <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 10.5l4 4 8-9" />
    </svg>
  );
}

/**
 * Botão de baixar/remover conteúdo pra estudo offline.
 *
 * O estado "baixado" é uma CARACTERÍSTICA do deck, não um alarme: o ícone
 * fica visível sempre, com internet ou sem. É o oposto da faixa de rede --
 * ele informa o que você PODE fazer, em vez de anunciar o que está
 * faltando (ver o princípio no OfflineBanner.jsx).
 */
export default function BotaoBaixarOffline({ baixado, aoBaixar, aoRemover, rotulo = "deck" }) {
  const online = useOnline();
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState(false);

  async function clique(e) {
    e.stopPropagation(); // não navegar pra dentro do deck/pasta ao clicar
    if (ocupado) return;
    setOcupado(true);
    setErro(false);
    try {
      if (baixado) await aoRemover();
      else await aoBaixar();
    } catch {
      setErro(true);
    } finally {
      setOcupado(false);
    }
  }

  // Sem conexão não dá pra baixar o que ainda não está aqui -- mas remover
  // continua valendo (é tudo local).
  const bloqueado = !online && !baixado;

  const titulo = erro
    ? "Não foi possível baixar. Tente de novo."
    : bloqueado
      ? "Precisa de internet pra baixar"
      : baixado
        ? `Disponível offline — toque pra remover do aparelho`
        : `Baixar ${rotulo} pra estudar sem internet`;

  return (
    <button
      type="button"
      className={`icone-acao botao-offline${baixado ? " baixado" : ""}${erro ? " erro" : ""}`}
      onClick={clique}
      disabled={bloqueado || ocupado}
      title={titulo}
      aria-label={titulo}
      aria-pressed={baixado}
    >
      {ocupado ? <span className="botao-offline-girando" aria-hidden="true" />
        : baixado ? <IcoBaixado /> : <IcoBaixar />}
    </button>
  );
}
