import { useState, useEffect, useCallback } from "react";
import { api } from "../api.js";

export default function Cards({ deck, aoVoltar, aoEstudar, aoAprender, aoRevelar }) {
  const [cards, setCards] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");

  // Formulário manual (adicionar)
  const [frente, setFrente] = useState("");
  const [verso, setVerso] = useState("");
  const [criando, setCriando] = useState(false);

  // Geração por IA
  const [textoIA, setTextoIA] = useState("");
  const [qtdIA, setQtdIA] = useState(5);
  const [gerando, setGerando] = useState(false);
  const [erroIA, setErroIA] = useState("");
  const [abaAtiva, setAbaAtiva] = useState("manual");

  // Edição inline
  const [cardEditando, setCardEditando] = useState(null);
  const [editFrente, setEditFrente] = useState("");
  const [editVerso, setEditVerso] = useState("");
  const [salvandoEdit, setSalvandoEdit] = useState(false);

  const carregarCards = useCallback(async () => {
    setErro("");
    try {
      setCards(await api.listarCards(deck.id));
    } catch (err) {
      setErro(err.message);
    } finally {
      setCarregando(false);
    }
  }, [deck.id]);

  useEffect(() => { carregarCards(); }, [carregarCards]);

  async function criarManual(e) {
    e.preventDefault();
    if (!frente.trim() || !verso.trim()) return;
    setCriando(true);
    setErro("");
    try {
      await api.criarCard(deck.id, frente.trim(), verso.trim());
      setFrente(""); setVerso("");
      await carregarCards();
    } catch (err) {
      setErro(err.message);
    } finally {
      setCriando(false);
    }
  }

  async function gerarIA(e) {
    e.preventDefault();
    if (!textoIA.trim()) return;
    setGerando(true);
    setErroIA("");
    try {
      await api.gerarCardsIA(deck.id, textoIA.trim(), qtdIA);
      setTextoIA(""); setQtdIA(5);
      await carregarCards();
    } catch (err) {
      setErroIA(err.message);
    } finally {
      setGerando(false);
    }
  }

  async function excluir(cardId) {
    if (!confirm("Excluir este card?")) return;
    setErro("");
    try {
      await api.excluirCard(cardId);
      await carregarCards();
    } catch (err) {
      setErro(err.message);
    }
  }

  function iniciarEdicao(card) {
    setCardEditando(card.id);
    setEditFrente(card.front);
    setEditVerso(card.back);
  }

  function cancelarEdicao() {
    setCardEditando(null);
    setEditFrente("");
    setEditVerso("");
  }

  async function salvarEdicao(cardId) {
    if (!editFrente.trim() || !editVerso.trim()) return;
    setSalvandoEdit(true);
    try {
      await api.atualizarCard(cardId, editFrente.trim(), editVerso.trim());
      setCardEditando(null);
      await carregarCards();
    } catch (err) {
      setErro(err.message);
    } finally {
      setSalvandoEdit(false);
    }
  }

  return (
    <div className="pagina">
      <header className="topo">
        <div className="topo-esquerda">
          <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
          <span className="estudo-deck-nome">{deck.title}</span>
        </div>
        <div className="modos-estudo-topo">
          <button className="botao-modo" onClick={aoRevelar}>Revelar</button>
          <button className="botao-modo" onClick={aoAprender}>Aprender</button>
          <button className="botao-estudar" onClick={aoEstudar}>Flashcards</button>
        </div>
      </header>

      <main className="conteudo">
        <div className="cards-cabecalho">
          <h1 className="titulo-pagina">Cards</h1>
          {!carregando && (
            <span className="estudo-contador">
              {cards.length} card{cards.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Formulário de criação */}
        <div className="cards-criar">
          <div className="abas">
            <button
              className={abaAtiva === "manual" ? "aba ativa" : "aba"}
              onClick={() => { setAbaAtiva("manual"); setErroIA(""); }}
            >
              Adicionar manualmente
            </button>
            <button
              className={abaAtiva === "ia" ? "aba ativa" : "aba"}
              onClick={() => { setAbaAtiva("ia"); setErro(""); }}
            >
              Gerar com IA
            </button>
          </div>

          {abaAtiva === "manual" ? (
            <form className="form-card" onSubmit={criarManual}>
              {erro && <p className="erro">{erro}</p>}
              <label className="campo">
                <span>Frente (pergunta)</span>
                <textarea value={frente} onChange={(e) => setFrente(e.target.value)}
                  placeholder="Ex: Qual é a capital da França?" rows={2} />
              </label>
              <label className="campo">
                <span>Verso (resposta)</span>
                <textarea value={verso} onChange={(e) => setVerso(e.target.value)}
                  placeholder="Ex: Paris" rows={2} />
              </label>
              <button className="botao-principal" type="submit"
                disabled={criando || !frente.trim() || !verso.trim()}>
                {criando ? "Adicionando…" : "Adicionar card"}
              </button>
            </form>
          ) : (
            <form className="form-card" onSubmit={gerarIA}>
              {erroIA && <p className="erro">{erroIA}</p>}
              <label className="campo">
                <span>Texto de estudo</span>
                <textarea value={textoIA} onChange={(e) => setTextoIA(e.target.value)}
                  placeholder="Cole aqui suas anotações, um trecho do livro, a descrição de um conceito…"
                  rows={6} />
              </label>
              <div className="form-card-rodape">
                <label className="campo campo-inline">
                  <span>Quantidade de cards</span>
                  <input type="number" min={1} max={30} value={qtdIA}
                    onChange={(e) => setQtdIA(Number(e.target.value))} />
                </label>
                <button className="botao-principal" type="submit"
                  disabled={gerando || !textoIA.trim()}>
                  {gerando ? "Gerando…" : "Gerar cards"}
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Lista de cards */}
        {carregando ? (
          <p className="vazio">Carregando…</p>
        ) : cards.length === 0 ? (
          <div className="vazio-bloco">
            <p>Nenhum card ainda.</p>
            <p className="vazio-dica">Adicione um card acima para começar.</p>
          </div>
        ) : (
          <ul className="lista-cards">
            {cards.map((c) =>
              cardEditando === c.id ? (
                /* Modo edição inline */
                <li key={c.id} className="item-card item-card-editando">
                  <div className="item-card-edit-campos">
                    <label className="campo">
                      <span>Frente</span>
                      <textarea value={editFrente} onChange={(e) => setEditFrente(e.target.value)}
                        rows={2} autoFocus />
                    </label>
                    <label className="campo">
                      <span>Verso</span>
                      <textarea value={editVerso} onChange={(e) => setEditVerso(e.target.value)}
                        rows={2} />
                    </label>
                  </div>
                  <div className="item-card-edit-acoes">
                    <button
                      className="botao-principal"
                      onClick={() => salvarEdicao(c.id)}
                      disabled={salvandoEdit || !editFrente.trim() || !editVerso.trim()}
                    >
                      {salvandoEdit ? "Salvando…" : "Salvar"}
                    </button>
                    <button className="botao-texto" onClick={cancelarEdicao}>
                      Cancelar
                    </button>
                  </div>
                </li>
              ) : (
                /* Modo normal */
                <li key={c.id} className="item-card">
                  <div className="item-card-conteudo">
                    <p className="item-card-frente">{c.front}</p>
                    <p className="item-card-verso">{c.back}</p>
                  </div>
                  <div className="item-card-rodape">
                    {c.source === "ai" && <span className="badge-ia">IA</span>}
                    <button className="botao-texto" onClick={() => iniciarEdicao(c)}>
                      Editar
                    </button>
                    <button className="botao-texto perigo" onClick={() => excluir(c.id)}>
                      Excluir
                    </button>
                  </div>
                </li>
              )
            )}
          </ul>
        )}
      </main>
    </div>
  );
}
