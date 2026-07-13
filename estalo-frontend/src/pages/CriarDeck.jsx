import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

const MSGS_IA = [
  "Lendo o texto fornecido...",
  "Decompondo conceitos essenciais...",
  "Criando alternativas falsas inteligentes...",
  "Finalizando a formatação dos cards...",
];

const MSGS_LEITURA = [
  "Lendo o texto...",
  "Identificando o vocabulário que mais trava a leitura...",
  "Montando questões de contexto...",
  "Preparando sua sessão de treino...",
];

const NIVEIS_CEFR = [
  { valor: "A1", label: "A1 — Iniciante" },
  { valor: "A2", label: "A2 — Básico" },
  { valor: "B1", label: "B1 — Intermediário" },
  { valor: "B2", label: "B2 — Intermediário avançado" },
  { valor: "C1", label: "C1 — Avançado" },
  { valor: "C2", label: "C2 — Proficiente" },
];

const IDIOMAS_RESPOSTA = [
  { valor: "pt", label: "Português" },
  { valor: "en", label: "Inglês" },
];

const LIMITE_TEXTO_LEITURA = 12_000;

export default function CriarDeck({ pastaId, aoVoltar, aoVerCards }) {
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");

  // Modo de Estudo: 'flashcards' (fluxo original, intocado) ou 'ingles'
  // (Leitura em Inglês) — dois motores de conteúdo isolados só na forma
  // de gerar (prompts diferentes em ai.py); o resultado dos dois é
  // sempre um Card comum, salvo do mesmo jeito, revisável no mesmo
  // Modo Aprender.
  const [modoEstudo, setModoEstudo] = useState("flashcards");

  const [modo, setModo] = useState("manual"); // "manual" | "ia" (dentro de Flashcards)

  // Modo manual: linhas dinâmicas
  const [linhas, setLinhas] = useState([{ frente: "", verso: "" }]);

  // Modo IA (flashcards genéricos)
  const [textoIA, setTextoIA] = useState("");
  const [qtdIA, setQtdIA] = useState(5);

  // Leitura em Inglês
  const [textoLeitura, setTextoLeitura] = useState("");
  const [nivelLeitura, setNivelLeitura] = useState("B1");
  const [idiomaResposta, setIdiomaResposta] = useState("pt");
  const [qtdLeitura, setQtdLeitura] = useState(10);

  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [msgIA, setMsgIA] = useState(MSGS_IA[0]);
  const msgIAIdx = useRef(0);

  const gerandoPorIA = modoEstudo === "ingles" || modo === "ia";

  useEffect(() => {
    if (!salvando || !gerandoPorIA) return;
    const msgs = modoEstudo === "ingles" ? MSGS_LEITURA : MSGS_IA;
    setMsgIA(msgs[0]);
    msgIAIdx.current = 0;
    const id = setInterval(() => {
      msgIAIdx.current = (msgIAIdx.current + 1) % msgs.length;
      setMsgIA(msgs[msgIAIdx.current]);
    }, 2500);
    return () => clearInterval(id);
  }, [salvando, modoEstudo, gerandoPorIA]);

  function addLinha() {
    setLinhas(l => [...l, { frente: "", verso: "" }]);
  }

  function removeLinha(i) {
    if (linhas.length === 1) return;
    setLinhas(l => l.filter((_, idx) => idx !== i));
  }

  function updateLinha(i, campo, valor) {
    setLinhas(l => l.map((linha, idx) => idx === i ? { ...linha, [campo]: valor } : linha));
  }

  async function criar(e) {
    e.preventDefault();
    if (!nome.trim()) return;
    setSalvando(true);
    setErro("");
    try {
      const deck = await api.criarDeck(nome.trim(), descricao.trim() || null, pastaId);

      if (modoEstudo === "ingles") {
        if (textoLeitura.trim()) {
          await api.gerarCardsIA(deck.id, textoLeitura.trim(), qtdLeitura, {
            languageLevel: nivelLeitura,
            answerLanguage: idiomaResposta,
          });
        }
      } else if (modo === "manual") {
        const validos = linhas.filter(l => l.frente.trim() && l.verso.trim());
        for (const l of validos) {
          await api.criarCard(deck.id, l.frente.trim(), l.verso.trim());
        }
      } else if (modo === "ia" && textoIA.trim()) {
        await api.gerarCardsIA(deck.id, textoIA.trim(), qtdIA);
      }

      aoVerCards(deck);
    } catch (err) {
      setErro(err.message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="pagina">
      <header className="topo">
        <div className="topo-esquerda">
          <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
          <span className="estudo-deck-nome">Novo deck</span>
        </div>
      </header>

      <main className="conteudo">
        <h1 className="titulo-pagina">Criar deck</h1>

        <form onSubmit={criar}>
          {/* Info do deck */}
          <div className="criar-deck-info">
            <label className="campo">
              <span>Nome do deck *</span>
              <input
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Ex: SC-900 Fundamentos"
                required
                autoFocus
              />
            </label>
            <label className="campo">
              <span>Descrição (opcional)</span>
              <input
                value={descricao}
                onChange={(e) => setDescricao(e.target.value)}
                placeholder="Ex: Conceitos de segurança e identidade Microsoft"
              />
            </label>
          </div>

          {/* Modo de Estudo */}
          <div className="modo-estudo-selector">
            <span className="modo-estudo-label">Modo de estudo</span>
            <div className="abas abas-modo-estudo">
              <button
                type="button"
                className={modoEstudo === "flashcards" ? "aba ativa" : "aba"}
                onClick={() => setModoEstudo("flashcards")}
              >
                📚 Flashcards
              </button>
              <button
                type="button"
                className={modoEstudo === "ingles" ? "aba ativa" : "aba"}
                onClick={() => setModoEstudo("ingles")}
              >
                🇬🇧 Inglês Ativo
              </button>
            </div>
          </div>

          {erro && <p className="erro">{erro}</p>}

          {modoEstudo === "ingles" ? (
            /* ---------- Leitura em Inglês ---------- */
            <div className="cards-criar">
              <p className="leitura-ingles-intro">
                Cole um texto em inglês — um artigo, um trecho de página, o que você quiser
                conseguir ler com mais facilidade — e a IA monta questões de vocabulário a
                partir das frases reais desse texto. Treinando elas, a leitura desse texto
                específico fica mais fácil.
              </p>
              <div className="form-card">
                <label className="campo">
                  <span>Cole o texto que você quer treinar</span>
                  <textarea
                    value={textoLeitura}
                    onChange={(e) => setTextoLeitura(e.target.value.slice(0, LIMITE_TEXTO_LEITURA))}
                    placeholder="Cole aqui um artigo, uma página, ou qualquer texto em inglês…"
                    rows={14}
                  />
                  <span className="campo-contador">
                    {textoLeitura.length.toLocaleString("pt-BR")} / {LIMITE_TEXTO_LEITURA.toLocaleString("pt-BR")} caracteres
                  </span>
                </label>
                <div className="leitura-ingles-opcoes">
                  <label className="campo">
                    <span>Seu nível (CEFR)</span>
                    <select
                      className="ordenacao-select"
                      value={nivelLeitura}
                      onChange={(e) => setNivelLeitura(e.target.value)}
                    >
                      {NIVEIS_CEFR.map(n => (
                        <option key={n.valor} value={n.valor}>{n.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="campo">
                    <span>Idioma da resposta</span>
                    <select
                      className="ordenacao-select"
                      value={idiomaResposta}
                      onChange={(e) => setIdiomaResposta(e.target.value)}
                    >
                      {IDIOMAS_RESPOSTA.map(i => (
                        <option key={i.valor} value={i.valor}>{i.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="campo campo-inline">
                    <span>Quantidade de questões</span>
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={qtdLeitura}
                      onChange={(e) => setQtdLeitura(Number(e.target.value))}
                    />
                  </label>
                </div>
              </div>
            </div>
          ) : (
            /* ---------- Flashcards (fluxo original) ---------- */
            <div className="cards-criar">
              <div className="abas">
                <button
                  type="button"
                  className={modo === "manual" ? "aba ativa" : "aba"}
                  onClick={() => setModo("manual")}
                >
                  Adicionar manualmente
                </button>
                <button
                  type="button"
                  className={modo === "ia" ? "aba ativa" : "aba"}
                  onClick={() => setModo("ia")}
                >
                  Gerar com IA
                </button>
              </div>

              {modo === "manual" ? (
                <div className="linhas-cards">
                  {linhas.map((linha, i) => (
                    <div key={i} className="linha-card">
                      <span className="linha-card-num">{i + 1}</span>
                      <div className="linha-card-campos">
                        <textarea
                          value={linha.frente}
                          onChange={(e) => updateLinha(i, "frente", e.target.value)}
                          placeholder="Frente (pergunta)"
                          rows={2}
                        />
                        <textarea
                          value={linha.verso}
                          onChange={(e) => updateLinha(i, "verso", e.target.value)}
                          placeholder="Verso (resposta)"
                          rows={2}
                        />
                      </div>
                      {linhas.length > 1 && (
                        <button
                          type="button"
                          className="linha-card-remover"
                          onClick={() => removeLinha(i)}
                          title="Remover"
                        >
                          ×
                        </button>
                      )}
                    </div>
                  ))}
                  <button type="button" className="botao-add-linha" onClick={addLinha}>
                    + Adicionar card
                  </button>
                </div>
              ) : (
                <div className="form-card">
                  <label className="campo">
                    <span>Material de estudo</span>
                    <textarea
                      value={textoIA}
                      onChange={(e) => setTextoIA(e.target.value)}
                      placeholder="Cole aqui suas anotações, um trecho do livro, a descrição de um conceito…"
                      rows={8}
                    />
                  </label>
                  <div className="form-card-rodape">
                    <label className="campo campo-inline">
                      <span>Quantidade de cards</span>
                      <input
                        type="number"
                        min={1}
                        max={30}
                        value={qtdIA}
                        onChange={(e) => setQtdIA(Number(e.target.value))}
                      />
                    </label>
                  </div>
                </div>
              )}
            </div>
          )}

          <button
            className="botao-principal criar-deck-submit"
            type="submit"
            disabled={salvando || !nome.trim()}
          >
            {salvando
              ? (gerandoPorIA ? msgIA : "Criando…")
              : "Criar deck"}
          </button>
        </form>
      </main>
    </div>
  );
}
