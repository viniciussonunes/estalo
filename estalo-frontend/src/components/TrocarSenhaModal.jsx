import { useId, useState } from "react";
import { api, NetworkException } from "../api.js";
import { TAMANHO_MINIMO_SENHA, validarSenha } from "../senha.js";
import CampoSenha from "./CampoSenha.jsx";
import Modal from "./Modal.jsx";

/**
 * Trocar a senha da conta.
 *
 * Antes disso não existia jeito nenhum: quem entrou com uma senha ruim
 * (e o cadastro aceitava qualquer uma) estava preso a ela pra sempre.
 *
 * A confirmação da senha nova não é burocracia: **não existe recuperação
 * de senha no Estalo**. Um erro de digitação numa senha mascarada tranca a
 * pessoa fora da própria conta, sem volta. Enquanto o bloco de recuperação
 * não existir, esse campo é a única rede embaixo.
 */
export default function TrocarSenhaModal({ aberto, aoFechar, aoTrocar }) {
  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  const [confirmacao, setConfirmacao] = useState("");
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);
  const idErro = useId();

  function fechar() {
    setAtual(""); setNova(""); setConfirmacao(""); setErro("");
    aoFechar();
  }

  async function enviar(e) {
    e.preventDefault();
    setErro("");

    const problema = validarSenha(nova);
    if (problema) { setErro(problema); return; }
    if (nova !== confirmacao) { setErro("A confirmação não bate com a senha nova."); return; }
    if (nova === atual) { setErro("A senha nova precisa ser diferente da atual."); return; }

    setSalvando(true);
    try {
      await api.trocarSenha(atual, nova);
      aoTrocar?.();
      fechar();
    } catch (err) {
      setErro(
        err instanceof NetworkException
          ? "Não conseguimos falar com o servidor. Verifique sua internet e tente de novo."
          : (err?.message || "Não deu pra trocar a senha. Tente de novo.")
      );
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Modal aberto={aberto} aoFechar={fechar} titulo="Trocar senha" className="modal-senha">
      <form onSubmit={enviar}>
        <CampoSenha
          rotulo="Senha atual"
          valor={atual}
          aoMudar={setAtual}
          autoComplete="current-password"
          invalido={!!erro}
          descritoPor={erro ? idErro : undefined}
          autoFocus
        />
        <CampoSenha
          rotulo="Nova senha"
          valor={nova}
          aoMudar={setNova}
          autoComplete="new-password"
          dica={`Mínimo de ${TAMANHO_MINIMO_SENHA} caracteres.`}
          invalido={!!erro}
        />
        <CampoSenha
          rotulo="Repita a nova senha"
          valor={confirmacao}
          aoMudar={setConfirmacao}
          autoComplete="new-password"
          invalido={!!erro}
        />

        {erro && <p className="erro" id={idErro} role="alert">{erro}</p>}

        {/* Dito na hora de decidir, não depois: sem recuperação de senha,
            esquecer a nova é perder a conta. */}
        <p className="modal-senha-aviso">
          Guarde a senha nova num lugar seguro. O Estalo ainda não tem
          recuperação de senha.
        </p>
        {/* Consequência que a pessoa precisa saber ANTES de confirmar:
            trocar a senha desconecta a conta nos outros aparelhos. É o
            comportamento desejado (é assim que se expulsa quem não devia
            estar lá), mas ninguém gosta de ser surpreendido. */}
        <p className="modal-senha-nota">
          Trocar a senha desconecta a sua conta nos outros aparelhos. Aqui você
          continua conectado.
        </p>

        <button className="botao-principal" type="submit"
          disabled={salvando || !atual || !nova || !confirmacao}>
          {salvando ? "Trocando…" : "Trocar senha"}
        </button>
      </form>
    </Modal>
  );
}
