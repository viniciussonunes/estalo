import { useState } from "react";
import { api } from "../api.js";

export default function CriarDeck({ pastaId, aoVoltar, aoVerCards }) {
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");
  const [modo, setModo] = useState("manual"); // "manual" | "ia"

  // Modo manual: linhas dinâmicas
  const [linhas, setLinhas] = useState([{ frente: "", verso: "" }]);

  // Modo IA
  const [textoIA, setTextoIA] = useState("");
  const [qtdIA, setQtdIA] = useState(5);

  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");

  function addLinha() {
    setLinhas(l => [...l, { frente: "", verso: "" }]);
  }

  function removeLinha(i) {
    if (linhas.length === 1) return;
    setLinhas(l => l.filter((_, idx) => idx !== i));
  }

  function updateLinha(i, campo, valor) {
    setLinhas(l => l.map((linha, idx) => idx === i ? { ...linha, [campo]: valor } : linha));
  }

  async function criar(e) {
    e.preventDefault();
    if (!nome.trim()) return;
    setSalvando(true);
    setErro("");
    try {
      const deck = await api.criarDeck(nome.trim(), descricao.trim() || null, pastaId);

      if (modo === "manual") {
        const validos = linhas.filter(l => l.frente.trim() && l.verso.trim());
        for (const l of validos) {
          await api.criarCard(deck.id, l.frente.trim(), l.verso.trim());
        }
      } else if (textoIA.trim()) {
        await api.gerarCardsIA(deck.id, textoIA.trim(), qtdIA);
      }

      aoVerCards(deck);
    } catch (err) {
      setErro(err.message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="pagina">
      <header className="topo">
        <div className="topo-esquerda">
          <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
          <span className="estudo-deck-nome">Novo deck</span>
        </div>
      </header>

      <main className="conteudo">
        <h1 className="titulo-pagina">Criar deck</h1>

        <form onSubmit={criar}>
          {/* Info do deck */}
          <div className="criar-deck-info">
            <label className="campo">
              <span>Nome do deck *</span>
              <input
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Ex: SC-900 Fundamentos"
                required
                autoFocus
              />
            </label>
            <label className="campo">
              <span>Descrição (opcional)</span>
              <input
                value={descricao}
                onChange={(e) => setDescricao(e.target.value)}
                placeholder="Ex: Conceitos de segurança e identidade Microsoft"
              />
            </label>
          </div>

          {/* Cards */}
          <div className="cards-criar">
            <div className="abas">
              <button
                type="button"
                className={modo === "manual" ? "aba ativa" : "aba"}
                onClick={() => setModo("manual")}
              >
                Adicionar manualmente
              </button>
              <button
                type="button"
                className={modo === "ia" ? "aba ativa" : "aba"}
                onClick={() => setModo("ia")}
              >
                Gerar com IA
              </button>
            </div>

            {erro && <p className="erro">{erro}</p>}

            {modo === "manual" ? (
              <div className="linhas-cards">
                {linhas.map((linha, i) => (
                  <div key={i} className="linha-card">
                    <span className="linha-card-num">{i + 1}</span>
                    <div className="linha-card-campos">
                      <textarea
                        value={linha.frente}
                        onChange={(e) => updateLinha(i, "frente", e.target.value)}
                        placeholder="Frente (pergunta)"
                        rows={2}
                      />
                      <textarea
                        value={linha.verso}
                        onChange={(e) => updateLinha(i, "verso", e.target.value)}
                        placeholder="Verso (resposta)"
                        rows={2}
                      />
                    </div>
                    {linhas.length > 1 && (
                      <button
                        type="button"
                        className="linha-card-remover"
                        onClick={() => removeLinha(i)}
                        title="Remover"
                      >
                        ×
                      </button>
                    )}
                  </div>
                ))}
                <button type="button" className="botao-add-linha" onClick={addLinha}>
                  + Adicionar card
                </button>
              </div>
            ) : (
              <div className="form-card">
                <label className="campo">
                  <span>Material de estudo</span>
                  <textarea
                    value={textoIA}
                    onChange={(e) => setTextoIA(e.target.value)}
                    placeholder="Cole aqui suas anotações, um trecho do livro, a descrição de um conceito…"
                    rows={8}
                  />
                </label>
                <div className="form-card-rodape">
                  <label className="campo campo-inline">
                    <span>Quantidade de cards</span>
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={qtdIA}
                      onChange={(e) => setQtdIA(Number(e.target.value))}
                    />
                  </label>
                </div>
              </div>
            )}
          </div>

          <button
            className="botao-principal criar-deck-submit"
            type="submit"
            disabled={salvando || !nome.trim()}
          >
            {salvando
              ? (modo === "ia" ? "Gerando cards com IA…" : "Criando…")
              : "Criar deck"}
          </button>
        </form>
      </main>
    </div>
  );
}
