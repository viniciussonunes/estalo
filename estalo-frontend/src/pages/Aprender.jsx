import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";
import useStudySession from "../hooks/useStudySession.js";

/*
  Lógica de fases SM-2:
    Fase 1 (rep == 0 / Novo)       0 erros no quiz  → quality 4  → Fase 2 (fica fácil)
    Fase 1 (rep == 0 / Novo)       1+ erros no quiz → quality 3  → Fase 2 (padrão)
    Fase 2 (rep == 1 / Validando)  acertou sem errar → quality 5  → Fase 3
    Fase 2                         errou alguma vez  → quality 2  → reseta (Crítico Imediato)
    Fase 3+ (rep ≥ 2 / Dominado)   acertou sem errar → quality 5
    Fase 3+                        errou alguma vez  → quality 1  → volta à Fase 1
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
        // Só vêm preenchidos na Fila Única (Revisão Geral) — ver
        // _buscarCards(). Em cards normais (api.listarCards) ficam
        // undefined, então a badge de origem simplesmente não renderiza.
        deck_name:      card.deck_name,
        deck_color:     card.deck_color,
      };
    });
}

export default function Aprender({ deck, aoVoltar, modoGlobal = false }) {
  // Na Fila Única não existe "o" deck — usa uma chave fixa própria pro
  // snapshot de F5, isolada de qualquer sessão por-deck real (ids de deck
  // são sempre numéricos, nunca colidem com essa string).
  const { snapshotPendente, salvar, limpar, descartarPendente } = useStudySession(modoGlobal ? "global" : deck.id);

  // Busca os cards a estudar: de um deck só (Modo Aprender normal) ou o
  // lote agrupado de até 15 vencidos de todas as pastas (Fila Única). Os
  // dois formatos convergem pro mesmo shape que montarFila() já espera
  // (id/front/back/options/explanation/repetitions), só a Fila Única
  // carrega junto deck_name/deck_color pra badge.
  function _buscarCards() {
    if (modoGlobal) {
      return api.proximaRevisaoGlobal().then(lista => lista.map(c => ({
        id:          c.card_id,
        front:       c.front,
        back:        c.back,
        options:     c.options,
        explanation: c.explanation,
        repetitions: c.repetitions,
        deck_name:   c.deck_name,
        deck_color:  c.deck_color,
      })));
    }
    return api.listarCards(deck.id);
  }

  const [fila, setFila]               = useState([]);
  const [totalUnicos, setTotalUnicos] = useState(0);
  const [carregando, setCarregando]   = useState(!snapshotPendente);
  const [mostrarPrompt, setMostrarPrompt] = useState(!!snapshotPendente);
  const [erro, setErro]               = useState("");
  const [semQuiz, setSemQuiz]         = useState(false);
  const [concluido, setConcluido]     = useState(false);
  const [salvando, setSalvando]       = useState(false);
  const [resposta, setResposta]       = useState(null);
  // true só durante a "linha de chegada": o intervalo entre acertar o
  // último card e de fato trocar pra tela de resultado. Sem isso,
  // setConcluido(true) desmontava a pergunta na mesma hora que a fila
  // esvaziava, e a barra nunca tinha tempo de deslizar até 100% (ver
  // proximo()). Também trava novos cliques/Enter nesse intervalo.
  const [concluindoAnimacao, setConcluindoAnimacao] = useState(false);
  // true durante o "Rever Vilões": um loop de treino extra, 100% em memória,
  // que reaproveita a mesma UI de pergunta/resposta sem tocar no banco nem
  // no snapshot de F5 (ver os dois useEffect abaixo e proximo()).
  const [modoPraticaViloes, setModoPraticaViloes] = useState(false);

  // Map<card_id, quantidade de vezes que errou nesta sessão> — antes era um
  // Set (só "errou ou não"). Agora contamos de verdade, pra graduar a nota
  // final em _salvarProgresso (Proposta 3) em vez de tratar todo erro igual.
  const errosPorCard      = useRef(new Map());
  // Cards que já foram acertados durante o "Rever Vilões" — separado de
  // errosPorCard de propósito: preserva a contagem original de erros (usada
  // em _salvarProgresso) e só marca "resolvido" como uma dimensão à parte,
  // consultada no filtro de `viloes` da tela de resumo.
  const viloesResolvidos  = useRef(new Set());
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

  function _restaurarDeSnapshot(snap) {
    setFila(snap.fila);
    setTotalUnicos(snap.totalUnicos);
    questoesOriginais.current = snap.questoesOriginais;
    startingReps.current = snap.startingReps;
    errosPorCard.current = new Map(snap.errosPorCard);
    setAcertosNaPrimeira(snap.acertosNaPrimeira);
    inicioSessao.current = snap.inicioSessao;
    // snap.resposta pode não existir em snapshots salvos antes dessa mudança
    // (?? null cobre isso: retoma sem alternativa marcada, e não quebra).
    setResposta(snap.resposta ?? null);
  }

  function _carregarDoServidor() {
    setCarregando(true);
    _buscarCards()
      .then(_iniciarComCards)
      .catch(err => setErro(err.message))
      .finally(() => setCarregando(false));
  }

  useEffect(() => {
    if (mostrarPrompt) return; // aguarda decisão do usuário sobre a sessão salva
    _carregarDoServidor();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck?.id, modoGlobal]);

  function continuarSessaoSalva() {
    _restaurarDeSnapshot(snapshotPendente);
    descartarPendente();
    setMostrarPrompt(false);
    setCarregando(false);
  }

  function comecarDoZero() {
    limpar();
    descartarPendente();
    setMostrarPrompt(false);
    _carregarDoServidor();
  }

  // "Voltar" só navega — não descarta o snapshot. O progresso só é apagado
  // quando a sessão é concluída de verdade (useEffect logo abaixo) ou quando
  // o usuário escolhe explicitamente "Começar do zero".
  function sair() {
    aoVoltar();
  }

  // Salva o progresso a cada mudança (inclusive a alternativa marcada na
  // questão atual, ainda não confirmada), pra sobreviver a reload/saída.
  //
  // modoPraticaViloes também barra o save aqui — sem essa trava, o "Rever
  // Vilões" reaproveita `fila`/`concluido=false` pra rodar a mesma UI de
  // pergunta, e esse efeito escreveria um snapshot com só o subconjunto de
  // vilões. Um F5 nesse momento leria esse snapshot errado e ofereceria
  // "continuar" uma sessão que não é a sessão real — a real já foi salva e
  // encerrada antes da prática começar (ver reverViloes()).
  useEffect(() => {
    if (mostrarPrompt || concluido || fila.length === 0 || modoPraticaViloes) return;
    salvar({
      fila,
      totalUnicos,
      questoesOriginais: questoesOriginais.current,
      startingReps: startingReps.current,
      // Serializa o Map como array de pares [card_id, contagem] — JSON não
      // tem Map nativo. new Map(arrayDePares) reconstrói certinho na volta.
      errosPorCard: [...errosPorCard.current],
      acertosNaPrimeira,
      inicioSessao: inicioSessao.current,
      resposta,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fila, acertosNaPrimeira, concluido, mostrarPrompt, resposta, modoPraticaViloes]);

  // Sessão chegou ao fim (equivalente a SessaoConcluida) → limpa o snapshot.
  useEffect(() => {
    if (concluido) limpar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [concluido]);

  const questaoAtual = fila[0] ?? null;
  const respondeu    = resposta !== null;

  // Mantém ref atualizada para o handler de teclado (evita stale closure)
  useEffect(() => { proximoRef.current = proximo; });

  // Incrementa a contagem de erros do card (usado tanto pelo clique quanto
  // pelo atalho de teclado, pra não duplicar a lógica em dois lugares).
  function _registrarErro(cardId) {
    errosPorCard.current.set(cardId, (errosPorCard.current.get(cardId) ?? 0) + 1);
  }

  useEffect(() => {
    function onKey(e) {
      if (concluido || semQuiz || carregando) return;
      const atual = fila[0];
      if (!atual) return;
      if (!respondeu && ["1","2","3","4"].includes(e.key)) {
        const opt = atual.options[parseInt(e.key) - 1];
        if (opt) {
          setResposta(opt.letter);
          if (opt.letter !== atual.correct_letter) _registrarErro(atual.card_id);
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
      _registrarErro(fila[0].card_id);
    } else if (modoPraticaViloes) {
      // Acertou um vilão durante a prática — marca resolvido sem tocar em
      // errosPorCard (que precisa manter a contagem original de erros).
      viloesResolvidos.current.add(fila[0].card_id);
    }
  }

  async function proximo() {
    if (concluindoAnimacao) return; // trava clique duplo/Enter repetido durante a linha de chegada

    const atual   = fila[0];
    const acertou = resposta === atual.correct_letter;

    if (acertou) {
      const novaFila = fila.slice(1);
      if (!errosPorCard.current.has(atual.card_id)) {
        setAcertosNaPrimeira(n => n + 1);
      }
      if (novaFila.length === 0) {
        // Linha de chegada: NÃO atualiza `fila` aqui de propósito — ela
        // continua com o último card, então questaoAtual nunca vira null
        // e a tela de pergunta permanece montada, congelada. concluindoAnimacao
        // força a barra pro estilo inline de 100% (ver JSX), e só depois de
        // ~450ms — tempo do CSS transition rodar de verdade — é que troca
        // pra tela de resultado. Sem esse atraso, setConcluido(true) trocava
        // de tela na mesma hora que a fila esvaziava, e o preenchimento de
        // 100% nunca chegava a ser desenhado.
        setConcluindoAnimacao(true);
        // Trava crítica: no "Rever Vilões" a fila também esvazia e cai
        // aqui, mas essa rodada é só treino — não pode chamar
        // _salvarProgresso() de novo (já rodou uma vez, na sessão real).
        // Disparado em paralelo com o atraso visual, não bloqueia a
        // animação — a tela de resultado já mostra "Salvando…" enquanto
        // isso ainda estiver em voo (ver `salvando`).
        if (!modoPraticaViloes) _salvarProgresso();
        setTimeout(() => {
          setConcluido(true);
          setConcluindoAnimacao(false);
          if (modoPraticaViloes) setModoPraticaViloes(false);
        }, 450);
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
      const fase = startingReps.current[q.card_id] ?? 0;
      const errou = (errosPorCard.current.get(q.card_id) ?? 0) > 0;

      let quality;
      if (fase === 0)                quality = errou ? 3 : 4; // Novo: limpo=4, com erro=3 — nunca cai no Crítico Imediato (quality<3)
      else if (fase === 1 && errou)  quality = 2;              // Validando + erro: reseta (Crítico Imediato), penalidade mais leve que Dominado
      else if (fase === 1 && !errou) quality = 5;              // Validando sem erro: avança pra Dominado
      else if (fase >= 2 && !errou)  quality = 5;              // Dominado sem erro: estende
      else                            quality = 1;              // Dominado com erro: volta à Fase 1

      return api.responderCard(q.card_id, quality, true).catch(err => {
        console.error(`[Aprender] card ${q.card_id} fase=${fase} quality=${quality} erro:`, err.message);
      });
    });
    try { await Promise.all(chamadas); } catch { /* silencioso */ }

    // Resumo da rodada pro histórico do Dashboard. Fire-and-forget depois
    // das respostas individuais acima: se isso falhar, perde-se só um ponto
    // do gráfico de evolução, não o progresso real dos cards.
    //
    // acertosNaPrimeira (state) não serve aqui — quando o último card é
    // acertado, o setAcertosNaPrimeira(n => n+1) ainda não "assentou" no
    // momento em que _salvarProgresso roda (mesma classe de stale closure
    // que motivou o proximoRef acima). Recalcula do zero a partir do ref,
    // que está sempre atualizado.
    const acertosPrimeiraFinal = questoesOriginais.current.filter(
      q => !errosPorCard.current.has(q.card_id)
    ).length;
    api.logarSessao(
      questoesOriginais.current.length,
      acertosPrimeiraFinal,
      Math.floor((Date.now() - (inicioSessao.current ?? Date.now())) / 1000),
      modoGlobal ? "global" : "deck",
    ).catch(err => console.error("[Aprender] falha ao logar sessão:", err.message));

    setSalvando(false);
  }

  function reiniciarSessao() {
    errosPorCard.current = new Map();
    viloesResolvidos.current.clear();
    startingReps.current = {};
    setAcertosNaPrimeira(0);
    setResposta(null);
    setConcluido(false);
    setCarregando(true);
    _buscarCards()
      .then(cards => { _iniciarComCards(cards); })
      .catch(err => setErro(err.message))
      .finally(() => setCarregando(false));
  }

  // Repopula a fila só com os cards que erraram >=2x na sessão que acabou
  // de fechar, e reusa a MESMA UI de pergunta/resposta pra treinar de novo.
  // Não busca nada do servidor, não mexe em errosPorCard/startingReps — é
  // puramente uma segunda passada em memória sobre o que já está carregado.
  function reverViloes() {
    const viloes = questoesOriginais.current.filter(
      q => (errosPorCard.current.get(q.card_id) ?? 0) >= 2
        && !viloesResolvidos.current.has(q.card_id)
    );
    if (viloes.length === 0) return;
    setModoPraticaViloes(true);
    setResposta(null);
    setFila(viloes);
    setConcluido(false);
  }

  // Durante o "Rever Vilões", Voltar não sai da tela — volta pro resumo da
  // sessão real (que já foi salva). Fora desse modo, comportamento normal.
  function voltarOuSairDaPratica() {
    if (modoPraticaViloes) {
      setModoPraticaViloes(false);
      setResposta(null);
      setConcluido(true);
    } else {
      sair();
    }
  }

  // ─── Header ────────────────────────────────────────────────────────────
  const cabecalho = (
    <header className="topo">
      <div className="topo-esquerda">
        <button className="botao-texto" onClick={voltarOuSairDaPratica}>
          {modoPraticaViloes ? "← Voltar ao resumo" : "← Voltar"}
        </button>
        <span className="estudo-deck-nome">
          {modoGlobal ? "Revisão Geral do Dia" : deck.title}
        </span>
      </div>
      <span className="modo-label">{modoPraticaViloes ? "Revisão de vilões" : "Múltipla escolha"}</span>
    </header>
  );

  if (mostrarPrompt && snapshotPendente) {
    const minutosAtras = Math.max(1, Math.round((Date.now() - snapshotPendente.timestamp) / 60000));
    return (
      <div className="pagina">{cabecalho}
        <main className="conteudo estudo-centro">
          <div className="gamificado-aviso">
            <p className="gamificado-aviso-titulo">↺ Sessão em andamento encontrada</p>
            <p className="gamificado-aviso-texto">
              Você tem uma sessão iniciada há {minutosAtras} min neste deck, com{" "}
              <em>{snapshotPendente.fila.length} questão(ões)</em> restante(s). Deseja continuar de onde parou?
            </p>
            <div className="gamificado-botoes">
              <button className="botao-principal" onClick={continuarSessaoSalva}>Continuar sessão</button>
              <button className="botao-texto" onClick={comecarDoZero}>Começar do zero</button>
            </div>
          </div>
        </main>
      </div>
    );
  }

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
            <button className="botao-principal estudo-concluido-botao" onClick={sair}>Voltar</button>
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
              {modoGlobal
                ? 'Os cards vencidos ainda não têm alternativas geradas por IA. Entre em cada deck e use a aba "Gerar com IA" para criar questões com alternativas.'
                : 'Este deck não tem cards gerados com IA. Vá até a tela de Cards e use a aba "Gerar com IA" para criar questões com alternativas.'}
            </p>
            <button className="botao-principal estudo-concluido-botao" onClick={sair}>
              {modoGlobal ? "Voltar à Home" : "Voltar ao deck"}
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
    // Vilões: cards que custaram 2+ erros nesta sessão — candidatos a uma
    // segunda passada rápida, só em memória (ver reverViloes()). Exclui quem
    // já foi acertado numa rodada de "Rever Vilões" anterior nesta mesma
    // sessão (viloesResolvidos), sem descontar de errosPorCard — a contagem
    // original de erros continua intacta pra _salvarProgresso.
    const viloes = questoesOriginais.current.filter(
      q => (errosPorCard.current.get(q.card_id) ?? 0) >= 2
        && !viloesResolvidos.current.has(q.card_id)
    );

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

            {viloes.length > 0 && (
              <div className="viloes-bloco">
                <p className="viloes-titulo">🎯 Vilões da rodada</p>
                <p className="viloes-sub">
                  {viloes.length} card{viloes.length !== 1 ? "s" : ""} te derrubaram 2 vezes ou
                  mais nesta sessão — vale uma revisão rápida agora, sem custar nada no seu ritmo real.
                </p>
                <ul className="viloes-lista">
                  {viloes.map(v => (
                    <li key={v.card_id} className="viloes-item">
                      <span className="viloes-item-texto">{v.question}</span>
                      <span className="viloes-item-badge">{errosPorCard.current.get(v.card_id)}×</span>
                    </li>
                  ))}
                </ul>
                <button className="botao-principal" onClick={reverViloes}>
                  Rever Vilões
                </button>
              </div>
            )}

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
                  <button className="botao-texto" onClick={sair}>
                    {modoGlobal ? "Voltar à Home" : "Voltar aos decks"}
                  </button>
                </div>
              </div>
            ) : (
              <button className="botao-principal estudo-concluido-botao"
                onClick={sair} disabled={salvando}>
                {salvando ? "Salvando…" : modoGlobal ? "Voltar à Home" : "Voltar ao deck"}
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
          <span className="quiz-progresso-contador">
            Card {Math.min(cardsConcluidos + 1, totalUnicos)} de {totalUnicos}
          </span>
          <div className="quiz-barra">
            <div className="quiz-barra-fill"
              style={{ width: `${concluindoAnimacao ? 100 : (cardsConcluidos / totalUnicos) * 100}%` }} />
          </div>
          {repeticoes > 0 && (
            <span className="quiz-repetindo" title="Aguardando reacerto">+{repeticoes}↺</span>
          )}
        </div>

        <div className="cartao-estudo">
          <div className="cartao-frente">
            <span className="cartao-lado-label">Pergunta</span>
            {modoGlobal && questaoAtual.deck_name && (
              <span
                className="revisao-badge-origem"
                style={{
                  borderColor: questaoAtual.deck_color || "var(--borda-forte)",
                  color: questaoAtual.deck_color || "var(--tinta-suave)",
                  background: questaoAtual.deck_color
                    ? `color-mix(in srgb, ${questaoAtual.deck_color} 14%, transparent)`
                    : "var(--papel)",
                }}
              >
                {questaoAtual.deck_name}
              </span>
            )}
            <p className="cartao-texto">{questaoAtual.question}</p>
          </div>

          <div className="quiz-opcoes">
            {questaoAtual.options.map((op, i) => {
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
              <button className="botao-principal" onClick={proximo} disabled={concluindoAnimacao}>
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
        fill="var(--tinta)" fontFamily="Fraunces, serif">
        {Math.round(pct)}%
      </text>
      <text x="50" y="61" textAnchor="middle" fontSize="9" fill="var(--tinta-suave)">
        precisão
      </text>
    </svg>
  );
}
