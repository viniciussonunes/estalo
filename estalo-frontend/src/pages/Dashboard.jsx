import { useState, useEffect, useCallback, useRef } from "react";
import * as Sentry from "@sentry/react";
import { api } from "../api.js";

/** Devolve o caminho (array de pastas) da raiz até `targetId` */
function caminhoParaPasta(arvore, targetId, path = []) {
  for (const p of arvore) {
    if (p.id === targetId) return [...path, p];
    const found = caminhoParaPasta(p.children || [], targetId, [...path, p]);
    if (found) return found;
  }
  return null;
}

function encontrarPasta(arvore, id) {
  for (const p of arvore) {
    if (p.id === id) return p;
    const found = encontrarPasta(p.children || [], id);
    if (found) return found;
  }
  return null;
}

/** Achata a árvore de pastas numa lista plana, com nível (pra indentar no seletor de mover) */
function achatarPastas(arvore, nivel = 0) {
  return arvore.flatMap(p => [
    { id: p.id, name: p.name, nivel },
    ...achatarPastas(p.children || [], nivel + 1),
  ]);
}

/** Coleta todos os decks dentro de uma pasta (recursivo) */
function coletarDecks(pasta, todosDecks) {
  const diretos = todosDecks.filter(d => d.folder_id === pasta.id);
  const filhos  = (pasta.children || []).flatMap(sub => coletarDecks(sub, todosDecks));
  return [...diretos, ...filhos];
}

/** Coleta os ids da pasta e de toda a sub-árvore dela (pra saber o que uma exclusão em cascata leva junto) */
function coletarIdsPastas(pasta) {
  return [pasta.id, ...(pasta.children || []).flatMap(coletarIdsPastas)];
}

/** Nova árvore com `novoNo` inserido como filho de `parentId` (raiz se parentId for null) */
function inserirNaArvore(arvore, parentId, novoNo) {
  if (parentId === null) return [...arvore, novoNo];
  return arvore.map(p => p.id === parentId
    ? { ...p, children: [...(p.children || []), novoNo] }
    : { ...p, children: inserirNaArvore(p.children || [], parentId, novoNo) });
}

/** Nova árvore com a pasta `id` renomeada */
function renomearNaArvore(arvore, id, novoNome) {
  return arvore.map(p => p.id === id
    ? { ...p, name: novoNome }
    : { ...p, children: renomearNaArvore(p.children || [], id, novoNome) });
}

/** Nova árvore sem a pasta `id` (e sua sub-árvore) */
function removerDaArvore(arvore, id) {
  return arvore
    .filter(p => p.id !== id)
    .map(p => ({ ...p, children: removerDaArvore(p.children || [], id) }));
}

/** Agrega stats de todos os decks contidos em uma pasta (recursivo) */
function agregarStats(pasta, todosDecks, statsMap) {
  const decks = coletarDecks(pasta, todosDecks);
  const zero = { total_cards: 0, criticos: 0, hoje: 0, novos: 0, validando: 0, dominados: 0 };
  return decks.reduce((acc, d) => {
    const s = statsMap[d.id];
    if (!s) return acc;
    return {
      total_cards: acc.total_cards + (s.total_cards ?? 0),
      criticos:    acc.criticos    + (s.criticos    ?? 0),
      hoje:        acc.hoje        + (s.hoje        ?? 0),
      novos:       acc.novos       + (s.novos       ?? s.new_cards ?? 0),
      validando:   acc.validando   + (s.validando   ?? s.validating ?? 0),
      dominados:   acc.dominados   + (s.dominados   ?? s.dominated  ?? 0),
    };
  }, zero);
}

/**
 * Barra segmentada em 4 faixas proporcionais ao total de cards.
 * Segmentos: Críticos (vermelho) · Hoje (âmbar) · Novos+Validando (cinza) · Dominados (verde)
 */
