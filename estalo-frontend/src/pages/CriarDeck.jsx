import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

const MSGS_IA = [
  "Lendo o texto fornecido...",
  "Decompondo conceitos essenciais...",
  "Criando alternativas falsas inteligentes...",
  "Finalizando a formatação dos cards...",
];

const NIVEIS_CEFR = [
  { valor: "A1", label: "A1 — Iniciante" },
  { valor: "A2", label: "A2 — Básico" },
  { valor: "B1", label: "B1 — Intermediário" },
  { valor: "B2", label: "B2 — Intermediário avançado" },
  { valor: "C1", label: "C1 — Avançado" },
  { valor: "C2", label: "C2 — Proficiente" },
];

// Componente de feedback do Mentor de Inglês Ativo — content vem sempre
// no formato {student_attempt, native_correction, why, collocations}
// (ver PERSONA_MENTOR_INGLES em challenge_service.py, backend). Pensado
// pra textos curtos e legíveis de relance: a tentativa fica discreta, a
// correção é o elemento que mais chama atenção, collocations viram chips.
function renderMentorIngles(content) {
  return (
    <div className="mentor-ingles-card">
      <p className="mentor-ingles-tentativa">
        <span className="mentor-ingles-label">Você escreveu</span>
        {content.student_attempt}
      </p>
      <p className="mentor-ingles-correcao">
        <span className="mentor-ingles-label">✓ Um nativo diria</span>
        {content.native_correction}
      </p>
      {Array.isArray(content.collocations) && content.collocations.length > 0 && (
        <div className="mentor-ingles-collocations">
          {content.collocations.map((c, i) => (
            <span key={i} className="mentor-chip">{c}</span>
          ))}
        </div>
      )}
      <p className="mentor-ingles-porque">{content.why}</p>
    </div>
  );
}

