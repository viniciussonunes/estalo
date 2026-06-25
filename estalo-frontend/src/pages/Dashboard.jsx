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

/** Coleta todos os decks dentro de uma pasta (recursivo) */
function coletarDecks(pasta, todosDecks) {
  const diretos = todosDecks.filter(d => d.folder_id === pasta.id);
  const filhos  = (pasta.children || []).flatMap(sub => coletarDecks(sub, todosDecks));
  return [...diretos, ...filhos];
}

/** Média de memorização dos decks de uma pasta (null = sem dados) */
function progressoDaPasta(pasta, todosDecks) {
  const decks = coletarDecks(pasta, todosDecks);
  if (decks.length === 0) return null;
  return decks.reduce((s, d) => s + (d.memorization_pct || 0), 0) / decks.length;
}

/** Barra de progresso inline */
function BarraProgresso({ pct, label }) {
  if (pct === null || pct === undefined) return null;
  const cor = pct >= 80 ? "#16a34a" : pct >= 40 ? "#d97706" : "#7c3aed";
  return (
    <div className="lista-progresso" title={label ?? `${Math.round(pct)}%`}>
      <div className="lista-progresso-trilho">
        <div className="lista-progresso-fill" style={{ width: `${pct}%`, background: cor }} />
      </div>
      <span className="lista-progresso-pct">{Math.round(pct)}%</span>
    </div>
  );
}

