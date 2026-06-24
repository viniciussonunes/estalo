import { useState, useEffect } from "react";
import { api } from "../api.js";

// Painel principal: lista seus decks e deixa criar/excluir.
// (As pastas e a tela de estudo entram nos próximos blocos.)
export default function Dashboard({ usuario, aoSair }) {
  const [decks, setDecks] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [novoTitulo, setNovoTitulo] = useState("");

  async function carregarDecks() {
    try {
      setDecks(await api.listarDecks());
    } catch (err) {
      setErro(err.message);
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    carregarDecks();
  }, []);

  async function criar(e) {
    e.preventDefault();
    if (!novoTitulo.trim()) return;
    try {
      await api.criarDeck(novoTitulo.trim(), null);
      setNovoTitulo("");
      carregarDecks();
    } catch (err) {
      setErro(err.message);
    }
  }

  async function excluir(id) {
    if (!confirm("Excluir este deck e todos os cards dentro dele?")) return;
    try {
      await api.excluirDeck(id);
      carregarDecks();
    } catch (err) {
      setErro(err.message);
    }
  }

  return (
    <div className="pagina">
      <header className="topo">
        <span className="marca-nome pequeno">Estalo</span>
        <div className="topo-direita">
          <span className="usuario-email">{usuario.email}</span>
          <button className="botao-texto" onClick={aoSair}>Sair</button>
        </div>
      </header>

      <main className="conteudo">
        <h1 className="titulo-pagina">Seus decks</h1>

        <form className="criar-deck" onSubmit={criar}>
          <input
            value={novoTitulo}
            onChange={(e) => setNovoTitulo(e.target.value)}
            placeholder="Nome do novo deck (ex: SC-900 Fundamentos)"
          />
          <button className="botao-principal" type="submit">Criar deck</button>
        </form>

        {erro && <p className="erro">{erro}</p>}

        {carregando ? (
          <p className="vazio">Carregando…</p>
        ) : decks.length === 0 ? (
          <div className="vazio-bloco">
            <p>Nenhum deck ainda.</p>
            <p className="vazio-dica">Crie o primeiro acima para começar a estudar.</p>
          </div>
        ) : (
          <ul className="lista-decks">
            {decks.map((d) => (
              <li key={d.id} className="card-deck">
                <div>
                  <span className="card-deck-titulo">{d.title}</span>
                  {d.description && (
                    <span className="card-deck-desc">{d.description}</span>
                  )}
                </div>
                <button className="botao-texto perigo" onClick={() => excluir(d.id)}>
                  Excluir
                </button>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
