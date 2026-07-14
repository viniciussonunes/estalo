import { useState, useEffect, useCallback } from "react";
import { api } from "../api.js";

// quality "Acertei" sem nuance -- 4 é neutro pro ease_factor do SM-2 (nem
// sobe nem desce, ver services/sm2.py), o default mais honesto quando não
// temos sinal de o quão fácil foi o acerto.
const QUALITY_ACERTEI = 4;

// "Errei" sem feedback pedido -- mesmo valor que o antigo botão "Errei"
// sempre usou.
const QUALITY_ERREI_PADRAO = 1;

// Quando existe feedback da IA, refina o quality de "Errei" pela
// classificação -- sempre dentro da faixa "errou" (<3, reseta reps/
// interval igual, ver sm2.py), só varia o tamanho da queda do
// ease_factor conforme a gravidade. Nunca promove um "Errei" auto-
// reportado pra faixa de "acertou" (>=3) -- respeitar a autoavaliação
// do usuário importa mais que a nuance da IA.
const QUALITY_POR_TIPO_ERRO = {
  omissao: 2,          // faltou um detalhe -- queda leve
  imprecisao: 1,        // mesmo peso do "Errei" padrão
  erro_conceitual: 0,   // entendimento fundamentalmente errado -- queda forte
};

// Linha de abertura em linguagem natural pro feedback -- em vez de expor
// a categoria crua (omissao/imprecisao/erro_conceitual) pro usuário, só a
// telemetria do backend vê o valor técnico (ver routers/cards.py).
const TIPO_ERRO_MENSAGEM = {
  omissao: "Quase lá — faltou só uma parte.",
  imprecisao: "No caminho certo, mas vale afinar.",
  erro_conceitual: "Vale revisitar esse conceito com calma.",
};

