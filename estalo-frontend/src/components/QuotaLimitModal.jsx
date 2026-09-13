import Modal from "./Modal.jsx";

// Modal exibido quando o backend recusa uma chamada de IA por limite diário
// de tokens estourado (HTTP 429 -> QuotaExceededException, ver api.js).
export default function QuotaLimitModal({ aberto, aoFechar }) {
  return (
    <Modal aberto={aberto} aoFechar={aoFechar} titulo="Limite diário atingido" className="modal-cota">
      <p className="modal-cota-texto">
        Você atingiu seu limite diário de tokens. Volte amanhã para continuar
        usando o Tutor Inteligente, ou conheça o plano Premium para ter mais cota.
      </p>
      <div className="modal-cota-botoes">
        <button className="botao-principal" onClick={aoFechar}>Entendido</button>
        <button className="botao-texto" type="button">Conhecer o Plano Premium</button>
      </div>
    </Modal>
  );
}