function BarraSegmentada({ stats, carregando = false }) {
  if (carregando) return <div className="barra-seg barra-seg-skeleton" />;

  const total = stats?.total_cards || 0;
  if (total === 0) return <div className="barra-seg barra-seg-vazia" />;

  const pct = (v) => Math.max(0, Math.min(100, ((v || 0) / total) * 100));

  const sCriticos  = pct(stats.criticos);
  const sHoje      = pct(stats.hoje);
  const sNovos     = pct(stats.novos);
  const sValidando = pct(stats.validando);
  const sDominados = pct(stats.dominados);

  const tooltip = [
    stats.criticos  && `${stats.criticos} crítico${stats.criticos  !== 1 ? "s" : ""}`,
    stats.hoje      && `${stats.hoje} hoje`,
    stats.novos     && `${stats.novos} novo${stats.novos !== 1 ? "s" : ""}`,
    stats.validando && `${stats.validando} validando`,
    stats.dominados && `${stats.dominados} dominado${stats.dominados !== 1 ? "s" : ""}`,
  ].filter(Boolean).join(" · ");

  return (
    <div className="barra-seg" title={tooltip || `${total} cards`} aria-hidden="true">
      {sCriticos  > 0 && <span className="barra-seg-fatia seg-critico"   style={{ width: `${sCriticos}%`  }} />}
      {sHoje      > 0 && <span className="barra-seg-fatia seg-hoje"      style={{ width: `${sHoje}%`      }} />}
      {sNovos     > 0 && <span className="barra-seg-fatia seg-novo"      style={{ width: `${sNovos}%`     }} />}
      {sValidando > 0 && <span className="barra-seg-fatia seg-validando" style={{ width: `${sValidando}%` }} />}
      {sDominados > 0 && <span className="barra-seg-fatia seg-dominado"  style={{ width: `${sDominados}%` }} />}
    </div>
  );
}

/** Skeleton de um card de pasta (grid) — mesma estrutura do card real, só com barras de brilho no lugar do texto. */
function PastaCardSkeleton() {
  return (
    <div className="pasta-card">
      <div className="pasta-card-corpo" style={{ cursor: "default" }}>
        <span className="pasta-card-icone skeleton" style={{ width: 18, height: 18, display: "inline-block" }} />
        <span className="pasta-card-nome skeleton skeleton-linha" style={{ width: "70%" }} />
        <span className="pasta-card-meta skeleton skeleton-linha" style={{ width: "40%", marginBottom: 0 }} />
        <BarraSegmentada carregando />
      </div>
    </div>
  );
}

/** Skeleton de uma linha de pasta (lista) */
function PastaListaSkeleton() {
  return (
    <li className="lista-item lista-pasta">
      <span className="lista-icone pasta skeleton" />
      <div className="lista-info">
        <span className="skeleton skeleton-linha" style={{ width: "45%", marginBottom: 0 }} />
      </div>
      <BarraSegmentada carregando />
      <div className="lista-acoes" style={{ width: 60 }} />
    </li>
  );
}

/** Skeleton de uma linha de deck (mesma estrutura em ambos os modos de visualização) */
function DeckListaSkeleton() {
  return (
    <li className="lista-item lista-deck">
      <span className="lista-icone deck skeleton" />
      <div className="lista-info">
        <span className="skeleton skeleton-linha" style={{ width: "55%" }} />
        <span className="skeleton skeleton-linha" style={{ width: "30%", height: "0.7em", marginBottom: 0 }} />
      </div>
      <BarraSegmentada carregando />
      <div className="lista-acoes" style={{ width: 120 }} />
    </li>
  );
}

/**
 * Skeleton do explorador inteiro, no carregamento inicial do Dashboard.
 * Reproduz a mesma estrutura (seções, grid/lista conforme viewMode) que o
 * conteúdo real vai assumir — a transição de skeleton pra dados de verdade
 * não pula o layout, só troca as barras de brilho pelo conteúdo.
 */
function ExplorerSkeleton({ viewMode }) {
  return (
    <div className="explorer-secoes">
      <section className="explorer-secao">
        <div className="explorer-secao-header">
          <h2 className="explorer-secao-titulo">Pastas</h2>
        </div>
        {viewMode === "grid" ? (
          <div className="pastas-grid">
            <PastaCardSkeleton /><PastaCardSkeleton /><PastaCardSkeleton />
          </div>
        ) : (
          <ul className="pastas-lista lista-explorer">
            <PastaListaSkeleton /><PastaListaSkeleton /><PastaListaSkeleton />
          </ul>
        )}
      </section>
      <section className="explorer-secao">
        <div className="explorer-secao-header">
          <h2 className="explorer-secao-titulo">Decks</h2>
        </div>
        <ul className="lista-explorer">
          <DeckListaSkeleton /><DeckListaSkeleton /><DeckListaSkeleton />
        </ul>
      </section>
    </div>
  );
}

