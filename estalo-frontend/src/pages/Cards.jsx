import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "../api.js";
import useUndoableDelete from "../hooks/useUndoableDelete.js";
import useOnline from "../hooks/useOnline.js";
import { baixarDeck, estaBaixado } from "../offlineDecks.js";
import UndoToasts from "../components/UndoToasts.jsx";

// Mesma classificação usada nos boxes de resumo (stats-deck) e no backend
// (ver _memorization_pct em decks.py): 0 repetições = novo, 1 = validando,
// 2+ = dominado.
function statusCard(repetitions) {
  if (!repetitions) return "novo";
  if (repetitions === 1) return "validando";
  return "dominado";
}

const MSGS_IA = [
  "Lendo o texto fornecido...",
  "Decompondo conceitos essenciais...",
  "Criando alternativas falsas inteligentes...",
  "Finalizando a formatação dos cards...",
];

export default function Cards({ deck, aoVoltar, aoEstudar, aoAprender, aoRevelar }) {
  const [cards, setCards]         = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro]           = useState("");
  const [stats, setStats]         = useState(null);
  // Excluir card: some da lista na hora, só chama a API se o toast
  // "Desfazer" expirar sem clique (ver useUndoableDelete.js) -- substitui
  // o antigo confirm() nativo.
  const { pendentes: exclusoesPendentes, disparar: dispararExclusao, desfazer: desfazerExclusao } = useUndoableDelete();
  const online = useOnline();

  // Modal
  const [modalAberto, setModalAberto] = useState(false);
  const [abaAtiva, setAbaAtiva]       = useState("manual");

  // Formulário manual
  const [frente, setFrente]   = useState("");
  const [verso, setVerso]     = useState("");
  const [criando, setCriando] = useState(false);

  // Formulário IA
  const [textoIA, setTextoIA] = useState("");
  const [qtdIA, setQtdIA]     = useState(5);
  const [gerando, setGerando] = useState(false);
  const [erroIA, setErroIA]   = useState("");
  const [msgIA, setMsgIA]     = useState(MSGS_IA[0]);
  const msgIAIdx              = useRef(0);

  // Edição inline
  const [cardEditando, setCardEditando] = useState(null);
  const [editFrente, setEditFrente]     = useState("");
  const [editVerso, setEditVerso]       = useState("");
  const [salvandoEdit, setSalvandoEdit] = useState(false);

  const primeiroInputRef = useRef(null);

  const carregarCards = useCallback(async () => {
    setErro("");
    try {
      const [listaCards, dadosStats] = await Promise.all([
        api.listarCards(deck.id),
        api.statsEstudo(deck.id),
      ]);
      setCards(listaCards);
      setStats(dadosStats);
    } catch (err) {
      setErro(err.message);
    } finally {
      setCarregando(false);
    }
  }, [deck.id]);

  useEffect(() => { carregarCards(); }, [carregarCards]);

  // Deck baixado + com internet = atualiza a cópia local em silêncio.
  // Decisão do usuário: manter atualizado sem ele precisar pensar nisso,
  // e só do deck que ele está abrindo (não de todos no boot) -- gasta
  // dados só do que vai ser estudado. Falha aqui não importa: a cópia
  // antiga continua valendo, é melhor que nada.
  useEffect(() => {
    if (!online || !estaBaixado(deck.id)) return;
    baixarDeck(deck).catch(() => { /* mantém a cópia anterior */ });
  }, [online, deck]);

  // Atalho 'C' abre modal; Escape fecha
  useEffect(() => {
    function onKey(e) {
      if (cardEditando) return;
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "c" || e.key === "C") { abrirModal(); return; }
      if (e.key === "Escape") fecharModal();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cardEditando]);

  // Foco no primeiro input ao abrir modal
  useEffect(() => {
    if (modalAberto) setTimeout(() => primeiroInputRef.current?.focus(), 50);
  }, [modalAberto, abaAtiva]);

  // Mensagens rotativas da IA
  useEffect(() => {
    if (!gerando) return;
    setMsgIA(MSGS_IA[0]); msgIAIdx.current = 0;
    const id = setInterval(() => {
      msgIAIdx.current = (msgIAIdx.current + 1) % MSGS_IA.length;
      setMsgIA(MSGS_IA[msgIAIdx.current]);
    }, 2500);
    return () => clearInterval(id);
  }, [gerando]);

  function abrirModal() { setModalAberto(true); setErro(""); setErroIA(""); }
  function fecharModal() {
    setModalAberto(false);
    setFrente(""); setVerso("");
    setTextoIA(""); setQtdIA(5);
    setErro(""); setErroIA("");
  }

  async function criarManual(e) {
    e.preventDefault();
    if (!frente.trim() || !verso.trim()) return;
    setCriando(true); setErro("");
    try {
      await api.criarCard(deck.id, frente.trim(), verso.trim());
      setFrente(""); setVerso("");
      await carregarCards();
      fecharModal();
    } catch (err) { setErro(err.message); }
    finally { setCriando(false); }
  }

  async function gerarIA(e) {
    e.preventDefault();
    if (!textoIA.trim()) return;
    setGerando(true); setErroIA("");
    try {
      await api.gerarCardsIA(deck.id, textoIA.trim(), qtdIA);
      setTextoIA(""); setQtdIA(5);
      await carregarCards();
      fecharModal();
    } catch (err) { setErroIA(err.message); }
    finally { setGerando(false); }
  }

  // Otimista + desfazer: some da lista na hora; guarda o índice original pra
  // reinserir no mesmo lugar se o usuário desfizer (a lista não está
  // ordenada por nenhum critério escolhível aqui, então a posição importa
  // pra não "pular" o card de lugar ao voltar).
  function excluir(cardId) {
    const indiceOriginal = cards.findIndex(c => c.id === cardId);
    if (indiceOriginal === -1) return;
    const cardRemovido = cards[indiceOriginal];

    setCards(cs => cs.filter(c => c.id !== cardId));

    dispararExclusao(`Card excluído`, {
      commit: () => { api.excluirCard(cardId).catch(err => setErro(err.message)); },
      onUndo: () => {
        setCards(cs => [...cs.slice(0, indiceOriginal), cardRemovido, ...cs.slice(indiceOriginal)]);
      },
    });
  }

  function iniciarEdicao(card) {
    setCardEditando(card.id);
    setEditFrente(card.front);
    setEditVerso(card.back);
  }

  function cancelarEdicao() { setCardEditando(null); }

  async function salvarEdicao(cardId) {
    if (!editFrente.trim() || !editVerso.trim()) return;
    setSalvandoEdit(true);
    try {
      await api.atualizarCard(cardId, editFrente.trim(), editVerso.trim());
      setCardEditando(null);
      await carregarCards();
    } catch (err) { setErro(err.message); }
    finally { setSalvandoEdit(false); }
  }

  // Barra de fases
  const total      = stats ? (stats.new_cards ?? 0) + (stats.validating ?? 0) + (stats.dominated ?? 0) : 0;
  const pctNovo    = total > 0 ? ((stats.new_cards  ?? 0) / total) * 100 : 0;
  const pctValid   = total > 0 ? ((stats.validating ?? 0) / total) * 100 : 0;
  const pctDom     = total > 0 ? ((stats.dominated  ?? 0) / total) * 100 : 0;

  return (
    <div className="pagina">
      <header className="topo">
        <div className="topo-esquerda">
          <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
          <span className="estudo-deck-nome">{deck.title}</span>
        </div>
        <div className="modos-estudo-topo">
          <button className="botao-modo-ghost" onClick={aoRevelar}>Revelar</button>
          <button className="botao-modo-ghost" onClick={aoEstudar}>Estudo clássico</button>
          {stats?.criticos > 0 ? (
            <button className="botao-modo-critico" onClick={aoAprender}>
              🔴 Estudar críticos ({stats.criticos})
            </button>
          ) : stats?.hoje > 0 ? (
            <button className="botao-principal botao-modo-primary" onClick={aoAprender}>
              Estudar hoje ({stats.hoje})
            </button>
          ) : stats && (stats.novos ?? stats.new_cards) === 0 && (stats.dominados ?? stats.dominated) === stats?.total_cards ? (
            <button className="botao-modo-ghost botao-modo-primary" onClick={aoAprender} disabled>
              ✓ Revisão em dia
            </button>
          ) : (
            <button className="botao-principal botao-modo-primary" onClick={aoAprender}>
              Aprender
            </button>
          )}
        </div>
      </header>

      <main className="conteudo cards-v2-main">

        {/* Stats */}
        {stats && (
          <div className="stats-bloco">
            {/* Cards de status prioritários */}
            {(stats.criticos > 0 || stats.hoje > 0) && (
              <div className="status-cards">
                {stats.criticos > 0 && (
                  <div className="status-card critico">
                    <span className="status-card-icone">🔴</span>
                    <div className="status-card-info">
                      <span className="status-card-valor">{stats.criticos}</span>
                      <span className="status-card-label">Crítico{stats.criticos !== 1 ? "s" : ""}</span>
                    </div>
                    <span className="status-card-dica">Revisão atrasada</span>
                  </div>
                )}
                {stats.hoje > 0 && (
                  <div className="status-card hoje">
                    <span className="status-card-icone">📅</span>
                    <div className="status-card-info">
                      <span className="status-card-valor">{stats.hoje}</span>
                      <span className="status-card-label">Para hoje</span>
                    </div>
                    <span className="status-card-dica">Revisão do dia</span>
                  </div>
                )}
              </div>
            )}

            {/* Badges de fase */}
            <div className="stats-deck">
              <div className="stat-badge stat-novo">
                <span className="stat-badge-valor">{stats.novos ?? stats.new_cards}</span>
                <span className="stat-badge-label">Novos</span>
              </div>
              <div className="stat-badge stat-aprendendo">
                <span className="stat-badge-valor">{stats.validando ?? stats.validating ?? 0}</span>
                <span className="stat-badge-label">Validando</span>
              </div>
              <div className="stat-badge stat-dominado">
                <span className="stat-badge-valor">{stats.dominados ?? stats.dominated ?? 0}</span>
                <span className="stat-badge-label">Dominados</span>
              </div>
            </div>

            {/* Barra de fases */}
            {total > 0 && (
              <div className="fases-barra" title={`${Math.round(pctNovo)}% Novos · ${Math.round(pctValid)}% Validando · ${Math.round(pctDom)}% Dominados`}>
                {pctNovo  > 0 && <div className="fases-barra-seg novo"      style={{ width: `${pctNovo}%`  }} />}
                {pctValid > 0 && <div className="fases-barra-seg validando" style={{ width: `${pctValid}%` }} />}
                {pctDom   > 0 && <div className="fases-barra-seg dominado"  style={{ width: `${pctDom}%`   }} />}
              </div>
            )}
          </div>
        )}

        {/* Topo da lista */}
        <div className="cards-lista-topo">
          <span className="cards-contagem">
            {carregando ? "…" : `${cards.length} card${cards.length !== 1 ? "s" : ""}`}
          </span>
          <button className="botao-adicionar-card" onClick={abrirModal}>
            + Adicionar card <kbd>C</kbd>
          </button>
        </div>

        {erro && <p className="erro">{erro}</p>}

        {/* Lista */}
        {carregando ? (
          <div>
            <div className="skeleton skeleton-card" />
            <div className="skeleton skeleton-card" />
            <div className="skeleton skeleton-card" style={{ opacity: 0.6 }} />
          </div>
        ) : cards.length === 0 ? (
          <div className="vazio-bloco">
            <p style={{ fontWeight: 600, marginBottom: "0.35rem" }}>Nenhum card ainda</p>
            <p className="vazio-dica">Clique em "+ Adicionar card" ou pressione <kbd>C</kbd> para começar.</p>
          </div>
        ) : (
          <ul className="lista-cards">
            {cards.map(c =>
              cardEditando === c.id ? (
                <li key={c.id} className="item-card item-card-editando">
                  <div className="item-card-edit-campos">
                    <label className="campo">
                      <span>Frente</span>
                      <textarea value={editFrente} onChange={e => setEditFrente(e.target.value)} rows={2} autoFocus />
                    </label>
                    <label className="campo">
                      <span>Verso</span>
                      <textarea value={editVerso} onChange={e => setEditVerso(e.target.value)} rows={2} />
                    </label>
                  </div>
                  <div className="item-card-edit-acoes">
                    <button className="botao-principal" onClick={() => salvarEdicao(c.id)}
                      disabled={salvandoEdit || !editFrente.trim() || !editVerso.trim()}>
                      {salvandoEdit ? "Salvando…" : "Salvar"}
                    </button>
                    <button className="botao-texto" onClick={cancelarEdicao}>Cancelar</button>
                  </div>
                </li>
              ) : (
                <li key={c.id} className={`item-card item-card--${statusCard(c.repetitions)}`}>
                  <div className="item-card-conteudo">
                    <p className="item-card-frente">{c.front}</p>
                    <p className="item-card-verso">{c.back}</p>
                  </div>
                  <div className="item-card-rodape">
                    <span className={`badge-status badge-status--${statusCard(c.repetitions)}`}>
                      {statusCard(c.repetitions) === "novo" ? "Novo" : statusCard(c.repetitions) === "validando" ? "Validando" : "Dominado"}
                    </span>
                    {c.source === "ai" && <span className="badge-ia">✨ IA</span>}
                    <div className="item-card-acoes">
                      <button className="icone-acao" onClick={() => iniciarEdicao(c)} title="Editar">
                        <IcoPencil />
                      </button>
                      <button className="icone-acao perigo" onClick={() => excluir(c.id)} title="Excluir">
                        <IcoTrash />
                      </button>
                    </div>
                  </div>
                </li>
              )
            )}
          </ul>
        )}
      </main>

      {/* Modal de criação */}
      {modalAberto && (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) fecharModal(); }}>
          <div className="modal-painel">
            <div className="modal-cabecalho">
              <h2 className="modal-titulo">Adicionar cards</h2>
              <button className="modal-fechar" onClick={fecharModal} aria-label="Fechar">×</button>
            </div>

            <div className="abas">
              <button className={abaAtiva === "manual" ? "aba ativa" : "aba"}
                onClick={() => { setAbaAtiva("manual"); setErroIA(""); }}>
                Manualmente
              </button>
              <button className={abaAtiva === "ia" ? "aba ativa" : "aba"}
                onClick={() => { setAbaAtiva("ia"); setErro(""); }}>
                Gerar com IA
              </button>
            </div>

            {abaAtiva === "manual" ? (
              <form className="form-card" onSubmit={criarManual}>
                {erro && <p className="erro">{erro}</p>}
                <label className="campo">
                  <span>Frente (pergunta)</span>
                  <textarea ref={primeiroInputRef} value={frente}
                    onChange={e => setFrente(e.target.value)}
                    placeholder="Ex: Qual é a capital da França?" rows={2} />
                </label>
                <label className="campo">
                  <span>Verso (resposta)</span>
                  <textarea value={verso} onChange={e => setVerso(e.target.value)}
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
                  <span>Material de estudo</span>
                  <textarea ref={primeiroInputRef} value={textoIA}
                    onChange={e => setTextoIA(e.target.value)}
                    placeholder="Cole aqui suas anotações, um trecho do livro, a descrição de um conceito…"
                    rows={7} />
                </label>
                <div className="form-card-rodape">
                  <label className="campo campo-inline">
                    <span>Quantidade</span>
                    <input type="number" min={1} max={30} value={qtdIA}
                      onChange={e => setQtdIA(Number(e.target.value))} />
                  </label>
                  <button className="botao-principal" type="submit"
                    disabled={gerando || !textoIA.trim() || !online}
                    title={online ? undefined : "Precisa de internet — disponível quando a conexão voltar"}>
                    {gerando ? msgIA : "Gerar cards"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      <UndoToasts pendentes={exclusoesPendentes} aoDesfazer={desfazerExclusao} />
    </div>
  );
}

function IcoPencil() {
  return (
    <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M13.586 3.586a2 2 0 112.828 2.828L7 14.828 3 15l.172-4L13.586 3.586z" />
    </svg>
  );
}

function IcoTrash() {
  return (
    <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h14M8 6V4h4v2M5 6l1 11a1 1 0 001 1h6a1 1 0 001-1l1-11" />
    </svg>
  );
}
