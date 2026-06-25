import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

/*
  Lógica de fases SM-2 para o Modo Aprender:

  Fase 1 (repetitions == 0 / Novo)
    → Resultado de qualquer sessão: avança para Fase 2 (quality 3)

  Fase 2 (repetitions == 1 / Em Validação)
    → Acertou na PRIMEIRA tentativa: avança para Fase 3 / Dominado (quality 5)
    → Errou ao menos uma vez:        permanece na Fase 2 (não envia answer)

  Fase 3+ (repetitions >= 2 / Dominado)
    → Acertou na primeira: quality 5 (estende intervalo)
    → Errou ao menos uma vez: quality 1 (volta para Fase 1)
*/

export default function Aprender({ deck, aoVoltar }) {
  const [fila, setFila]               = useState([]);  // questões restantes
  const [totalUnicos, setTotalUnicos] = useState(0);
  const [carregando, setCarregando]   = useState(true);
  const [erro, setErro]               = useState("");
  const [concluido, setConcluido]     = useState(false);
  const [salvando, setSalvando]       = useState(false);

  // Estado da questão atual
  const [resposta, setResposta]       = useState(null); // letra escolhida

  // Tracking de sessão
  const errosPorCard    = useRef(new Set());  // card_ids que erraram ao menos uma vez
  const startingReps    = useRef({});         // card_id → repetitions ao INÍCIO da sessão
  const questoesOriginais = useRef([]);

  const [acertosNaPrimeira, setAcertosNaPrimeira] = useState(0);
  const [cartasConcluidas, setCartasConcluidas]   = useState(0);

  useEffect(() => {
    api.gerarQuiz(deck.id)
      .then((qs) => {
        setFila(qs);
        setTotalUnicos(qs.length);
        questoesOriginais.current = qs;
        // Guarda a fase inicial de cada card
        const repsMap = {};
        qs.forEach(q => { repsMap[q.card_id] = q.repetitions ?? 0; });
        startingReps.current = repsMap;
      })
      .catch((err) => setErro(err.message))
      .finally(() => setCarregando(false));
  }, [deck.id]);

  const questaoAtual = fila[0] ?? null;
  const respondeu    = resposta !== null;
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

    let novaFila;
    if (acertou) {
      novaFila = fila.slice(1);
      if (!errosPorCard.current.has(atual.card_id)) {
        setAcertosNaPrimeira(n => n + 1);
      }
      setCartasConcluidas(n => n + 1);
    } else {
      // Errou: volta para o final da fila
      novaFila = [...fila.slice(1), atual];
    }

    setResposta(null);

    if (novaFila.length === 0) {
      await _salvarProgresso();
      setConcluido(true);
    } else {
      setFila(novaFila);
    }
  }

  async function _salvarProgresso() {
    setSalvando(true);
    const chamadas = questoesOriginais.current.map(q => {
      const fase     = startingReps.current[q.card_id] ?? 0;
      const errou    = errosPorCard.current.has(q.card_id);

      // Fase 2 + errou → não envia (mantém repetitions == 1 = Fase 2)
      if (fase === 1 && errou) return Promise.resolve();

      let quality;
      if (fase === 0) {
        quality = 3;  // Fase 1 → Fase 2 (independente de erros)
      } else if (fase === 1 && !errou) {
        quality = 5;  // Fase 2 + primeira tentativa → Fase 3 (Dominado)
      } else if (fase >= 2 && !errou) {
        quality = 5;  // Dominado + primeira → estende intervalo
      } else {
        quality = 1;  // Dominado + errou → volta para Fase 1
      }
      return api.responderCard(q.card_id, quality).catch(() => {});
    });

    try { await Promise.all(chamadas); } catch { /* silencioso */ }
    setSalvando(false);
  }

  function reiniciarSessao() {
    // Reseta tudo e recarrega o quiz
    errosPorCard.current = new Set();
    startingReps.current = {};
    setAcertosNaPrimeira(0);
    setCartasConcluidas(0);
    setResposta(null);
    setConcluido(false);
    setCarregando(true);
    api.gerarQuiz(deck.id)
      .then((qs) => {
        setFila(qs);
        setTotalUnicos(qs.length);
        questoesOriginais.current = qs;
        const repsMap = {};
        qs.forEach(q => { repsMap[q.card_id] = q.repetitions ?? 0; });
        startingReps.current = repsMap;
      })
      .catch((err) => setErro(err.message))
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

  // ─── Carregando ────────────────────────────────────────────────────────
  if (carregando) {
    return (
      <div className="pagina">
        {cabecalho}
        <main className="conteudo estudo-centro">
          <div className="ia-carregando">
            <div className="ia-carregando-icone">✦</div>
            <p className="ia-carregando-msg">A IA está preparando suas questões…</p>
            <p className="ia-carregando-sub">Isso pode levar alguns segundos</p>
          </div>
        </main>
      </div>
    );
  }

  // ─── Erro ──────────────────────────────────────────────────────────────
  if (erro) {
    return (
      <div className="pagina">
        {cabecalho}
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <p className="erro">{erro}</p>
            <button className="botao-principal estudo-concluido-botao" onClick={aoVoltar}>
              Voltar
            </button>
          </div>
        </main>
      </div>
    );
  }

  // ─── Tela de resultado ─────────────────────────────────────────────────
  if (concluido) {
    const pct = totalUnicos > 0
      ? Math.round((acertosNaPrimeira / totalUnicos) * 100)
      : 0;

    // Detecta se há cards que subiram para Fase 2 (precisam de nova sessão)
    const temCardsEmValidacao = questoesOriginais.current.some(
      q => (startingReps.current[q.card_id] ?? 0) === 0   // era Fase 1
    );
    // Cards que subiram para Dominado (eram Fase 2 + acertaram de primeira)
    const novosDoминados = questoesOriginais.current.filter(
      q => (startingReps.current[q.card_id] ?? 0) === 1
        && !errosPorCard.current.has(q.card_id)
    ).length;

    return (
      <div className="pagina">
        {cabecalho}
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <div className="estudo-concluido-icone">
              {pct >= 80 ? "★" : pct >= 50 ? "✓" : "↺"}
            </div>
            <h2 className="estudo-concluido-titulo">Sessão concluída!</h2>

            <p className="quiz-resultado-placar">
              {acertosNaPrimeira}/{totalUnicos} na primeira tentativa — {pct}%
            </p>

            {novosDoминados > 0 && (
              <p className="resultado-badge dominado">
                🏆 {novosDoминados} card{novosDoминados > 1 ? "s" : ""} dominado{novosDoминados > 1 ? "s" : ""}!
              </p>
            )}

            {temCardsEmValidacao && (
              <div className="gamificado-aviso">
                <p className="gamificado-aviso-titulo">🧠 Seus cards estão em Validação</p>
                <p className="gamificado-aviso-texto">
                  Cientificamente, seu cérebro precisa de um intervalo para consolidar
                  a memória. Fazer uma nova sessão <em>agora</em> acelera a fixação —
                  ou você pode descansar e revisar depois.
                </p>
                <div className="gamificado-botoes">
                  <button
                    className="botao-principal"
                    onClick={reiniciarSessao}
                    disabled={salvando}
                  >
                    Nova sessão agora
                  </button>
                  <button className="botao-texto" onClick={aoVoltar}>
                    Voltar aos decks
                  </button>
                </div>
              </div>
            )}

            {!temCardsEmValidacao && (
              <button
                className="botao-principal estudo-concluido-botao"
                onClick={aoVoltar}
                disabled={salvando}
              >
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
    <div className="pagina">
      {cabecalho}
      <main className="conteudo estudo-centro">
        <div className="quiz-progresso">
          <span>{cardsConcluidos} de {totalUnicos}</span>
          <div className="quiz-barra">
            <div
              className="quiz-barra-fill"
              style={{ width: `${(cardsConcluidos / totalUnicos) * 100}%` }}
            />
          </div>
          {repeticoes > 0 && (
            <span className="quiz-repetindo" title="Questões aguardando reacerto">
              +{repeticoes}↺
            </span>
          )}
        </div>

        <div className="cartao-estudo">
          <div className="cartao-frente">
            <span className="cartao-lado-label">Pergunta</span>
            <p className="cartao-texto">{questaoAtual.question}</p>
          </div>

          <div className="quiz-opcoes">
            {questaoAtual.options.map((op) => {
              let extra = "";
              if (respondeu) {
                if (op.letter === questaoAtual.correct_letter) extra = " correta";
                else if (op.letter === resposta) extra = " errada";
                else extra = " neutra";
              }
              return (
                <button
                  key={op.letter}
                  className={`quiz-opcao${extra}`}
                  onClick={() => escolher(op.letter)}
                  disabled={respondeu}
                >
                  <span className="quiz-opcao-letra">{op.letter}</span>
                  <span className="quiz-opcao-texto">{op.text}</span>
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
                  ? "Ver resultado"
                  : "Próxima →"}
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