export default function Dashboard({ usuario, aoSair, aoVerCards, aoEstudar, aoCriarDeck, tema, proximoTema }) {
  const [arvore, setArvore]         = useState([]);
  const [todosDecks, setTodosDecks] = useState([]);
  const [statsMap, setStatsMap]     = useState({});   // { [deckId]: StudyStats }
  const [statsCarregando, setStatsCarregando] = useState(false);
  const [pastaAtiva, setPastaAtiva] = useState(null);
  const [caminho, setCaminho]       = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro]             = useState("");
  const [criandoPasta, setCriandoPasta]   = useState(false);
  const [nomePasta, setNomePasta]         = useState("");
  const [salvandoPasta, setSalvandoPasta] = useState(false);
  const [editando, setEditando] = useState(null); // { tipo: "pasta"|"deck", id, valor }
  const [movendo, setMovendo]   = useState(null); // deck sendo movido, ou null
  const [viewMode, setViewMode] = useState(() => {
    try { return localStorage.getItem("dashboard_view_mode") === "list" ? "list" : "grid"; }
    catch { return "grid"; }
  });
  const inputRef = useRef(null);

  useEffect(() => {
    try { localStorage.setItem("dashboard_view_mode", viewMode); } catch { /* localStorage indisponível */ }
  }, [viewMode]);

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

      // Carrega stats de todos os decks numa única chamada (sem bloquear a UI)
      if (novosDecks.length > 0) {
        setStatsCarregando(true);
        api.statsMultiplos(novosDecks.map(d => d.id))
          .then(mapa => setStatsMap(mapa))
          .finally(() => setStatsCarregando(false));
      }
    } catch (err) {
      setErro(err.message);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  useEffect(() => {
    if (criandoPasta) inputRef.current?.focus();
  }, [criandoPasta]);

  // Aplica uma nova árvore e resincroniza pastaAtiva com ela (senão
  // pastaAtiva.children fica congelado na versão de quando você entrou
  // na pasta, e mudanças nos filhos não apareceriam na tela).
  function aplicarArvore(novaArvore) {
    setArvore(novaArvore);
    setPastaAtiva(pa => pa ? (encontrarPasta(novaArvore, pa.id) ?? null) : pa);
  }

  const pastasVisiveis = pastaAtiva ? (pastaAtiva.children || []) : arvore;
  const decksVisiveis  = todosDecks.filter(d =>
    pastaAtiva ? d.folder_id === pastaAtiva.id : !d.folder_id
  );

  function entrarPasta(pasta) {
    setPastaAtiva(pasta);
    setCaminho(c => [...c, pasta]);
    setCriandoPasta(false);
  }

  function navegarBreadcrumb(idx) {
    if (idx === -1) { setPastaAtiva(null); setCaminho([]); return; }
    const novo = caminho.slice(0, idx + 1);
    setPastaAtiva(encontrarPasta(arvore, novo[novo.length - 1].id) ?? novo[novo.length - 1]);
    setCaminho(novo);
  }

  function irParaPastaSidebar(pasta) {
    if (!pasta) { setPastaAtiva(null); setCaminho([]); return; }
    const path = caminhoParaPasta(arvore, pasta.id) ?? [pasta];
    setPastaAtiva(encontrarPasta(arvore, pasta.id) ?? pasta);
    setCaminho(path);
    setCriandoPasta(false);
  }

  async function criarPasta(e) {
    e.preventDefault();
    if (!nomePasta.trim()) return;
    setSalvandoPasta(true);
    try {
      const nova = await api.criarPasta(nomePasta.trim(), pastaAtiva?.id ?? null);
      setNomePasta(""); setCriandoPasta(false);
      aplicarArvore(inserirNaArvore(arvore, pastaAtiva?.id ?? null, { ...nova, children: [] }));
    } catch (err) { setErro(err.message); }
    finally { setSalvandoPasta(false); }
  }

  async function excluirPasta(pasta, e) {
    e.stopPropagation();
    if (!confirm(`Excluir "${pasta.name}" e tudo dentro dela?`)) return;
    try {
      await api.excluirPasta(pasta.id);
      const idsRemovidos = new Set(coletarIdsPastas(pasta));
      aplicarArvore(removerDaArvore(arvore, pasta.id));
      setTodosDecks(decks => decks.filter(d => d.folder_id === null || !idsRemovidos.has(d.folder_id)));
      setStatsMap(sm => {
        const novo = { ...sm };
        for (const d of todosDecks) {
          if (d.folder_id !== null && idsRemovidos.has(d.folder_id)) delete novo[d.id];
        }
        return novo;
      });
    } catch (err) { setErro(err.message); }
  }

  async function excluirDeck(deck, e) {
    e.stopPropagation();
    if (!confirm(`Excluir "${deck.title}" e todos os cards?`)) return;
    try {
      await api.excluirDeck(deck.id);
      setTodosDecks(decks => decks.filter(d => d.id !== deck.id));
      setStatsMap(sm => { const novo = { ...sm }; delete novo[deck.id]; return novo; });
    } catch (err) { setErro(err.message); }
  }

  function abrirMover(deck, e) {
    e.stopPropagation();
    setMovendo(deck);
  }

  async function moverPara(folderId) {
    if (!movendo) return;
    const deck = movendo;
    setMovendo(null);
    try {
      const atualizado = await api.moverDeck(deck.id, folderId);
      setTodosDecks(decks => decks.map(d => d.id === deck.id ? atualizado : d));
    } catch (err) { setErro(err.message); }
  }

  function iniciarEdicao(tipo, id, valorAtual, e) {
    e.stopPropagation();
    setEditando({ tipo, id, valor: valorAtual });
  }

  async function confirmarEdicao() {
    if (!editando) return;
    const { tipo, id, valor } = editando;
    setEditando(null);
    const nomeNovo = valor.trim();
    if (!nomeNovo) return;
    try {
      if (tipo === "pasta") {
        await api.renomearPasta(id, nomeNovo);
        aplicarArvore(renomearNaArvore(arvore, id, nomeNovo));
      } else {
        const atualizado = await api.renomearDeck(id, nomeNovo);
        setTodosDecks(decks => decks.map(d => d.id === id ? atualizado : d));
      }
    } catch (err) { setErro(err.message); }
  }

  const podeAdicionarPasta = !pastaAtiva || pastaAtiva.depth < 4;
  const vazio = !carregando && pastasVisiveis.length === 0 && decksVisiveis.length === 0;

  return (
    <div className="pagina dashboard-layout">
      <header className="topo">
        <span className="marca-nome pequeno">Estalo</span>
        <div className="topo-direita">
          {import.meta.env.DEV && <BotaoTesteSentry />}
          <ToggleTema tema={tema} proximoTema={proximoTema} />
          <span className="usuario-email">{usuario.email}</span>
          <button className="botao-texto" onClick={aoSair}>Sair</button>
        </div>
      </header>

      <div className="dashboard-corpo">
        {/* Sidebar — visível apenas em desktop */}
        <aside className="dashboard-sidebar">
          <span className="sidebar-label">Pastas</span>
          <ul className="sidebar-arvore">
            <li>
              <div className="sidebar-no-row">
                <button
                  className={`sidebar-no-btn${!pastaAtiva ? " ativo" : ""}`}
                  onClick={() => irParaPastaSidebar(null)}
                >
                  <IconeHome /> Início
                </button>
              </div>
            </li>
            {arvore.map(p => (
              <SidebarNo key={p.id} pasta={p} pastaAtiva={pastaAtiva}
                aoNavegar={irParaPastaSidebar} nivel={0} />
            ))}
          </ul>
        </aside>

      <main className="conteudo dashboard-main">
      <div className="dash-container">
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

        {/* Visão Geral — só na raiz */}
        {!pastaAtiva && !carregando && todosDecks.length > 0 && (
          <VisaoGeral decks={todosDecks} />
        )}

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
          <ExplorerSkeleton viewMode={viewMode} />
        ) : vazio ? (
          <div className="vazio-bloco fade-in">
            <p style={{ fontWeight: 600, marginBottom: "0.35rem" }}>
              {pastaAtiva ? `"${pastaAtiva.name}" está vazia` : "Nenhum conteúdo ainda"}
            </p>
            <p className="vazio-dica" style={{ marginBottom: "1rem" }}>
              Crie {pastaAtiva && pastaAtiva.depth < 4 ? "uma subpasta ou " : ""}um deck para começar.
            </p>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              {podeAdicionarPasta && (
                <button className="btn-secao-acao"
                  onClick={() => { setCriandoPasta(true); setNomePasta(""); }}>
                  + Nova Pasta
                </button>
              )}
              <button className="btn-secao-acao primario"
                onClick={() => aoCriarDeck(pastaAtiva?.id ?? null)}>
                + Novo Deck
              </button>
            </div>
          </div>
        ) : (
          <div className="explorer-secoes fade-in">
            {/* ── Pastas: grid ou lista, conforme viewMode ── */}
            {pastasVisiveis.length > 0 && (
              <section className="explorer-secao">
                <div className="explorer-secao-header">
                  <h2 className="explorer-secao-titulo">Pastas</h2>
                  <div className="explorer-secao-acoes">
                    <div className="view-toggle" role="group" aria-label="Modo de exibição das pastas">
                      <button
                        className={`view-toggle-btn${viewMode === "grid" ? " ativo" : ""}`}
                        onClick={() => setViewMode("grid")} title="Ver em blocos">
                        <IconeGrid />
                      </button>
                      <button
                        className={`view-toggle-btn${viewMode === "list" ? " ativo" : ""}`}
                        onClick={() => setViewMode("list")} title="Ver em lista">
                        <IconeListaModo />
                      </button>
                    </div>
                    {podeAdicionarPasta && (
                      <button className="btn-secao-acao"
                        onClick={() => { setCriandoPasta(true); setNomePasta(""); }}>
                        + Nova Pasta
                      </button>
                    )}
                  </div>
                </div>
                {viewMode === "grid" ? (
                  <div className="pastas-grid">
                    {pastasVisiveis.map(pasta => (
                      <PastaItem key={pasta.id} viewMode="grid" pasta={pasta} todosDecks={todosDecks}
                        statsMap={statsMap} statsCarregando={statsCarregando} editando={editando}
                        setEditando={setEditando} confirmarEdicao={confirmarEdicao}
                        iniciarEdicao={iniciarEdicao} entrarPasta={entrarPasta} excluirPasta={excluirPasta} />
                    ))}
                  </div>
                ) : (
                  <ul className="pastas-lista lista-explorer">
                    {pastasVisiveis.map(pasta => (
                      <PastaItem key={pasta.id} viewMode="list" pasta={pasta} todosDecks={todosDecks}
                        statsMap={statsMap} statsCarregando={statsCarregando} editando={editando}
                        setEditando={setEditando} confirmarEdicao={confirmarEdicao}
                        iniciarEdicao={iniciarEdicao} entrarPasta={entrarPasta} excluirPasta={excluirPasta} />
                    ))}
                  </ul>
                )}
              </section>
            )}

            {/* ── Decks em lista ── */}
            {decksVisiveis.length > 0 && (
              <section className="explorer-secao">
                <div className="explorer-secao-header">
                  <h2 className="explorer-secao-titulo">Decks</h2>
                  <button className="btn-secao-acao primario"
                    onClick={() => aoCriarDeck(pastaAtiva?.id ?? null)}>
                    + Novo Deck
                  </button>
                </div>
                <ul className="lista-explorer">
                  {decksVisiveis.map(deck => {
                    const s = statsMap[deck.id];
                    const temCriticos  = (s?.criticos ?? 0) > 0;
                    const temHoje      = (s?.hoje     ?? 0) > 0;
                    const temPendentes = temCriticos || temHoje ||
                      (s ? (s.novos ?? s.new_cards ?? 0) > 0 : (deck.memorization_pct ?? 0) < 100);
                    const editandoEste = editando?.tipo === "deck" && editando.id === deck.id;
                    return (
                      <li key={deck.id} className="lista-item lista-deck">
                        <span className="lista-icone deck"><IconeDeck /></span>
                        {editandoEste ? (
                          <div className="lista-info">
                            <input
                              className="lista-nome-input"
                              value={editando.valor}
                              autoFocus
                              onFocus={e => e.target.select()}
                              onChange={e => setEditando(ed => ({ ...ed, valor: e.target.value }))}
                              onBlur={confirmarEdicao}
                              onKeyDown={e => {
                                if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
                                if (e.key === "Escape") { e.preventDefault(); setEditando(null); }
                              }}
                            />
                          </div>
                        ) : (
                          <button className="lista-info" onClick={() => aoVerCards(deck)}>
                            <span className="lista-nome">{deck.title}</span>
                            <span className="lista-meta">
                              {deck.total_cards} card{deck.total_cards !== 1 ? "s" : ""}
                              {deck.description ? ` · ${deck.description}` : ""}
                              {temCriticos && (
                                <span className="badge-critico-mini">{s.criticos} crítico{s.criticos !== 1 ? "s" : ""}</span>
                              )}
                            </span>
                          </button>
                        )}
                        <BarraSegmentada
                          stats={s}
                          carregando={statsCarregando && !s}
                        />
                        <div className="lista-acoes">
                          <button
                            className={temCriticos ? "botao-estudar-critico" : temPendentes ? "botao-estudar-primary" : "botao-estudar"}
                            onClick={() => aoEstudar(deck)}>
                            {temCriticos ? `🔴 ${s.criticos}` : "Estudar"}
                          </button>
                          <button className="icone-acao lista-deck-editar"
                            onClick={e => iniciarEdicao("deck", deck.id, deck.title, e)} title="Renomear deck">
                            <IcoLapis />
                          </button>
                          <button className="icone-acao lista-deck-editar"
                            onClick={e => abrirMover(deck, e)} title="Mover deck">
                            <IcoMover />
                          </button>
                          <button className="icone-acao perigo lista-deck-excluir"
                            onClick={e => excluirDeck(deck, e)} title="Excluir deck">
                            <IcoTrash />
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
          </div>
        )}
      </div>{/* dash-container */}
      </main>
      </div>{/* dashboard-corpo */}

      {movendo && (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setMovendo(null); }}>
          <div className="modal-painel modal-mover">
            <div className="modal-cabecalho">
              <h2 className="modal-titulo">Mover "{movendo.title}"</h2>
              <button className="modal-fechar" onClick={() => setMovendo(null)} aria-label="Fechar">×</button>
            </div>
            <ul className="mover-lista-pastas">
              <li>
                <button
                  className={`mover-opcao-pasta${movendo.folder_id === null ? " ativa" : ""}`}
                  onClick={() => moverPara(null)}>
                  <IconeHome /> Raiz
                </button>
              </li>
              {achatarPastas(arvore).map(p => (
                <li key={p.id}>
                  <button
                    className={`mover-opcao-pasta${movendo.folder_id === p.id ? " ativa" : ""}`}
                    style={{ paddingLeft: `${0.9 + p.nivel * 1.1}rem` }}
                    onClick={() => moverPara(p.id)}>
                    <IconePasta /> {p.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

/** Uma pasta, renderizada como bloco (grid) ou linha (lista) conforme `viewMode`. */
function PastaItem({
  pasta, viewMode, todosDecks, statsMap, statsCarregando,
  editando, setEditando, confirmarEdicao, iniciarEdicao, entrarPasta, excluirPasta,
}) {
  const nDecks   = coletarDecks(pasta, todosDecks).length;
  const nSubpast = (pasta.children || []).length;
  const meta     = [
    nDecks > 0   && `${nDecks} deck${nDecks !== 1 ? "s" : ""}`,
    nSubpast > 0 && `${nSubpast} subpasta${nSubpast !== 1 ? "s" : ""}`,
  ].filter(Boolean).join(" · ") || "Vazia";
  const statsAgregadas = agregarStats(pasta, todosDecks, statsMap);
  const temCriticos = statsAgregadas.criticos > 0;
  const editandoEsta = editando?.tipo === "pasta" && editando.id === pasta.id;
  const barra = (
    <BarraSegmentada
      stats={statsAgregadas}
      carregando={statsCarregando && nDecks > 0 && statsAgregadas.total_cards === 0}
    />
  );
  const inputNome = (
    <input
      className={viewMode === "grid" ? "pasta-card-nome-input" : "lista-nome-input"}
      value={editando?.valor ?? ""}
      autoFocus
      onFocus={e => e.target.select()}
      onChange={e => setEditando(ed => ({ ...ed, valor: e.target.value }))}
      onBlur={confirmarEdicao}
      onKeyDown={e => {
        if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
        if (e.key === "Escape") { e.preventDefault(); setEditando(null); }
      }}
    />
  );

  if (viewMode === "list") {
    return (
      <li className="lista-item lista-pasta">
        <span className="lista-icone pasta"><IconePasta /></span>
        {editandoEsta ? (
          <div className="lista-info">{inputNome}</div>
        ) : (
          <button className="lista-info" onClick={() => entrarPasta(pasta)}>
            <span className="lista-nome">{pasta.name}</span>
            <span className="lista-meta">{meta}</span>
          </button>
        )}
        {barra}
        <div className="lista-acoes">
          <button className="icone-acao lista-deck-editar"
            onClick={e => iniciarEdicao("pasta", pasta.id, pasta.name, e)} title="Renomear pasta">
            <IcoLapis />
          </button>
          <button className="icone-acao perigo lista-deck-excluir"
            onClick={e => excluirPasta(pasta, e)} title="Excluir pasta">
            <IcoTrash />
          </button>
        </div>
      </li>
    );
  }

  return (
    <div className={`pasta-card${temCriticos ? " pasta-card-alerta" : ""}`}>
      {editandoEsta ? (
        <div className="pasta-card-corpo">
          <span className="pasta-card-icone"><IconePasta /></span>
          {inputNome}
        </div>
      ) : (
        <button className="pasta-card-corpo" onClick={() => entrarPasta(pasta)}>
          <span className="pasta-card-icone"><IconePasta /></span>
          <span className="pasta-card-nome">{pasta.name}</span>
          <span className="pasta-card-meta">{meta}</span>
          {barra}
        </button>
      )}
      <button className="pasta-card-editar icone-acao"
        onClick={e => iniciarEdicao("pasta", pasta.id, pasta.name, e)} title="Renomear pasta">
        <IcoLapis />
      </button>
      <button className="pasta-card-excluir icone-acao perigo"
        onClick={e => excluirPasta(pasta, e)} title="Excluir pasta">
        <IcoTrash />
      </button>
    </div>
  );
}

function SidebarNo({ pasta, pastaAtiva, aoNavegar, nivel }) {
  const [aberta, setAberta] = useState(nivel < 1);
  const eAtiva = pastaAtiva?.id === pasta.id;
  const temFilhos = (pasta.children || []).length > 0;
  const indent = (nivel + 1) * 12;

  return (
    <li>
      <div className="sidebar-no-row" style={{ paddingLeft: `${indent}px` }}>
        {temFilhos ? (
          <button className={`sidebar-chevron${aberta ? " aberto" : ""}`}
            onClick={e => { e.stopPropagation(); setAberta(v => !v); }}>
            ▶
          </button>
        ) : <span style={{ width: 22, flexShrink: 0 }} />}
        <button className={`sidebar-no-btn${eAtiva ? " ativo" : ""}`}
          onClick={() => aoNavegar(pasta)}>
          <IconePasta />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{pasta.name}</span>
        </button>
      </div>
      {aberta && temFilhos && (
        <ul className="sidebar-arvore">
          {pasta.children.map(filho => (
            <SidebarNo key={filho.id} pasta={filho} pastaAtiva={pastaAtiva}
              aoNavegar={aoNavegar} nivel={nivel + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

const TEMA_ICONES = { light: IconeSol, dark: IconeLua, system: IconeMonitor };
const TEMA_LABELS = { light: "Claro", dark: "Escuro", system: "Sistema" };

/** Botão único que cicla light → dark → system → light. */
/** Só renderiza em dev (import.meta.env.DEV). Dispara um erro simulado
 * pro Sentry pra verificar a captura sem precisar quebrar a UI de verdade. */
function BotaoTesteSentry() {
  function disparar() {
    const id = Sentry.captureException(new Error("[teste] erro simulado disparado manualmente"));
    console.info("[Sentry] captureException chamado, event id:", id);
  }
  return (
    <button className="botao-texto" onClick={disparar} title="Dispara um erro de teste pro Sentry (só em dev)">
      🐞 Testar Sentry
    </button>
  );
}

function ToggleTema({ tema, proximoTema }) {
  const Icone = TEMA_ICONES[tema] ?? IconeMonitor;
  return (
    <button className="toggle-tema" onClick={proximoTema}
      title={`Tema: ${TEMA_LABELS[tema] ?? "Sistema"} (clique para trocar)`}>
      <Icone />
    </button>
  );
}

function IconeSol() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <circle cx="10" cy="10" r="3.5" />
      <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M4.2 15.8l1.4-1.4M14.4 5.6l1.4-1.4" />
    </svg>
  );
}

function IconeLua() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path d="M16.7 12.4A7 7 0 018.1 3.3a.6.6 0 00-.7-.8A8 8 0 1017.5 13a.6.6 0 00-.8-.6z" />
    </svg>
  );
}

function IconeMonitor() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
      <rect x="2.5" y="4" width="15" height="10" rx="1.3" />
      <path d="M7 17.5h6M10 14v3.5" strokeLinecap="round" />
    </svg>
  );
}

function IconeGrid() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinejoin="round" aria-hidden="true">
      <rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1.2" />
      <rect x="11" y="2.5" width="6.5" height="6.5" rx="1.2" />
      <rect x="2.5" y="11" width="6.5" height="6.5" rx="1.2" />
      <rect x="11" y="11" width="6.5" height="6.5" rx="1.2" />
    </svg>
  );
}

function IconeListaModo() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
      <path d="M3 5h14M3 10h14M3 15h14" />
    </svg>
  );
}

function IcoMover() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 6a2 2 0 012-2h3.172a2 2 0 011.414.586l.828.828A2 2 0 0010.828 6H16a2 2 0 012 2v7a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
      <path d="M8 12h5M10.5 9.5L13 12l-2.5 2.5" />
    </svg>
  );
}

function IcoLapis() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M13.5 3.5l3 3L7 16H4v-3L13.5 3.5z" />
    </svg>
  );
}

function IcoTrash() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h14M8 6V4h4v2M5 6l1 11a1 1 0 001 1h6a1 1 0 001-1l1-11" />
    </svg>
  );
}

// Nível de intensidade (0-4) a partir da quantidade de avaliações do dia.
function nivelHeatmap(qtd) {
  if (!qtd) return 0;
  if (qtd <= 2) return 1;
  if (qtd <= 5) return 2;
  if (qtd <= 9) return 3;
  return 4;
}

// Últimos `n` dias (YYYY-MM-DD), do mais antigo pro mais recente.
function ultimosDias(n) {
  return Array.from({ length: n }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (n - 1 - i));
    return d.toISOString().slice(0, 10);
  });
}

