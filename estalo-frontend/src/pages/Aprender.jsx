import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

export default function Aprender({ deck, aoVoltar }) {
  const [fila, setFila]     = useState([]);   // questões ainda a responder
  const [totalUnicos, setTotalUnicos] = useState(0);
  const [carregando, setCarregando]   = useState(true);
  const [erro, setErro]               = useState("");

  // Estado da questão atual
  const [resposta, setResposta]       = useState(null); // letra escolhida
  const [concluido, setConcluido]     = useState(false);

  // Tracking para SM-2 e placar
  const errosPorCard = useRef(new Set());   // card_ids que erraram ao menos uma vez
  const [acertosNaPrimeira, setAcertosNaPrimeira] = useState(0);

  // Salvar progresso no backend ao final
  const [salvando, setSalvando]       = useState(false);
  const questoesOriginais = useRef([]); // todos os card_ids da sessão

  useEffect(() => {
    api.gerarQuiz(deck.id)
      .then((qs) => {
        setFila(qs);
        setTotalUnicos(qs.length);
        questoesOriginais.current = qs;
      })
      .catch((err) => setErro(err.message))
      .finally(() => setCarregando(false));
  }, [deck.id]);

  const questaoAtual = fila[0] ?? null;
  const respondeu    = resposta !== null;
  const acertouAtual = respondeu && questaoAtual && resposta === questaoAtual.correct_letter;

  // Quantos cards únicos já foram respondidos corretamente
  const concluidos = totalUnicos - new Set(fila.map(q => q.card_id)).size
    + (questaoAtual && !respondeu ? 0 : 0);
  // Simpler: track separately
  const [cartasCorretas, setCartasCorretas] = useState(0);

  function escolher(letter) {
    if (respondeu) return;
    setResposta(letter);
    const atual = fila[0];
    const acertou = letter === atual.correct_letter;
    if (!acertou) {
      errosPorCard.current.add(atual.card_id);
    }
  }

  async function proximo() {
    const atual = fila[0];
    const acertou = resposta === atual.correct_letter;

    let novaFila;
    if (acertou) {
      // Remove da fila — card concluído
      novaFila = fila.slice(1);
      if (!errosPorCard.current.has(atual.card_id)) {
        setAcertosNaPrimeira(n => n + 1);
      }
      setCartasCorretas(n => n + 1);
    } else {
      // Errou: move para o final da fila
      novaFila = [...fila.slice(1), atual];
    }

    setResposta(null);

    if (novaFila.length === 0) {
      // Sessão concluída — salva progresso no backend
      setSalvando(true);
      try {
        await Promise.all(
          questoesOriginais.current.map(q =>
            api.responderCard(q.card_id, errosPorCard.current.has(q.card_id) ? 1 : 4)
          )
        );
      } catch {
        // Progresso pode não ter salvo, mas não bloqueia a tela de resultado
      } finally {
        setSalvando(false);
      }
      setConcluido(true);
    } else {
      setFila(novaFila);
    }
  }

  // ─── Cabeçalho ───────────────────────────────────────────────────────────
  const cabecalho = (
    <header className="topo">
      <div className="topo-esquerda">
        <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
        <span className="estudo-deck-nome">{deck.title}</span>
      </div>
      <span className="modo-label">Múltipla escolha</span>
    </header>
  );

  // ─── Estados de carregamento/erro ────────────────────────────────────────
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

  // ─── Tela de resultado ───────────────────────────────────────────────────
  if (concluido) {
    const pct = Math.round((acertosNaPrimeira / totalUnicos) * 100);
    return (
      <div className="pagina">
        {cabecalho}
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <div className="estudo-concluido-icone">{pct >= 70 ? "★" : "✓"}</div>
            <h2 className="estudo-concluido-titulo">Quiz concluído!</h2>
            <p className="quiz-resultado-placar">
              {acertosNaPrimeira} de {totalUnicos} na primeira tentativa — {pct}%
            </p>
            <p className="estudo-concluido-sub">
              {salvando
                ? "Salvando progresso…"
                : "Progresso salvo no seu histórico de revisão."}
            </p>
            <button className="botao-principal estudo-concluido-botao" onClick={aoVoltar}>
              Voltar ao deck
            </button>
          </div>
        </main>
      </div>
    );
  }

  // ─── Questão atual ───────────────────────────────────────────────────────
  // Progresso: quantos card_ids únicos ainda estão na fila
  const cardIdsNaFila  = new Set(fila.map(q => q.card_id));
  const cardsConcluidos = totalUnicos - cardIdsNaFila.size;
  const perguntasNaFila = fila.length; // pode ser > totalUnicos por causa das repetições

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
          {perguntasNaFila > (totalUnicos - cardsConcluidos) && (
            <span className="quiz-repetindo" title="Questões repetidas por erro">
              +{perguntasNaFila - (totalUnicos - cardsConcluidos)} repetição
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
                  : `Incorreto — a resposta certa é ${questaoAtual.correct_letter}. A questão voltará.`}
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