export default function CriarDeck({ pastaId, aoVoltar, aoVerCards }) {
  const [nome, setNome] = useState("");
  const [descricao, setDescricao] = useState("");

  // Modo de Estudo: 'flashcards' (fluxo original, intocado) ou 'ingles'
  // (Mentor de Inglês Ativo) — são dois motores de conteúdo totalmente
  // isolados por baixo (ver challenge_service.py), essa é só a escolha
  // de qual o usuário quer usar nesta sessão de criação.
  const [modoEstudo, setModoEstudo] = useState("flashcards");

  const [modo, setModo] = useState("manual"); // "manual" | "ia" (dentro de Flashcards)

  // Modo manual: linhas dinâmicas
  const [linhas, setLinhas] = useState([{ frente: "", verso: "" }]);

  // Modo IA
  const [textoIA, setTextoIA] = useState("");
  const [qtdIA, setQtdIA] = useState(5);

  // Mentor de Inglês Ativo
  const [tentativaIngles, setTentativaIngles] = useState("");
  const [nivelIngles, setNivelIngles] = useState("B1");
  const [previewChallenges, setPreviewChallenges] = useState([]);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [salvandoChallenges, setSalvandoChallenges] = useState(false);
  const [challengesSalvos, setChallengesSalvos] = useState(0);

  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [msgIA, setMsgIA] = useState(MSGS_IA[0]);
  const msgIAIdx = useRef(0);

  // O deck precisa existir (com id de verdade) antes de gerar ou salvar
  // qualquer challenge — Challenge.deck_id é obrigatório e validado por
  // dono no backend. Criado sob demanda (1ª correção do Mentor, ou no
  // submit do formulário, o que vier primeiro) e reaproveitado depois —
  // nunca duas vezes pro mesmo rascunho.
  const deckCriadoRef = useRef(null);

  async function garantirDeck() {
    if (deckCriadoRef.current) return deckCriadoRef.current;
    const deck = await api.criarDeck(nome.trim(), descricao.trim() || null, pastaId);
    deckCriadoRef.current = deck;
    return deck;
  }

  useEffect(() => {
    if (!salvando || modo !== "ia") return;
    setMsgIA(MSGS_IA[0]);
    msgIAIdx.current = 0;
    const id = setInterval(() => {
      msgIAIdx.current = (msgIAIdx.current + 1) % MSGS_IA.length;
      setMsgIA(MSGS_IA[msgIAIdx.current]);
    }, 2500);
    return () => clearInterval(id);
  }, [salvando, modo]);

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
      // garantirDeck() em vez de api.criarDeck() direto: se o usuário já
      // gerou alguma correção do Mentor antes de dar submit, o deck já
      // existe (deckCriadoRef) e é reaproveitado — sem isso, criaríamos
      // um segundo deck vazio e deixaríamos o primeiro (com os challenges
      // salvos) órfão do formulário. Em modoEstudo="ingles", `modo`
      // nunca sai de "manual" e `linhas` fica vazia — o submit principal
      // só cria o deck, sem duplicar nada do fluxo de inglês.
      const deck = await garantirDeck();

      if (modo === "manual") {
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

  async function handleCorrigirIngles() {
    if (!nome.trim() || !tentativaIngles.trim()) return;
    setIsLoadingPreview(true);
    setErro("");
    try {
      const deck = await garantirDeck();
      const pedido = {
        deck_id: deck.id,
        raw_content: tentativaIngles.trim(),
        type: "ENGLISH_TUTOR",
        language_level: nivelIngles,
      };
      const preview = await api.generateChallengePreview(pedido);
      setPreviewChallenges(lista => [...lista, { chave: crypto.randomUUID(), pedido, preview }]);
      // Limpa o campo pra próxima tentativa — fluxo de prática rápida,
      // tipo chat: escreve, corrige, escreve de novo, sem re-digitar.
      setTentativaIngles("");
    } catch (err) {
      setErro(err.message);
    } finally {
      setIsLoadingPreview(false);
    }
  }

  function removerPreviewChallenge(chave) {
    setPreviewChallenges(lista => lista.filter(item => item.chave !== chave));
  }

  async function handleConfirmarChallenges() {
    if (previewChallenges.length === 0) return;
    setSalvandoChallenges(true);
    setErro("");
    try {
      for (const item of previewChallenges) {
        await api.saveChallenge(item.pedido);
      }
      setChallengesSalvos(n => n + previewChallenges.length);
      setPreviewChallenges([]);
    } catch (err) {
      setErro(err.message);
    } finally {
      setSalvandoChallenges(false);
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
            /* ---------- Mentor de Inglês Ativo ---------- */
            <div className="cards-criar mentor-ingles-form">
              <p className="mentor-ingles-intro">
                Escreva uma frase em inglês do jeito que você diria naturalmente — o Mentor
                mostra como um nativo diria e explica o porquê, com foco em collocations e
                gramática no contexto, não em tradução mecânica.
              </p>
              <div className="form-card">
                <label className="campo">
                  <span>O que você tentou dizer em inglês?</span>
                  <textarea
                    value={tentativaIngles}
                    onChange={(e) => setTentativaIngles(e.target.value)}
                    placeholder="Ex: I are happy to see you yesterday"
                    rows={3}
                  />
                </label>
                <label className="campo mentor-ingles-nivel">
                  <span>Seu nível (CEFR)</span>
                  <select
                    className="ordenacao-select"
                    value={nivelIngles}
                    onChange={(e) => setNivelIngles(e.target.value)}
                  >
                    {NIVEIS_CEFR.map(n => (
                      <option key={n.valor} value={n.valor}>{n.label}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="botao-principal"
                  disabled={isLoadingPreview || !nome.trim() || !tentativaIngles.trim()}
                  onClick={handleCorrigirIngles}
                >
                  {isLoadingPreview ? "Corrigindo…" : "✨ Corrigir com o Mentor"}
                </button>
                {isLoadingPreview && <div className="skeleton challenge-preview-skeleton" />}
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
              ? (modo === "ia" ? msgIA : "Criando…")
              : "Criar deck"}
          </button>
        </form>

        {/* Painel de correções do Mentor — fora do <form> de propósito, é
            uma ação separada (Confirmar e Salvar) do submit principal do
            deck, e persiste mesmo se o usuário trocar de Modo de Estudo. */}
        {previewChallenges.length > 0 && (
          <section className="challenge-preview-painel">
            <div className="challenge-preview-header">
              <h2 className="challenge-preview-titulo">Correções do Mentor</h2>
              <span className="badge-ia">✨ IA</span>
            </div>

            <ul className="challenge-preview-lista">
              {previewChallenges.map(item => (
                <li key={item.chave} className="item-card challenge-preview-item">
                  <button
                    type="button"
                    className="linha-card-remover"
                    onClick={() => removerPreviewChallenge(item.chave)}
                    title="Remover"
                  >
                    ×
                  </button>
                  {renderMentorIngles(item.preview.content)}
                  <p className="challenge-preview-explicacao">{item.preview.explanation}</p>
                </li>
              ))}
            </ul>

            <button
              type="button"
              className="botao-principal"
              disabled={salvandoChallenges}
              onClick={handleConfirmarChallenges}
            >
              {salvandoChallenges ? "Salvando…" : `Confirmar e Salvar (${previewChallenges.length})`}
            </button>
          </section>
        )}

        {challengesSalvos > 0 && previewChallenges.length === 0 && (
          <p className="challenge-preview-sucesso">
            {challengesSalvos} correç{challengesSalvos !== 1 ? "ões salvas" : "ão salva"} no deck.
            {/* Sem link direto pra "ver desafios" -- Cards.jsx ainda não exibe
                Challenge, só Card (ver backlog). */}
          </p>
        )}
      </main>
    </div>
  );
}