const HEATMAP_NIVEIS = [
  { bg: "var(--borda)",    title: "Sem atividade" },
  { bg: "rgba(22,163,74,.25)", title: "Pouca atividade" },
  { bg: "rgba(22,163,74,.50)", title: "Atividade moderada" },
  { bg: "rgba(22,163,74,.75)", title: "Boa atividade" },
  { bg: "var(--verde)",    title: "Muita atividade" },
];

function VisaoGeral({ decks }) {
  const totalCards = decks.reduce((s, d) => s + (d.total_cards || 0), 0);
  const dominados  = decks.reduce((s, d) =>
    s + Math.round(((d.memorization_pct || 0) / 100) * (d.total_cards || 0)), 0);
  const pendentes  = decks.reduce((s, d) =>
    s + Math.round(((1 - (d.memorization_pct || 0) / 100)) * (d.total_cards || 0)), 0);

  const [heatmapStats, setHeatmapStats] = useState({});
  const [heatmapCarregando, setHeatmapCarregando] = useState(true);
  useEffect(() => {
    api.heatmapStats()
      .then(setHeatmapStats)
      .catch(() => setHeatmapStats({}))
      .finally(() => setHeatmapCarregando(false));
  }, []);

  const [streak, setStreak] = useState(null);
  useEffect(() => {
    api.streak().then(setStreak).catch(() => setStreak(null));
  }, []);

  const dias = ultimosDias(30);

  return (
    <div className="visao-geral-wrapper fade-in">
      <div className="visao-geral">
        <div className="visao-card">
          <span className="visao-card-icone">📚</span>
          <div className="visao-card-info">
            <span className="visao-card-valor">{totalCards}</span>
            <span className="visao-card-label">Cards totais</span>
          </div>
        </div>
        <div className="visao-card">
          <span className="visao-card-icone">⏳</span>
          <div className="visao-card-info">
            <span className="visao-card-valor">{pendentes}</span>
            <span className="visao-card-label">Pendentes</span>
          </div>
        </div>
        <div className="visao-card">
          <span className="visao-card-icone">🧠</span>
          <div className="visao-card-info">
            <span className="visao-card-valor">{dominados}</span>
            <span className="visao-card-label">Dominados</span>
          </div>
        </div>
      </div>

      {/* Heatmap de atividade */}
      <div className="heatmap-bloco">
        <div className="heatmap-cabecalho">
          <span className="heatmap-titulo">Atividade — últimos 30 dias</span>
          {streak && streak.current_streak > 0 && (
            <span className="streak-badge"
              title={`Recorde: ${streak.longest_streak} dia${streak.longest_streak !== 1 ? "s" : ""} seguido${streak.longest_streak !== 1 ? "s" : ""}`}>
              🔥 Streak atual: {streak.current_streak} dia{streak.current_streak !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="heatmap-grid">
          {heatmapCarregando
            ? dias.map((data) => <div key={data} className="heatmap-cel skeleton" />)
            : dias.map((data) => {
                const nivel = nivelHeatmap(heatmapStats[data]);
                return (
                  <div key={data} className="heatmap-cel"
                    style={{ background: HEATMAP_NIVEIS[nivel].bg }}
                    title={`${data} — ${HEATMAP_NIVEIS[nivel].title}`} />
                );
              })}
        </div>
        <span className="heatmap-legenda">
          Menos
          {HEATMAP_NIVEIS.map((n, i) => (
            <span key={i} className="heatmap-cel legenda" style={{ background: n.bg }} />
          ))}
          Mais
        </span>
      </div>
    </div>
  );
}

function IconeHome() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7A1 1 0 003 11h1v6a1 1 0 001 1h4v-4h2v4h4a1 1 0 001-1v-6h1a1 1 0 00.707-1.707l-7-7z"/>
    </svg>
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
