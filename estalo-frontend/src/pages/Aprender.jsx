import { useState, useEffect } from "react";
import { api } from "../api.js";

export default function Aprender({ deck, aoVoltar }) {
  const [questoes, setQuestoes] = useState([]);
  const [indice, setIndice] = useState(0);
  const [resposta, setResposta] = useState(null); // letra escolhida, ou null
  const [acertos, setAcertos] = useState(0);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [concluido, setConcluido] = useState(false);

  useEffect(() => {
    api.gerarQuiz(deck.id)
      .then(setQuestoes)
      .catch((err) => setErro(err.message))
      .finally(() => setCarregando(false));
  }, [deck.id]);

  const questaoAtual = questoes[indice];

  function escolher(letter) {
    if (resposta !== null) return;
    setResposta(letter);
    if (letter === questaoAtual.correct_letter) {
      setAcertos((a) => a + 1);
    }
  }

  function proximo() {
    if (indice + 1 >= questoes.length) {
      setConcluido(true);
    } else {
      setIndice((i) => i + 1);
      setResposta(null);
    }
  }

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

  if (concluido) {
    const pct = Math.round((acertos / questoes.length) * 100);
    return (
      <div className="pagina">
        {cabecalho}
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <div className="estudo-concluido-icone">{pct >= 70 ? "★" : "✓"}</div>
            <h2 className="estudo-concluido-titulo">Quiz concluído!</h2>
            <p className="quiz-resultado-placar">
              {acertos} de {questoes.length} corretas — {pct}%
            </p>
            <button className="botao-principal estudo-concluido-botao" onClick={aoVoltar}>
              Voltar ao deck
            </button>
          </div>
        </main>
      </div>
    );
  }

  const respondeu = resposta !== null;
  const acertou = resposta === questaoAtual.correct_letter;

  return (
    <div className="pagina">
      {cabecalho}
      <main className="conteudo estudo-centro">
        <div className="quiz-progresso">
          <span>{indice + 1} de {questoes.length}</span>
          <div className="quiz-barra">
            <div
              className="quiz-barra-fill"
              style={{ width: `${((indice + 1) / questoes.length) * 100}%` }}
            />
          </div>
          <span className="quiz-acertos">{acertos} corretas</span>
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
            <div className={`quiz-explicacao ${acertou ? "acertou" : "errou"}`}>
              <p className="quiz-explicacao-status">
                {acertou
                  ? "Correto!"
                  : `Incorreto — a resposta certa é ${questaoAtual.correct_letter}`}
              </p>
              <p className="quiz-explicacao-texto">{questaoAtual.explanation}</p>
              <button className="botao-principal" onClick={proximo}>
                {indice + 1 < questoes.length ? "Próxima →" : "Ver resultado"}
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