export default function Estudo({ deck, aoVoltar }) {
  const [card, setCard] = useState(undefined); // undefined = ainda carregando, null = sessão concluída
  const [virado, setVirado] = useState(false);
  const [stats, setStats] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  // Mentoria Ativa: tentativa é sempre OPCIONAL e digitada ANTES de
  // revelar (evita o viés de "eu sabia" que flashcard tradicional tem).
  // Trava (read-only) assim que revela -- editar depois de ver a
  // resposta certa contaminaria tanto o registro quanto a análise da IA.
  // Pedir feedback é uma ação à parte -- só 2 notas na tela (Acertei/
  // Errei), mas quando existe feedback, a classificação da IA
  // (omissão/imprecisão/erro conceitual) refina o quality de "Errei" por
  // baixo dos panos (ver QUALITY_POR_TIPO_ERRO/qualityErrei abaixo) sem o
  // usuário precisar entender SM-2 pra se beneficiar da precisão. Tudo
  // reseta a cada card novo (ver carregarProximo).
  const [tentativa, setTentativa] = useState("");
  const [analisando, setAnalisando] = useState(false);
  const [erroAnalise, setErroAnalise] = useState("");
  const [feedback, setFeedback] = useState(null); // { explanation, tipo_erro, gap_cognitivo }

  const carregarProximo = useCallback(async () => {
    setErro("");
    setVirado(false);
    setTentativa("");
    setErroAnalise("");
    setFeedback(null);
    try {
      const [proximo, novasStats] = await Promise.all([
        api.proximoCard(deck.id),
        api.statsEstudo(deck.id),
      ]);
      // O backend nunca devolve null de verdade — sempre um objeto truthy
      // (StudyCard ou SessaoConcluida). motivo só existe em SessaoConcluida,
      // por isso é o jeito certo de detectar "fila vazia".
      setCard(proximo?.motivo ? null : proximo);
      setStats(novasStats);
    } catch (err) {
      setErro(err.message);
    } finally {
      setCarregando(false);
    }
  }, [deck.id]);

  useEffect(() => {
    carregarProximo();
  }, [carregarProximo]);

  async function responder(quality) {
    if (enviando || analisando) return;
    setEnviando(true);
    setErro("");
    try {
      await api.responderCard(card.card_id, quality);
      await carregarProximo();
    } catch (err) {
      setErro(err.message);
    } finally {
      setEnviando(false);
    }
  }

  function qualityErrei() {
    return feedback?.tipo_erro !== undefined && feedback.tipo_erro in QUALITY_POR_TIPO_ERRO
      ? QUALITY_POR_TIPO_ERRO[feedback.tipo_erro]
      : QUALITY_ERREI_PADRAO;
  }

  async function pedirFeedback() {
    if (!tentativa.trim() || analisando) return;
    setAnalisando(true);
    setErroAnalise("");
    try {
      const resp = await api.analisarFeedback(card.card_id, tentativa.trim());
      setFeedback(resp);
    } catch (err) {
      setErroAnalise(err.message);
    } finally {
      setAnalisando(false);
    }
  }

  // Tela de carregamento inicial
  if (carregando) {
    return (
      <div className="pagina">
        <CabecalhoEstudo deck={deck} stats={null} aoVoltar={aoVoltar} />
        <main className="conteudo estudo-centro">
          <p className="vazio">Carregando…</p>
        </main>
      </div>
    );
  }

  // Sessão concluída
  if (card === null) {
    return (
      <div className="pagina">
        <CabecalhoEstudo deck={deck} stats={stats} aoVoltar={aoVoltar} />
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <div className="estudo-concluido-icone">✓</div>
            <h2 className="estudo-concluido-titulo">Tudo revisado por hoje!</h2>
            <p className="estudo-concluido-sub">
              Volte amanhã para a próxima rodada.
            </p>
            <button className="botao-principal estudo-concluido-botao" onClick={aoVoltar}>
              Voltar ao painel
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="pagina">
      <CabecalhoEstudo deck={deck} stats={stats} aoVoltar={aoVoltar} />
      <main className="conteudo estudo-centro">
        {erro && <p className="erro">{erro}</p>}

        <div className="cartao-estudo">
          <div className="cartao-frente">
            <span className="cartao-lado-label">Pergunta</span>
            <p className="cartao-texto">{card.front}</p>
          </div>

          {!virado ? (
            <>
              <label className="campo">
                <span>Sua tentativa de resposta (opcional)</span>
                <div className="errei-input-linha">
                  <textarea
                    value={tentativa}
                    onChange={(e) => setTentativa(e.target.value)}
                    placeholder="O que você responderia?"
                    rows={3}
                  />
                  <button
                    type="button"
                    className="errei-mic-botao"
                    disabled
                    title="Transcrição por voz em breve"
                  >
                    🎙️
                  </button>
                </div>
              </label>
              <button
                className="botao-principal botao-mostrar"
                onClick={() => setVirado(true)}
              >
                Revelar resposta
              </button>
            </>
          ) : (
            <>
              <div className="cartao-divisor" />

              {tentativa.trim() && (
                <div className="revelar-explicacao">
                  <span className="cartao-lado-label">Sua tentativa</span>
                  <p className="revelar-explicacao-texto">{tentativa}</p>
                </div>
              )}

              <div className="cartao-verso">
                <span className="cartao-lado-label">Resposta</span>
                <p className="cartao-texto">{card.back}</p>
              </div>

              {tentativa.trim() && !feedback && (
                <button
                  type="button"
                  className="botao-texto tutor-botao"
                  onClick={pedirFeedback}
                  disabled={analisando}
                >
                  {analisando ? "Analisando…" : "🔍 Pedir feedback da IA"}
                </button>
              )}
              {erroAnalise && <p className="tutor-status tutor-status-erro">{erroAnalise}</p>}
              {feedback && (
                <div className="revelar-explicacao">
                  <span className="cartao-lado-label">Tutor</span>
                  {feedback.tipo_erro && TIPO_ERRO_MENSAGEM[feedback.tipo_erro] && (
                    <p className="revelar-explicacao-resumo">{TIPO_ERRO_MENSAGEM[feedback.tipo_erro]}</p>
                  )}
                  <p className="revelar-explicacao-texto">{feedback.explanation}</p>
                </div>
              )}

              <div className="notas">
                <button
                  className="nota nota-errei"
                  onClick={() => responder(qualityErrei())}
                  disabled={enviando || analisando}
                >
                  Errei
                </button>
                <button
                  className="nota nota-bom"
                  onClick={() => responder(QUALITY_ACERTEI)}
                  disabled={enviando || analisando}
                >
                  Acertei
                </button>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function CabecalhoEstudo({ deck, stats, aoVoltar }) {
  return (
    <header className="topo">
      <div className="topo-esquerda">
        <button className="botao-texto" onClick={aoVoltar}>
          ← Voltar
        </button>
        <span className="estudo-deck-nome">{deck.title}</span>
      </div>
      {stats !== null && (
        <span className="estudo-contador">
          {stats.due_now > 0
            ? `${stats.due_now} card${stats.due_now > 1 ? "s" : ""} pra revisar`
            : "Em dia!"}
        </span>
      )}
    </header>
  );
}
