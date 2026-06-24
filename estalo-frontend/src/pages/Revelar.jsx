import { useState, useEffect } from "react";
import { api } from "../api.js";

export default function Revelar({ deck, aoVoltar }) {
  const [cards, setCards] = useState([]);
  const [indice, setIndice] = useState(0);
  const [revelado, setRevelado] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");

  useEffect(() => {
    api.gerarRevelar(deck.id)
      .then(setCards)
      .catch((err) => setErro(err.message))
      .finally(() => setCarregando(false));
  }, [deck.id]);

  function proximo() {
    setIndice((i) => i + 1);
    setRevelado(false);
  }

  const cabecalho = (
    <header className="topo">
      <div className="topo-esquerda">
        <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
        <span className="estudo-deck-nome">{deck.title}</span>
      </div>
      <span className="modo-label">Revelar cards</span>
    </header>
  );

  if (carregando) {
    return (
      <div className="pagina">
        {cabecalho}
        <main className="conteudo estudo-centro">
          <div className="ia-carregando">
            <div className="ia-carregando-icone">✦</div>
            <p className="ia-carregando-msg">A IA está preparando as explicações…</p>
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

  if (indice >= cards.length) {
    return (
      <div className="pagina">
        {cabecalho}
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <div className="estudo-concluido-icone">✓</div>
            <h2 className="estudo-concluido-titulo">Todos os cards revisados!</h2>
            <p className="estudo-concluido-sub">
              Você passou por {cards.length} card{cards.length !== 1 ? "s" : ""}.
            </p>
            <button className="botao-principal estudo-concluido-botao" onClick={aoVoltar}>
              Voltar ao deck
            </button>
          </div>
        </main>
      </div>
    );
  }

  const card = cards[indice];

  return (
    <div className="pagina">
      {cabecalho}
      <main className="conteudo estudo-centro">
        <div className="quiz-progresso">
          <span>{indice + 1} de {cards.length}</span>
          <div className="quiz-barra">
            <div
              className="quiz-barra-fill"
              style={{ width: `${((indice + 1) / cards.length) * 100}%` }}
            />
          </div>
        </div>

        <div className="cartao-estudo">
          <div className="cartao-frente">
            <span className="cartao-lado-label">Conceito</span>
            <p className="cartao-texto">{card.front}</p>
          </div>

          {!revelado ? (
            <button
              className="botao-principal botao-mostrar"
              onClick={() => setRevelado(true)}
            >
              Revelar resposta
            </button>
          ) : (
            <>
              <div className="cartao-divisor" />
              <div className="cartao-verso">
                <span className="cartao-lado-label">Resposta</span>
                <p className="cartao-texto">{card.back}</p>
              </div>

              {card.explanation && (
                <div className="revelar-explicacao">
                  <span className="cartao-lado-label">Explicação</span>
                  <p className="revelar-explicacao-texto">{card.explanation}</p>
                </div>
              )}

              <button className="botao-principal" onClick={proximo}>
                {indice + 1 < cards.length ? "Próximo →" : "Concluir"}
              </button>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
