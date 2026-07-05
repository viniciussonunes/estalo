// Modal exibido quando o backend recusa uma chamada de IA por limite diário
// de tokens estourado (HTTP 429 -> QuotaExceededException, ver api.js).
export default function QuotaLimitModal({ aberto, aoFechar }) {
  if (!aberto) return null;

  return (
    <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) aoFechar(); }}>
      <div className="modal-painel modal-cota">
        <div className="modal-cabecalho">
          <h2 className="modal-titulo">Limite diário atingido</h2>
          <button className="modal-fechar" onClick={aoFechar} aria-label="Fechar">×</button>
        </div>
        <p className="modal-cota-texto">
          Você atingiu seu limite diário de tokens. Volte amanhã para continuar
          usando o Tutor Inteligente, ou conheça o plano Premium para ter mais cota.
        </p>
        <div className="modal-cota-botoes">
          <button className="botao-principal" onClick={aoFechar}>Entendido</button>
          <button className="botao-texto" type="button">Conhecer o Plano Premium</button>
        </div>
      </div>
    </div>
  );
}
