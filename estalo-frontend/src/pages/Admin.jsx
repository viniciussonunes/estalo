import { useState, useEffect } from "react";
import { api } from "../api.js";

export default function Admin({ aoVoltar }) {
  const [usuarios, setUsuarios]     = useState([]);
  const [carregando, setCarregando] = useState(true);
  // Erro de CARREGAR (ex: 403 de quem não é admin) -- impede a tabela de
  // aparecer, já que não há dado nenhum pra mostrar. Separado do erro de
  // SALVAR de propósito: uma falha ao salvar uma linha não deve esconder
  // a tabela inteira que já estava carregada e visível.
  const [erroCarregar, setErroCarregar] = useState("");
  const [erroSalvar, setErroSalvar]     = useState("");
  // Map<user_id, string> -- valor do input de cada linha, separado do
  // dado já salvo (usuarios) até o usuário clicar "Salvar".
  const [edicoes, setEdicoes]       = useState({});
  const [salvandoId, setSalvandoId] = useState(null);

  function _carregar() {
    setCarregando(true);
    setErroCarregar("");
    api.adminListarUsuarios()
      .then(lista => {
        setUsuarios(lista);
        const iniciais = {};
        lista.forEach(u => { iniciais[u.user_id] = String(u.daily_limit); });
        setEdicoes(iniciais);
      })
      .catch(e => setErroCarregar(e.message || "Não foi possível carregar os usuários."))
      .finally(() => setCarregando(false));
  }

  useEffect(_carregar, []);

  async function salvarLimite(userId) {
    const valor = parseInt(edicoes[userId], 10);
    if (Number.isNaN(valor) || valor < 0) {
      setErroSalvar("O limite precisa ser um número inteiro maior ou igual a 0.");
      return;
    }
    setSalvandoId(userId);
    setErroSalvar("");
    try {
      const atualizado = await api.adminAtualizarLimite(userId, valor);
      setUsuarios(lista => lista.map(u => (u.user_id === userId ? atualizado : u)));
    } catch (e) {
      setErroSalvar(e.message || "Não foi possível salvar o novo limite.");
    } finally {
      setSalvandoId(null);
    }
  }

  return (
    <div className="pagina">
      <header className="topo">
        <div className="topo-esquerda">
          <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
          <span className="estudo-deck-nome">Administração — Cotas de IA</span>
        </div>
      </header>

      <main className="conteudo admin-conteudo">
        {erroCarregar && <p className="erro">{erroCarregar}</p>}
        {erroSalvar && <p className="erro">{erroSalvar}</p>}

        {carregando ? (
          <p className="vazio">Carregando usuários…</p>
        ) : !erroCarregar && (
          <div className="admin-tabela-wrap">
            <table className="admin-tabela">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Consumido hoje</th>
                  <th>Limite diário</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {usuarios.map(u => {
                  const alterado = edicoes[u.user_id] !== String(u.daily_limit);
                  return (
                    <tr key={u.user_id}>
                      <td>{u.email}</td>
                      <td className="admin-tabela-numero">{u.daily_tokens_consumed.toLocaleString("pt-BR")}</td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          className="admin-input-limite"
                          value={edicoes[u.user_id] ?? ""}
                          onChange={e => setEdicoes(m => ({ ...m, [u.user_id]: e.target.value }))}
                        />
                      </td>
                      <td>
                        <button
                          className="botao-texto"
                          disabled={!alterado || salvandoId === u.user_id}
                          onClick={() => salvarLimite(u.user_id)}
                        >
                          {salvandoId === u.user_id ? "Salvando…" : "Salvar"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
