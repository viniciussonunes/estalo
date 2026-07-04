import { useState, useEffect, useCallback } from "react";
import { api } from "../api.js";

const NOTAS = [
  { label: "Errei",   quality: 1, classe: "nota-errei"   },
  { label: "Difícil", quality: 3, classe: "nota-dificil" },
  { label: "Bom",     quality: 4, classe: "nota-bom"     },
  { label: "Fácil",   quality: 5, classe: "nota-facil"   },
];

export default function Estudo({ deck, aoVoltar }) {
  const [card, setCard] = useState(undefined); // undefined = ainda carregando, null = sessão concluída
  const [virado, setVirado] = useState(false);
  const [stats, setStats] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  const carregarProximo = useCallback(async () => {
    setErro("");
    setVirado(false);
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
    if (enviando) return;
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
            <button
              className="botao-principal botao-mostrar"
              onClick={() => setVirado(true)}
            >
              Mostrar resposta
            </button>
          ) : (
            <>
              <div className="cartao-divisor" />
              <div className="cartao-verso">
                <span className="cartao-lado-label">Resposta</span>
                <p className="cartao-texto">{card.back}</p>
              </div>

              <div className="notas">
                {NOTAS.map(({ label, quality, classe }) => (
                  <button
                    key={quality}
                    className={`nota ${classe}`}
                    onClick={() => responder(quality)}
                    disabled={enviando}
                  >
                    {label}
                  </button>
                ))}
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
