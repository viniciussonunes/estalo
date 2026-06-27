import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

/*
  Lógica de fases SM-2:
    Fase 1 (rep == 0 / Novo)       → quality 3  → Fase 2
    Fase 2 (rep == 1 / Validando)  acertou 1ª   → quality 5  → Fase 3
    Fase 2                         errou alguma → NÃO envia  → permanece Fase 2
    Fase 3+ (rep ≥ 2 / Dominado)   acertou 1ª   → quality 5
    Fase 3+                        errou alguma → quality 1  → Fase 1
*/

const LETRAS = ["A", "B", "C", "D"];

function embaralhar(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/** Monta a fila de questões a partir dos cards que já têm quiz pré-gerado. */
function montarFila(cards) {
  return cards
    .filter(c => Array.isArray(c.options) && c.options.length >= 3 && c.explanation)
    .map(card => {
      const todas = embaralhar([card.back, ...card.options.slice(0, 3)]);
      const opts  = todas.map((text, i) => ({ letter: LETRAS[i], text }));
      const correct_letter = LETRAS[todas.indexOf(card.back)];
      return {
        card_id:        card.id,
        question:       card.front,
        options:        opts,
        correct_letter,
        explanation:    card.explanation,
        repetitions:    card.repetitions ?? 0,
      };
    });
}

export default function Aprender({ deck, aoVoltar }) {
  const [fila, setFila]               = useState([]);
  const [totalUnicos, setTotalUnicos] = useState(0);
  const [carregando, setCarregando]   = useState(true);
  const [erro, setErro]               = useState("");
  const [semQuiz, setSemQuiz]         = useState(false);
  const [concluido, setConcluido]     = useState(false);
  const [salvando, setSalvando]       = useState(false);
  const [resposta, setResposta]       = useState(null);

  const errosPorCard      = useRef(new Set());
  const startingReps      = useRef({});
  const questoesOriginais = useRef([]);
  const inicioSessao      = useRef(null);
  const proximoRef        = useRef(null);
  const [acertosNaPrimeira, setAcertosNaPrimeira] = useState(0);
  const [tempoSessao, setTempoSessao] = useState(0);

  function _iniciarComCards(cards) {
    const questoes = montarFila(cards);
    if (questoes.length === 0) { setSemQuiz(true); return; }
    setFila(questoes);
    setTotalUnicos(questoes.length);
    questoesOriginais.current = questoes;
    const repsMap = {};
    questoes.forEach(q => { repsMap[q.card_id] = q.repetitions; });
    startingReps.current = repsMap;
    inicioSessao.current = Date.now();
  }

  useEffect(() => {
    api.listarCards(deck.id)
      .then(_iniciarComCards)
      .catch(err => setErro(err.message))
      .finally(() => setCarregando(false));
  }, [deck.id]);

  const questaoAtual = fila[0] ?? null;
  const respondeu    = resposta !== null;

  // Mantém ref atualizada para o handler de teclado (evita stale closure)
  useEffect(() => { proximoRef.current = proximo; });

  useEffect(() => {
    function onKey(e) {
      if (concluido || semQuiz || carregando) return;
      const atual = fila[0];
      if (!atual) return;
      if (!respondeu && ["1","2","3","4"].includes(e.key)) {
        const opt = atual.options[parseInt(e.key) - 1];
        if (opt) {
          setResposta(opt.letter);
          if (opt.letter !== atual.correct_letter) errosPorCard.current.add(atual.card_id);
        }
      }
      if (respondeu && (e.key === " " || e.key === "Enter")) {
        e.preventDefault();
        proximoRef.current?.();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [concluido, semQuiz, carregando, fila, respondeu]);
  const acertouAtual = respondeu && questaoAtual
    ? resposta === questaoAtual.correct_letter
    : false;

  function escolher(letter) {
    if (respondeu) return;
    setResposta(letter);
    if (letter !== fila[0].correct_letter) {
      errosPorCard.current.add(fila[0].card_id);
    }
  }

  async function proximo() {
    const atual   = fila[0];
    const acertou = resposta === atual.correct_letter;

    if (acertou) {
      const novaFila = fila.slice(1);
      if (!errosPorCard.current.has(atual.card_id)) {
        setAcertosNaPrimeira(n => n + 1);
      }
      if (novaFila.length === 0) {
        setConcluido(true);
        await _salvarProgresso();
      } else {
        setResposta(null);
        setFila(novaFila);
      }
    } else {
      // Errou → reinsere com distância mínima de 2 cards
      setFila(f => {
        const resto = f.slice(1);
        if (resto.length >= 3) {
          return [...resto.slice(0, 2), atual, ...resto.slice(2)];
        }
        return [...resto, atual];
      });
      setResposta(null);
    }
  }

  async function _salvarProgresso() {
    setTempoSessao(Math.floor((Date.now() - (inicioSessao.current ?? Date.now())) / 1000));
    setSalvando(true);
    const chamadas = questoesOriginais.current.map(q => {
      const fase  = startingReps.current[q.card_id] ?? 0;
      const errou = errosPorCard.current.has(q.card_id);
      if (fase === 1 && errou) return Promise.resolve(); // permanece Fase 2
      let quality;
      if (fase === 0)               quality = 3; // Fase 1 → 2
      else if (fase === 1 && !errou) quality = 5; // Fase 2 → 3
      else if (fase >= 2 && !errou)  quality = 5; // Dominado: estende
      else                           quality = 1; // Dominado: volta Fase 1
      return api.responderCard(q.card_id, quality).catch(() => {});
    });
    try { await Promise.all(chamadas); } catch { /* silencioso */ }
    setSalvando(false);
  }

  function reiniciarSessao() {
    errosPorCard.current = new Set();
    startingReps.current = {};
    setAcertosNaPrimeira(0);
    setResposta(null);
    setConcluido(false);
    setCarregando(true);
    api.listarCards(deck.id)
      .then(cards => { _iniciarComCards(cards); })
      .catch(err => setErro(err.message))
      .finally(() => setCarregando(false));
  }

  // ─── Header ────────────────────────────────────────────────────────────
  const cabecalho = (
    <header className="topo">
      <div className="topo-esquerda">
        <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
        <span className="estudo-deck-nome">{deck.title}</span>
      </div>
      <span className="modo-label">Múltipla escolha</span>
    </header>
  );

  if (carregando) {
    return (
      <div className="pagina">{cabecalho}
        <main className="conteudo estudo-centro">
          <p className="vazio">Carregando cards…</p>
        </main>
      </div>
    );
  }

  if (erro) {
    return (
      <div className="pagina">{cabecalho}
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <p className="erro">{erro}</p>
            <button className="botao-principal estudo-concluido-botao" onClick={aoVoltar}>Voltar</button>
          </div>
        </main>
      </div>
    );
  }

  if (semQuiz) {
    return (
      <div className="pagina">{cabecalho}
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <div className="estudo-concluido-icone">✦</div>
            <h2 className="estudo-concluido-titulo">Sem questões disponíveis</h2>
            <p className="estudo-concluido-sub">
              Este deck não tem cards gerados com IA. Vá até a tela de Cards
              e use a aba "Gerar com IA" para criar questões com alternativas.
            </p>
            <button className="botao-principal estudo-concluido-botao" onClick={aoVoltar}>
              Voltar ao deck
            </button>
          </div>
        </main>
      </div>
    );
  }

  // ─── Resultado ─────────────────────────────────────────────────────────
  if (concluido) {
    const pct = totalUnicos > 0
      ? Math.round((acertosNaPrimeira / totalUnicos) * 100) : 0;

    const temCardsEmValidacao = questoesOriginais.current.some(
      q => (startingReps.current[q.card_id] ?? 0) === 0
    );
    const novosDoминados = questoesOriginais.current.filter(
      q => (startingReps.current[q.card_id] ?? 0) === 1
        && !errosPorCard.current.has(q.card_id)
    ).length;
    const avancadosParaValidacao = questoesOriginais.current.filter(
      q => (startingReps.current[q.card_id] ?? 0) === 0
    ).length;

    return (
      <div className="pagina">{cabecalho}
        <main className="conteudo estudo-centro">
          <div className="sessao-resumo">
            <div className="anel-wrapper">
              <AnelProgresso pct={pct} />
            </div>
            <h2 className="sessao-titulo">Sessão concluída!</h2>

            <div className="sessao-stats">
              <div className="sessao-stat">
                <span className="sessao-stat-valor">{acertosNaPrimeira}/{totalUnicos}</span>
                <span className="sessao-stat-label">1ª tentativa</span>
              </div>
              <div className="sessao-stat">
                <span className="sessao-stat-valor">{formatarTempo(tempoSessao)}</span>
                <span className="sessao-stat-label">Tempo</span>
              </div>
              {avancadosParaValidacao > 0 && (
                <div className="sessao-stat ambar">
                  <span className="sessao-stat-valor">+{avancadosParaValidacao}</span>
                  <span className="sessao-stat-label">Validando</span>
                </div>
              )}
              {novosDoминados > 0 && (
                <div className="sessao-stat verde">
                  <span className="sessao-stat-valor">+{novosDoминados}</span>
                  <span className="sessao-stat-label">Dominados</span>
                </div>
              )}
            </div>

            {temCardsEmValidacao ? (
              <div className="gamificado-aviso">
                <p className="gamificado-aviso-titulo">🧠 Seus cards estão em Validação</p>
                <p className="gamificado-aviso-texto">
                  Cientificamente, seu cérebro precisa de um intervalo para consolidar
                  a memória. Fazer uma nova sessão <em>agora</em> acelera a fixação —
                  ou você pode descansar e revisar depois.
                </p>
                <div className="gamificado-botoes">
                  <button className="botao-principal" onClick={reiniciarSessao} disabled={salvando}>
                    Nova sessão agora
                  </button>
                  <button className="botao-texto" onClick={aoVoltar}>Voltar aos decks</button>
                </div>
              </div>
            ) : (
              <button className="botao-principal estudo-concluido-botao"
                onClick={aoVoltar} disabled={salvando}>
                {salvando ? "Salvando…" : "Voltar ao deck"}
              </button>
            )}
          </div>
        </main>
      </div>
    );
  }

  // ─── Questão ───────────────────────────────────────────────────────────
  const cardIdsNaFila   = new Set(fila.map(q => q.card_id));
  const cardsConcluidos = totalUnicos - cardIdsNaFila.size;
  const repeticoes      = fila.length - cardIdsNaFila.size;

  return (
    <div className="pagina">{cabecalho}
      <main className="conteudo estudo-centro">
        <div className="quiz-progresso">
          <span>{cardsConcluidos} de {totalUnicos}</span>
          <div className="quiz-barra">
            <div className="quiz-barra-fill"
              style={{ width: `${(cardsConcluidos / totalUnicos) * 100}%` }} />
          </div>
          {repeticoes > 0 && (
            <span className="quiz-repetindo" title="Aguardando reacerto">+{repeticoes}↺</span>
          )}
        </div>

        <div className="cartao-estudo">
          <div className="cartao-frente">
            <span className="cartao-lado-label">Pergunta</span>
            <p className="cartao-texto">{questaoAtual.question}</p>
          </div>

          <div className="quiz-opcoes">
            {questaoAtual.options.map(op => {
              let extra = "";
              if (respondeu) {
                if (op.letter === questaoAtual.correct_letter) extra = " correta";
                else if (op.letter === resposta)               extra = " errada";
                else                                           extra = " neutra";
              }
              return (
                <button key={op.letter} className={`quiz-opcao${extra}`}
                  onClick={() => escolher(op.letter)} disabled={respondeu}>
                  <span className="quiz-opcao-letra">{op.letter}</span>
                  <span className="quiz-opcao-texto">{op.text}</span>
                  {!respondeu && <kbd className="quiz-kbd">{i + 1}</kbd>}
                </button>
              );
            })}
          </div>

          {respondeu && (
            <div className={`quiz-explicacao ${acertouAtual ? "acertou" : "errou"}`}>
              <p className="quiz-explicacao-status">
                {acertouAtual
                  ? "Correto!"
                  : `Incorreto — a certa é ${questaoAtual.correct_letter}. A questão volta ao final.`}
              </p>
              <p className="quiz-explicacao-texto">{questaoAtual.explanation}</p>
              <button className="botao-principal" onClick={proximo}>
                {acertouAtual && cardsConcluidos + 1 >= totalUnicos
                  ? "Ver resultado" : "Próxima →"}
              </button>
              <span className="revelar-kbd"><kbd>Space</kbd> / <kbd>Enter</kbd> para avançar</span>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function formatarTempo(seg) {
  const m = Math.floor(seg / 60);
  const s = seg % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2,"0")}s` : `${s}s`;
}

function AnelProgresso({ pct }) {
  const r = 42;
  const circ = 2 * Math.PI * r;
  const fill = Math.min(pct / 100, 1) * circ;
  const cor = pct >= 80 ? "#16a34a" : pct >= 50 ? "#f59e0b" : "#5c54e8";
  return (
    <svg className="anel-svg" viewBox="0 0 100 100" width="130" height="130">
      <circle cx="50" cy="50" r={r} fill="none" stroke="#e5e3ee" strokeWidth="9" />
      <circle cx="50" cy="50" r={r} fill="none" stroke={cor} strokeWidth="9"
        strokeDasharray={`${fill} ${circ}`} strokeLinecap="round"
        transform="rotate(-90 50 50)"
        style={{ transition: "stroke-dasharray 0.9s cubic-bezier(.4,0,.2,1)" }}
      />
      <text x="50" y="47" textAnchor="middle" fontSize="19" fontWeight="700"
        fill="#17161f" fontFamily="Fraunces, serif">
        {Math.round(pct)}%
      </text>
      <text x="50" y="61" textAnchor="middle" fontSize="9" fill="#56535f">
        precisão
      </text>
    </svg>
  );
}
