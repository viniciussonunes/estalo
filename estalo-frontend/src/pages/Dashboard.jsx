import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "../api.js";

function encontrarPasta(arvore, id) {
  for (const p of arvore) {
    if (p.id === id) return p;
    const found = encontrarPasta(p.children || [], id);
    if (found) return found;
  }
  return null;
}

export default function Dashboard({ usuario, aoSair, aoVerCards, aoEstudar, aoCriarDeck }) {
  const [arvore, setArvore] = useState([]);
  const [todosDecks, setTodosDecks] = useState([]);
  const [pastaAtiva, setPastaAtiva] = useState(null);
  const [caminho, setCaminho] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [menuAberto, setMenuAberto] = useState(false);
  const [criandoPasta, setCriandoPasta] = useState(false);
  const [nomePasta, setNomePasta] = useState("");
  const [salvandoPasta, setSalvandoPasta] = useState(false);
  const menuRef = useRef(null);
  const inputPastaRef = useRef(null);

  const carregar = useCallback(async (pastaAtivaAtual = null) => {
    setErro("");
    try {
      const [novaArvore, novosDecks] = await Promise.all([
        api.listarPastas(),
        api.listarDecks(),
      ]);
      setArvore(novaArvore);
      setTodosDecks(novosDecks);
      if (pastaAtivaAtual) {
        const atualizada = encontrarPasta(novaArvore, pastaAtivaAtual.id);
        setPastaAtiva(atualizada ?? null);
        if (!atualizada) setCaminho([]);
      }
    } catch (err) {
      setErro(err.message);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  // Fecha o menu ao clicar fora
  useEffect(() => {
    function handler(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuAberto(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Foca o input ao abrir o formulário de pasta
  useEffect(() => {
    if (criandoPasta) inputPastaRef.current?.focus();
  }, [criandoPasta]);

  const pastasVisiveis = pastaAtiva ? (pastaAtiva.children || []) : arvore;
  const decksVisiveis  = todosDecks.filter(d =>
    pastaAtiva ? d.folder_id === pastaAtiva.id : !d.folder_id
  );

  function entrarPasta(pasta) {
    setPastaAtiva(pasta);
    setCaminho(c => [...c, pasta]);
    setCriandoPasta(false);
    setMenuAberto(false);
  }

  function navegarBreadcrumb(idx) {
    if (idx === -1) {
      setPastaAtiva(null);
      setCaminho([]);
    } else {
      const novoCaminho = caminho.slice(0, idx + 1);
      const pasta = novoCaminho[novoCaminho.length - 1];
      setPastaAtiva(encontrarPasta(arvore, pasta.id) ?? pasta);
      setCaminho(novoCaminho);
    }
  }

  async function criarPasta(e) {
    e.preventDefault();
    if (!nomePasta.trim()) return;
    setSalvandoPasta(true);
    try {
      await api.criarPasta(nomePasta.trim(), pastaAtiva?.id ?? null);
      setNomePasta("");
      setCriandoPasta(false);
      await carregar(pastaAtiva);
    } catch (err) {
      setErro(err.message);
    } finally {
      setSalvandoPasta(false);
    }
  }

  async function excluirPasta(pasta, e) {
    e.stopPropagation();
    if (!confirm(`Excluir "${pasta.name}" e tudo dentro dela?`)) return;
    try {
      await api.excluirPasta(pasta.id);
      await carregar(pastaAtiva);
    } catch (err) {
      setErro(err.message);
    }
  }

  async function excluirDeck(deck, e) {
    e.stopPropagation();
    if (!confirm(`Excluir "${deck.title}" e todos os cards?`)) return;
    try {
      await api.excluirDeck(deck.id);
      await carregar(pastaAtiva);
    } catch (err) {
      setErro(err.message);
    }
  }

  const podeAdicionarPasta = !pastaAtiva || pastaAtiva.depth < 4;

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
        {/* Breadcrumb */}
        <nav className="breadcrumb" aria-label="Localização">
          <button
            className={`breadcrumb-item${!pastaAtiva ? " ativo" : ""}`}
            onClick={() => navegarBreadcrumb(-1)}
          >
            Início
          </button>
          {caminho.map((pasta, idx) => (
            <span key={pasta.id} className="breadcrumb-sep-wrapper">
              <span className="breadcrumb-sep">/</span>
              <button
                className={`breadcrumb-item${idx === caminho.length - 1 ? " ativo" : ""}`}
                onClick={() => navegarBreadcrumb(idx)}
              >
                {pasta.name}
              </button>
            </span>
          ))}
        </nav>

        {erro && <p className="erro">{erro}</p>}

        {/* Formulário inline: criar pasta */}
        {criandoPasta && (
          <form className="criar-pasta-form" onSubmit={criarPasta}>
            <input
              ref={inputPastaRef}
              value={nomePasta}
              onChange={(e) => setNomePasta(e.target.value)}
              placeholder="Nome da pasta"
            />
            <button
              className="botao-principal"
              type="submit"
              disabled={salvandoPasta || !nomePasta.trim()}
            >
              {salvandoPasta ? "Criando…" : "Criar"}
            </button>
            <button
              type="button"
              className="botao-texto"
              onClick={() => { setCriandoPasta(false); setNomePasta(""); }}
            >
              Cancelar
            </button>
          </form>
        )}

        {/* Grade de pastas e decks */}
        {carregando ? (
          <p className="vazio">Carregando…</p>
        ) : pastasVisiveis.length === 0 && decksVisiveis.length === 0 ? (
          <div className="vazio-bloco">
            <p>Nada aqui ainda.</p>
            <p className="vazio-dica">Use o botão + para criar uma pasta ou um deck.</p>
          </div>
        ) : (
          <div className="explorer-grid">
            {pastasVisiveis.map((pasta) => (
              <button
                key={pasta.id}
                className="explorer-item explorer-pasta"
                onClick={() => entrarPasta(pasta)}
              >
                <span className="explorer-item-icon"><IconePasta /></span>
                <span className="explorer-item-info">
                  <span className="explorer-item-nome">{pasta.name}</span>
                  <span className="explorer-item-meta">
                    {(pasta.children || []).length} subpasta{(pasta.children || []).length !== 1 ? "s" : ""}
                  </span>
                </span>
                <span
                  className="explorer-excluir"
                  role="button"
                  tabIndex={0}
                  title="Excluir pasta"
                  onClick={(e) => excluirPasta(pasta, e)}
                  onKeyDown={(e) => e.key === "Enter" && excluirPasta(pasta, e)}
                >
                  ×
                </span>
              </button>
            ))}

            {decksVisiveis.map((deck) => (
              <div key={deck.id} className="explorer-item explorer-deck">
                <button className="explorer-deck-principal" onClick={() => aoVerCards(deck)}>
                  <span className="explorer-item-icon"><IconeDeck /></span>
                  <span className="explorer-item-info">
                    <span className="explorer-item-nome">{deck.title}</span>
                    {deck.description && (
                      <span className="explorer-item-meta">{deck.description}</span>
                    )}
                  </span>
                </button>
                <div className="explorer-deck-acoes">
                  <button className="botao-estudar" onClick={() => aoEstudar(deck)}>
                    Estudar
                  </button>
                  <span
                    className="explorer-excluir"
                    role="button"
                    tabIndex={0}
                    title="Excluir deck"
                    onClick={(e) => excluirDeck(deck, e)}
                    onKeyDown={(e) => e.key === "Enter" && excluirDeck(deck, e)}
                  >
                    ×
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Botão "+" flutuante */}
      <div className="fab-wrapper" ref={menuRef}>
        {menuAberto && (
          <div className="fab-menu">
            {podeAdicionarPasta && (
              <button
                className="fab-menu-item"
                onClick={() => {
                  setMenuAberto(false);
                  setCriandoPasta(true);
                  setNomePasta("");
                }}
              >
                <span className="fab-menu-icone"><IconePasta /></span>
                Criar pasta
              </button>
            )}
            <button
              className="fab-menu-item"
              onClick={() => {
                setMenuAberto(false);
                aoCriarDeck(pastaAtiva?.id ?? null);
              }}
            >
              <span className="fab-menu-icone"><IconeDeck /></span>
              Criar deck
            </button>
          </div>
        )}
        <button
          className="fab"
          onClick={() => setMenuAberto(v => !v)}
          aria-label="Adicionar pasta ou deck"
        >
          <span className={`fab-icone${menuAberto ? " aberto" : ""}`}>+</span>
        </button>
      </div>
    </div>
  );
}

function IconePasta() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M2 6a2 2 0 012-2h3.172a2 2 0 011.414.586l.828.828A2 2 0 0010.828 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"
        fill="currentColor" opacity=".25" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
    </svg>
  );
}

function IconeDeck() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <rect x="3" y="5" width="14" height="11" rx="2"
        fill="currentColor" opacity=".25" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M7 5V4a1 1 0 011-1h4a1 1 0 011 1v1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}