export default function Dashboard({ usuario, aoSair, aoVerCards, aoEstudar, aoCriarDeck }) {
  const [arvore, setArvore]         = useState([]);
  const [todosDecks, setTodosDecks] = useState([]);
  const [pastaAtiva, setPastaAtiva] = useState(null);
  const [caminho, setCaminho]       = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro]             = useState("");
  const [menuAberto, setMenuAberto] = useState(false);
  const [criandoPasta, setCriandoPasta]   = useState(false);
  const [nomePasta, setNomePasta]         = useState("");
  const [salvandoPasta, setSalvandoPasta] = useState(false);
  const menuRef    = useRef(null);
  const inputRef   = useRef(null);

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

  useEffect(() => {
    function handler(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuAberto(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (criandoPasta) inputRef.current?.focus();
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
    if (idx === -1) { setPastaAtiva(null); setCaminho([]); return; }
    const novo = caminho.slice(0, idx + 1);
    setPastaAtiva(encontrarPasta(arvore, novo[novo.length - 1].id) ?? novo[novo.length - 1]);
    setCaminho(novo);
  }

  async function criarPasta(e) {
    e.preventDefault();
    if (!nomePasta.trim()) return;
    setSalvandoPasta(true);
    try {
      await api.criarPasta(nomePasta.trim(), pastaAtiva?.id ?? null);
      setNomePasta(""); setCriandoPasta(false);
      await carregar(pastaAtiva);
    } catch (err) { setErro(err.message); }
    finally { setSalvandoPasta(false); }
  }

  async function excluirPasta(pasta, e) {
    e.stopPropagation();
    if (!confirm(`Excluir "${pasta.name}" e tudo dentro dela?`)) return;
    try { await api.excluirPasta(pasta.id); await carregar(pastaAtiva); }
    catch (err) { setErro(err.message); }
  }

  async function excluirDeck(deck, e) {
    e.stopPropagation();
    if (!confirm(`Excluir "${deck.title}" e todos os cards?`)) return;
    try { await api.excluirDeck(deck.id); await carregar(pastaAtiva); }
    catch (err) { setErro(err.message); }
  }

  const podeAdicionarPasta = !pastaAtiva || pastaAtiva.depth < 4;
  const vazio = !carregando && pastasVisiveis.length === 0 && decksVisiveis.length === 0;

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

        {/* Formulário criar pasta */}
        {criandoPasta && (
          <form className="criar-pasta-form" onSubmit={criarPasta}>
            <input
              ref={inputRef}
              value={nomePasta}
              onChange={e => setNomePasta(e.target.value)}
              placeholder="Nome da pasta"
            />
            <button className="botao-principal" type="submit"
              disabled={salvandoPasta || !nomePasta.trim()}>
              {salvandoPasta ? "Criando…" : "Criar"}
            </button>
            <button type="button" className="botao-texto"
              onClick={() => { setCriandoPasta(false); setNomePasta(""); }}>
              Cancelar
            </button>
          </form>
        )}

        {/* Lista */}
        {carregando ? (
          <p className="vazio">Carregando…</p>
        ) : vazio ? (
          <div className="vazio-bloco">
            <p>Nada aqui ainda.</p>
            <p className="vazio-dica">Use o botão + para criar uma pasta ou deck.</p>
          </div>
        ) : (
          <ul className="lista-explorer">
            {/* Pastas */}
            {pastasVisiveis.map(pasta => {
              const pct      = progressoDaPasta(pasta, todosDecks);
              const nDecks   = coletarDecks(pasta, todosDecks).length;
              const nSubpast = (pasta.children || []).length;
              const meta     = [
                nDecks > 0    && `${nDecks} deck${nDecks !== 1 ? "s" : ""}`,
                nSubpast > 0  && `${nSubpast} subpasta${nSubpast !== 1 ? "s" : ""}`,
              ].filter(Boolean).join(" · ") || "Vazia";
              return (
                <li key={pasta.id} className="lista-item lista-pasta">
                  <span className="lista-icone pasta"><IconePasta /></span>
                  <button className="lista-info" onClick={() => entrarPasta(pasta)}>
                    <span className="lista-nome">{pasta.name}</span>
                    <span className="lista-meta">{meta}</span>
                  </button>
                  <BarraProgresso pct={pct} label={`${Math.round(pct ?? 0)}% memorizado`} />
                  <div className="lista-acoes">
                    <button className="lista-btn-entrar" onClick={() => entrarPasta(pasta)}
                      title="Abrir pasta">›</button>
                    <button className="lista-btn-excluir"
                      onClick={e => excluirPasta(pasta, e)} title="Excluir">×</button>
                  </div>
                </li>
              );
            })}

            {/* Decks */}
            {decksVisiveis.map(deck => (
              <li key={deck.id} className="lista-item lista-deck">
                <span className="lista-icone deck"><IconeDeck /></span>
                <button className="lista-info" onClick={() => aoVerCards(deck)}>
                  <span className="lista-nome">{deck.title}</span>
                  <span className="lista-meta">
                    {deck.total_cards} card{deck.total_cards !== 1 ? "s" : ""}
                    {deck.description ? ` · ${deck.description}` : ""}
                  </span>
                </button>
                <BarraProgresso pct={deck.memorization_pct}
                  label={`${Math.round(deck.memorization_pct ?? 0)}% memorizado`} />
                <div className="lista-acoes">
                  <button className="botao-estudar"
                    onClick={() => aoEstudar(deck)}>Estudar</button>
                  <button className="lista-btn-excluir"
                    onClick={e => excluirDeck(deck, e)} title="Excluir">×</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>

      {/* FAB */}
      <div className="fab-wrapper" ref={menuRef}>
        {menuAberto && (
          <div className="fab-menu">
            {podeAdicionarPasta && (
              <button className="fab-menu-item" onClick={() => {
                setMenuAberto(false); setCriandoPasta(true); setNomePasta("");
              }}>
                <span className="fab-menu-icone"><IconePasta /></span>
                Criar pasta
              </button>
            )}
            <button className="fab-menu-item" onClick={() => {
              setMenuAberto(false); aoCriarDeck(pastaAtiva?.id ?? null);
            }}>
              <span className="fab-menu-icone"><IconeDeck /></span>
              Criar deck
            </button>
          </div>
        )}
        <button className="fab" onClick={() => setMenuAberto(v => !v)}
          aria-label="Adicionar">
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
      <path d="M7 5V4a1 1 0 011-1h4a1 1 0 011 1v1"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}
