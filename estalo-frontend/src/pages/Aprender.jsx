import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import confetti from "canvas-confetti";
import { api, QuotaExceededException } from "../api.js";
import { contar, enfileirar, sincronizar } from "../outbox.js";
import useStudySession from "../hooks/useStudySession.js";
import useOnline from "../hooks/useOnline.js";
import { useToast } from "../hooks/ToastContext.jsx";
import QuotaLimitModal from "../components/QuotaLimitModal.jsx";
import SeloOffline from "../components/SeloOffline.jsx";
import Modal from "../components/Modal.jsx";
import ToggleTema from "../components/ToggleTema.jsx";

// Cores da própria paleta do app (violeta de marca + verde/âmbar/rosa dos
// estados de acerto) -- confete precisa combinar com o resto da UI, não
// parecer um componente genérico colado por cima.
const CONFETTI_CORES = ["#5c54e8", "#16a34a", "#f59e0b", "#ec4899"];

function _prefereReduzirMovimento() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** Disparado uma vez ao fechar a sessão de verdade (ver useEffect [concluido]). */
function comemorarSessaoConcluida() {
  if (_prefereReduzirMovimento()) return;
  confetti({ particleCount: 120, spread: 90, origin: { y: 0.6 }, colors: CONFETTI_CORES });
  confetti({ particleCount: 60, angle: 60, spread: 70, origin: { x: 0, y: 0.6 }, colors: CONFETTI_CORES });
  confetti({ particleCount: 60, angle: 120, spread: 70, origin: { x: 1, y: 0.6 }, colors: CONFETTI_CORES });
}

/** Disparado a cada vilão resolvido no "Rever Vilões" (menor, não rouba a cena). */
function comemorarVilaoResolvido() {
  if (_prefereReduzirMovimento()) return;
  confetti({ particleCount: 40, spread: 55, origin: { y: 0.7 }, scalar: 0.75, colors: CONFETTI_CORES });
}

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

export default function Aprender({ deck, aoVoltar, modoGlobal = false, folderId = null, folderName = null, aoEstudoClassico }) {
  // Na Fila Única não existe "o" deck — usa uma chave fixa própria pro
  // snapshot de F5, isolada de qualquer sessão por-deck real (ids de deck
  // são sempre numéricos, nunca colidem com essa string). Escopada por
  // pasta quando "Estudar Pasta" (folderId) pra não colidir com a sessão
  // salva da Fila Única de verdade nem com a de outra pasta.
  const chaveSessao = modoGlobal ? (folderId ? `folder-${folderId}` : "global") : deck.id;
  const { snapshotPendente, salvar, limpar, descartarPendente } = useStudySession(chaveSessao);
  const mostrarToast = useToast();
  const online = useOnline();

  // Busca os cards a estudar: de um deck só (Modo Aprender normal) ou o
  // lote agrupado de até 15 vencidos (Fila Única — todas as pastas, ou só
  // uma + subpastas quando folderId vem preenchido, "Estudar Pasta"). Os
  // dois formatos convergem pro mesmo shape que montarFila() já espera
  // (id/front/back/options/explanation/repetitions), só a Fila Única
  // carrega junto deck_name/deck_color pra badge.
  function _buscarCards() {
    if (modoGlobal) {
      return api.proximaRevisaoGlobal(folderId).then(lista => lista.map(c => ({
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
  // Quantos vilões entraram na prática -- base do contador enquanto ela
  // roda, já que a fila deixa de ser a sessão inteira (ver reverViloes).
  const [totalViloes, setTotalViloes] = useState(0);
  const [carregando, setCarregando]   = useState(!snapshotPendente);
  // true só durante a chamada de auto-cura (POST /study/cards/enrich) —
  // usada pra trocar a mensagem de "Carregando cards…" por algo que não
  // vaze o detalhe de que alguns cards estavam sem quiz (ver _repararSemQuiz).
  const [reparando, setReparando]     = useState(false);
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
  // Treino extra, 100% em memória: reaproveita a mesma UI de
  // pergunta/resposta sem tocar no banco nem no snapshot de F5 (ver os dois
  // useEffect abaixo e proximo()). null = sessão de verdade.
  //   "viloes" -> só os cards que custaram 2+ erros
  //   "tudo"   -> a sessão inteira de novo, a pedido de quem quer repetir
  // O "tudo" existe porque o botão que fazia isso ANTES refazia a sessão
  // valendo: o card ia de "volta amanhã" pra "volta em 6 dias" e ganhava o
  // selo de Dominado, com base num acerto 3 minutos depois de aprender.
  // Praticar e pontuar viraram coisas separadas.
  const [modoPratica, setModoPratica] = useState(null);

  // Map<card_id, quantidade de vezes que errou nesta sessão> — antes era um
  // Set (só "errou ou não"). Agora contamos de verdade, pra graduar a nota
  // final em _salvarProgresso (Proposta 3) em vez de tratar todo erro igual.
  const errosPorCard      = useRef(new Map());
  // Cards que já foram acertados durante o "Rever Vilões" — separado de
  // errosPorCard de propósito: preserva a contagem original de erros (usada
  // em _salvarProgresso) e só marca "resolvido" como uma dimensão à parte,
  // consultada no filtro de `viloes` da tela de resumo.
  const viloesResolvidos  = useRef(new Set());
  // Garante um único burst de confete por sessão de verdade -- sem isso, ao
  // voltar do "Rever Vilões" (que também passa por concluido=true) o efeito
  // abaixo dispararia de novo o mesmo confete de "sessão concluída".
  const confetiSessaoDisparado = useRef(false);
  const startingReps      = useRef({});
  const questoesOriginais = useRef([]);
  const inicioSessao      = useRef(null);
  const proximoRef        = useRef(null);
  const [acertosNaPrimeira, setAcertosNaPrimeira] = useState(0);
  const [tempoSessao, setTempoSessao] = useState(0);
  // Só na Fila Única. O backend entrega a revisão em lotes de 15, mas o
  // herói da Home diz "15+ esperando" -- quem tinha 40 terminava o lote,
  // via "Voltar à Home" como única saída, voltava e encontrava "25
  // esperando" sem nada ter explicado que a sessão era um pedaço. Depois
  // de salvar, o app pergunta ao servidor o que ainda falta (ver
  // _salvarProgresso) e guarda aqui:
  //   null  -> não sabe (sem rede, respostas ainda na fila, ou por-deck)
  //   []    -> zerou por hoje
  //   [...] -> o próximo lote, já carregado, pronto pro "Continuar"
  const [proximoLote, setProximoLote] = useState(null);

  // Tutor Inteligente: explicação sob demanda pra questão atual (ver
  // botão "Perguntar ao Tutor" abaixo). tutorTexto fica em cache local por
  // card_id enquanto a fila não avança — reabrir o modal pro mesmo card
  // não refaz a chamada (ver pedirTutor).
  const [tutorAberto, setTutorAberto]         = useState(false);
  const [tutorCarregando, setTutorCarregando] = useState(false);
  const [tutorTexto, setTutorTexto]           = useState("");
  const [tutorErro, setTutorErro]             = useState("");
  // true quando o backend recusou a chamada por limite diário de tokens
  // (429 -> QuotaExceededException, ver api.js) -- some pra um modal
  // dedicado em vez de aparecer como texto de erro dentro do modal do tutor.
  const [isQuotaModalOpen, setIsQuotaModalOpen] = useState(false);

  // Tutor Inteligente Evolutivo: explica por que a alternativa ERRADA
  // escolhida está incorreta (diferente do Tutor geral acima), com cache
  // versionado + feedback 👍/👎 no backend (ver pedirExplicacaoErro).
  const [erroExplicacaoAberto, setErroExplicacaoAberto]         = useState(false);
  const [erroExplicacaoCarregando, setErroExplicacaoCarregando] = useState(false);
  const [erroExplicacaoTexto, setErroExplicacaoTexto]           = useState("");
  const [erroExplicacaoVersao, setErroExplicacaoVersao]         = useState(1);
  const [erroExplicacaoLimite, setErroExplicacaoLimite]         = useState(false);
  const [erroExplicacaoErro, setErroExplicacaoErro]             = useState("");
  // Controla a UI de feedback: null = ainda não decidiu, "motivo" = abriu
  // o campo de texto do 👎, "enviado" = já mandou feedback (👍 ou 👎).
  const [feedbackEstado, setFeedbackEstado]     = useState(null);
  const [motivoTexto, setMotivoTexto]           = useState("");
  const [enviandoFeedback, setEnviandoFeedback] = useState(false);

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

  function _temQuizPronto(c) {
    return Array.isArray(c.options) && c.options.length >= 3 && !!c.explanation;
  }

  // Auto-cura: cards sem quiz pré-gerado (tipicamente criados manualmente,
  // nunca passaram por "Gerar com IA") seriam descartados em silêncio por
  // montarFila(). Em vez disso, tenta reparar na hora via POST
  // /study/cards/enrich antes de montar a fila — o usuário só percebe o
  // tempo extra de IA, nunca a causa (card sem dado no banco).
  async function _repararSemQuiz(cards) {
    const semQuizIds = cards.filter(c => !_temQuizPronto(c)).map(c => c.id);
    if (semQuizIds.length === 0) return cards;

    setReparando(true);
    try {
      // O backend aceita até 20 ids por chamada (mesmo teto de
      // /decks/{id}/quiz), pra manter o prompt e a resposta da IA previsíveis.
      const lotes = [];
      for (let i = 0; i < semQuizIds.length; i += 20) lotes.push(semQuizIds.slice(i, i + 20));

      const corrigidos = new Map();
      for (const lote of lotes) {
        const { enriched } = await api.enriquecerCards(lote);
        enriched.forEach(e => corrigidos.set(e.card_id, e));
      }

      return cards.map(c => {
        const fix = corrigidos.get(c.id);
        return fix ? { ...c, options: fix.options, explanation: fix.explanation } : c;
      });
    } catch {
      // IA fora do ar ou erro de rede — não trava a tela: os cards que
      // continuarem sem quiz são descartados por montarFila(), igual já
      // acontecia antes da auto-cura existir (ver tela de "Sem questões
      // disponíveis", que agora oferece o Modo Estudo clássico como saída).
      return cards;
    } finally {
      setReparando(false);
    }
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
      .then(_repararSemQuiz)
      .then(_iniciarComCards)
      .catch(err => setErro(err.message))
      .finally(() => setCarregando(false));
  }

  useEffect(() => {
    if (mostrarPrompt) return; // aguarda decisão do usuário sobre a sessão salva
    _carregarDoServidor();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck?.id, modoGlobal, folderId]);

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
  // modoPratica também barra o save aqui — sem essa trava, o "Rever
  // Vilões" reaproveita `fila`/`concluido=false` pra rodar a mesma UI de
  // pergunta, e esse efeito escreveria um snapshot com só o subconjunto de
  // vilões. Um F5 nesse momento leria esse snapshot errado e ofereceria
  // "continuar" uma sessão que não é a sessão real — a real já foi salva e
  // encerrada antes da prática começar (ver reverViloes()).
  useEffect(() => {
    if (mostrarPrompt || concluido || fila.length === 0 || modoPratica) return;
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
  }, [fila, acertosNaPrimeira, concluido, mostrarPrompt, resposta, modoPratica]);

  // Sessão chegou ao fim (equivalente a SessaoConcluida) → limpa o snapshot
  // e comemora (só na primeira vez -- ver confetiSessaoDisparado acima).
  useEffect(() => {
    if (!concluido) return;
    limpar();
    if (!confetiSessaoDisparado.current) {
      confetiSessaoDisparado.current = true;
      comemorarSessaoConcluida();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [concluido]);

  const questaoAtual = fila[0] ?? null;
  const respondeu    = resposta !== null;

  // Nova questão -> nova explicação do tutor (limpa o cache local anterior).
  useEffect(() => {
    setTutorAberto(false);
    setTutorTexto("");
    setTutorErro("");
    setErroExplicacaoAberto(false);
    setErroExplicacaoTexto("");
    setErroExplicacaoErro("");
    setErroExplicacaoVersao(1);
    setErroExplicacaoLimite(false);
    setFeedbackEstado(null);
    setMotivoTexto("");
  }, [questaoAtual?.card_id]);

  async function pedirTutor() {
    setTutorAberto(true);
    setTutorErro("");
    if (tutorTexto) return; // já carregado pra este card, só reabre o modal
    setTutorCarregando(true);
    try {
      const { explanation } = await api.tutorExplicarCard(questaoAtual.card_id);
      setTutorTexto(explanation);
    } catch (e) {
      if (e instanceof QuotaExceededException) {
        // Modal dedicado assume o lugar do modal do tutor -- não faz
        // sentido mostrar os dois ao mesmo tempo.
        setTutorAberto(false);
        setIsQuotaModalOpen(true);
      } else {
        setTutorErro(e.message || "Não foi possível carregar a explicação do tutor.");
      }
    } finally {
      setTutorCarregando(false);
    }
  }

  // Texto da alternativa ERRADA que o usuário escolheu (a letra sozinha
  // não serve de chave -- é embaralhada a cada carregamento, ver
  // montarFila -- por isso o backend cacheia pelo texto).
  function _alternativaEscolhidaTexto() {
    return questaoAtual?.options.find(o => o.letter === resposta)?.text ?? "";
  }

  async function pedirExplicacaoErro() {
    setErroExplicacaoAberto(true);
    setErroExplicacaoErro("");
    if (erroExplicacaoTexto) return; // já carregado pra este card+alternativa
    setErroExplicacaoCarregando(true);
    try {
      const { explanation, versao } = await api.explicarErroCard(questaoAtual.card_id, _alternativaEscolhidaTexto());
      setErroExplicacaoTexto(explanation);
      setErroExplicacaoVersao(versao);
    } catch (e) {
      if (e instanceof QuotaExceededException) {
        setErroExplicacaoAberto(false);
        setIsQuotaModalOpen(true);
      } else {
        setErroExplicacaoErro(e.message || "Não foi possível carregar a explicação.");
      }
    } finally {
      setErroExplicacaoCarregando(false);
    }
  }

  async function enviarFeedbackPositivo() {
    setEnviandoFeedback(true);
    try {
      await api.feedbackErroCard(questaoAtual.card_id, _alternativaEscolhidaTexto(), true);
    } catch {
      // Continua best-effort -- não vale travar o fluxo de estudo por um
      // 👍 que não salvou, a explicação já foi mostrada. A diferença agora
      // é que isso não fica mais em silêncio total: antes a tela dizia
      // "Obrigado pelo feedback!" mesmo quando a chamada tinha falhado de
      // verdade, dando a entender (falsamente) que foi registrado.
      mostrarToast("Não deu pra registrar seu feedback agora, mas pode seguir estudando.");
    } finally {
      setFeedbackEstado("enviado");
      setEnviandoFeedback(false);
    }
  }

  async function enviarMotivoNegativo() {
    if (!motivoTexto.trim()) return;
    setEnviandoFeedback(true);
    setErroExplicacaoErro("");
    try {
      const { explanation, versao, limite_atingido } = await api.feedbackErroCard(
        questaoAtual.card_id, _alternativaEscolhidaTexto(), false, motivoTexto.trim(),
      );
      setErroExplicacaoTexto(explanation);
      setErroExplicacaoVersao(versao);
      setErroExplicacaoLimite(!!limite_atingido);
      setFeedbackEstado("enviado");
      setMotivoTexto("");
    } catch (e) {
      if (e instanceof QuotaExceededException) {
        setErroExplicacaoAberto(false);
        setIsQuotaModalOpen(true);
      } else {
        setErroExplicacaoErro(e.message || "Não foi possível enviar o feedback.");
      }
    } finally {
      setEnviandoFeedback(false);
    }
  }

  // Mantém ref atualizada para o handler de teclado (evita stale closure)
  useEffect(() => { proximoRef.current = proximo; });

  // Incrementa a contagem de erros do card (usado tanto pelo clique quanto
  // pelo atalho de teclado, pra não duplicar a lógica em dois lugares).
  function _registrarErro(cardId) {
    // No "praticar de novo" o resumo da sessão real já foi calculado e
    // salvo -- contar erro aqui inventaria vilões numa sessão encerrada.
    // No "rever vilões" continua contando: lá o erro é o assunto.
    if (modoPratica === "tudo") return;
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
          if (opt.letter !== atual.correct_letter) {
            _registrarErro(atual.card_id);
          } else if (modoPratica === "viloes") {
            // Mesma marcação de escolher() (clique do mouse) -- sem isso, um
            // vilão respondido certo só pelo teclado nunca some do resumo
            // (bug real reportado: "refiz os dois vilões umas 3 vezes e ele
            // não sumiu", sempre pelos atalhos 1-4 que a própria tela sugere).
            viloesResolvidos.current.add(atual.card_id);
            comemorarVilaoResolvido();
          }
        }
      }
      if (respondeu && (e.key === " " || e.key === "Enter")) {
        e.preventDefault();
        proximoRef.current?.();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [concluido, semQuiz, carregando, fila, respondeu, modoPratica]);
  const acertouAtual = respondeu && questaoAtual
    ? resposta === questaoAtual.correct_letter
    : false;

  function escolher(letter) {
    if (respondeu) return;
    setResposta(letter);
    if (letter !== fila[0].correct_letter) {
      _registrarErro(fila[0].card_id);
    } else if (modoPratica === "viloes") {
      // Acertou um vilão durante a prática — marca resolvido sem tocar em
      // errosPorCard (que precisa manter a contagem original de erros).
      viloesResolvidos.current.add(fila[0].card_id);
      comemorarVilaoResolvido();
    }
  }

  async function proximo() {
    if (concluindoAnimacao) return; // trava clique duplo/Enter repetido durante a linha de chegada

    const atual   = fila[0];
    const acertou = resposta === atual.correct_letter;

    if (acertou) {
      const novaFila = fila.slice(1);
      // Numa rodada de treino o resumo da sessão real JÁ foi calculado e
      // salvo -- somar acertos aqui inflaria o anel de % pra além de 100%.
      if (!modoPratica && !errosPorCard.current.has(atual.card_id)) {
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
        if (!modoPratica) _salvarProgresso();
        setTimeout(() => {
          setConcluido(true);
          setConcluindoAnimacao(false);
          if (modoPratica) setModoPratica(null);
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
    // Grava TODAS as respostas na fila local primeiro (ver outbox.js) --
    // é isso que garante que fechar o app, ficar sem sinal ou dar F5 não
    // perde mais nada. Só depois tenta enviar. Substitui o comRetry do
    // Nível 1: quem re-tenta agora é a própria fila, nos gatilhos dela
    // (volta da conexão, abertura do app, aba voltando a ficar visível).
    let semDisco = 0;
    questoesOriginais.current.forEach(q => {
      const fase = startingReps.current[q.card_id] ?? 0;
      const errou = (errosPorCard.current.get(q.card_id) ?? 0) > 0;

      let quality;
      if (fase === 0)                quality = errou ? 3 : 4; // Novo: limpo=4, com erro=3 — nunca cai no Crítico Imediato (quality<3)
      else if (fase === 1 && errou)  quality = 2;              // Validando + erro: reseta (Crítico Imediato), penalidade mais leve que Dominado
      else if (fase === 1 && !errou) quality = 5;              // Validando sem erro: avança pra Dominado
      else if (fase >= 2 && !errou)  quality = 5;              // Dominado sem erro: estende
      else                            quality = 1;              // Dominado com erro: volta à Fase 1

      if (!enfileirar({ cardId: q.card_id, quality, ignorarElegibilidade: true })) {
        semDisco++;
      }
    });

    // Ficar guardada esperando conexão é o caminho NORMAL da fila -- não
    // rende aviso nenhum (a faixa de offline já explica o contexto, e
    // anunciar mecânica de sincronização só transforma o normal em evento).
    // O único caso que fala é o que realmente ameaça o progresso: o
    // navegador não deixou gravar em disco (janela anônima, armazenamento
    // cheio), então a resposta só existe em memória e não sobrevive a
    // fechar o app.
    const sync = await sincronizar();
    if (semDisco > 0 && contar() > 0) {
      mostrarToast(
        "Este navegador não está deixando guardar seu progresso. Se fechar o app " +
        "sem conexão, as respostas desta sessão se perdem.",
      );
    }

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

    // Fila Única: o que sobrou pra hoje? Só vale perguntar se TODAS as
    // respostas já chegaram ao servidor -- com algo ainda na fila offline,
    // ele devolveria os mesmos cards desta rodada. Reusa a própria busca
    // do lote (e não uma contagem à parte) por dois motivos: o número que
    // sai daqui é o mesmo "15+" que a Home mostra, e o lote já vem pronto
    // pra começar na hora se a pessoa clicar em Continuar. Sem rede, fica
    // em null e a tela não promete nada.
    if (modoGlobal && sync.restantes === 0) {
      _buscarCards().then(setProximoLote).catch(() => setProximoLote(null));
    }
  }

  /**
   * Repete a sessão inteira, só pra treinar.
   *
   * Substitui o antigo `reiniciarSessao`, que refazia a sessão VALENDO:
   * cada card era respondido de novo no servidor minutos depois de ter
   * sido aprendido, e o SM-2 (com ignorar_elegibilidade ligado) tratava
   * aquilo como uma revisão espaçada de verdade. Medido: card novo
   * acertado ia pra "volta em 1 dia"; um clique no botão o levava pra
   * "volta em 6 dias" com selo de Dominado. Ou seja, a tela chamava de
   * "consolidar" o ato de PULAR a consolidação -- justamente o que a
   * repetição espaçada existe pra evitar.
   *
   * Agora é como o "Rever vilões" sempre foi: segunda passada em memória,
   * sem tocar no servidor e sem mexer no agendamento.
   */
  function praticarDeNovo() {
    setModoPratica("tudo");
    setResposta(null);
    setFila(questoesOriginais.current);
    setConcluido(false);
  }

  /**
   * Fila Única: começa a próxima rodada com o lote que _salvarProgresso já
   * buscou. É uma sessão NOVA de verdade (grava no servidor, salva
   * snapshot de F5), não uma prática -- por isso zera tudo o que o resumo
   * anterior usava, inclusive o confete, que é por sessão.
   */
  function continuarProximoLote() {
    const cards = proximoLote;
    if (!cards || cards.length === 0) return;
    setProximoLote(null);
    errosPorCard.current = new Map();
    viloesResolvidos.current = new Set();
    confetiSessaoDisparado.current = false;
    setAcertosNaPrimeira(0);
    setTempoSessao(0);
    setResposta(null);
    setModoPratica(null);
    setConcluido(false);
    setCarregando(true);
    _repararSemQuiz(cards)
      .then(_iniciarComCards)
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
    setTotalViloes(viloes.length);
    setModoPratica("viloes");
    setResposta(null);
    setFila(viloes);
    setConcluido(false);
  }

  // Durante o "Rever Vilões", Voltar não sai da tela — volta pro resumo da
  // sessão real (que já foi salva). Fora desse modo, comportamento normal.
  function voltarOuSairDaPratica() {
    if (modoPratica) {
      setModoPratica(null);
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
          {modoPratica ? "← Voltar ao resumo" : "← Voltar"}
        </button>
        <span className="estudo-deck-nome">
          {modoGlobal
            ? (folderName ? `Revisão do Dia — ${folderName}` : "Revisão Geral do Dia")
            : deck.title}
        </span>
      </div>
      <div className="topo-direita">
        <span className="modo-label">{
          modoPratica === "viloes" ? "Revisão de vilões"
          : modoPratica === "tudo" ? "Praticando — não conta"
          : "Múltipla escolha"
        }</span>
        <ToggleTema />
      </div>
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
          <p className="vazio">
            {reparando ? "Preparando seu material de estudo…" : "Carregando cards…"}
          </p>
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
    // Chegou aqui depois de _repararSemQuiz() já ter tentado consertar
    // sozinho — se ainda assim não sobrou nenhuma questão, a IA falhou ou
    // está indisponível agora, não é falta de tentativa.
    return (
      <div className="pagina">{cabecalho}
        <main className="conteudo estudo-centro">
          <div className="estudo-concluido">
            <div className="estudo-concluido-icone">✦</div>
            <h2 className="estudo-concluido-titulo">Não foi possível preparar o quiz agora</h2>
            <p className="estudo-concluido-sub">
              {modoGlobal
                ? 'Tentamos gerar as alternativas automaticamente pros cards vencidos, mas não deu certo agora (a IA pode estar indisponível). Tente de novo em instantes, ou entre em cada deck e use a aba "Gerar com IA".'
                : 'Tentamos gerar as alternativas automaticamente, mas não deu certo agora (a IA pode estar indisponível). Tente de novo em instantes, use a aba "Gerar com IA" na tela de Cards, ou estude esses cards no modo clássico enquanto isso.'}
            </p>
            <div className="gamificado-botoes">
              <button className="botao-principal estudo-concluido-botao" onClick={sair}>
                {modoGlobal ? "Voltar à Home" : "Voltar ao deck"}
              </button>
              {!modoGlobal && aoEstudoClassico && (
                <button className="botao-texto" onClick={aoEstudoClassico}>
                  Estudar no modo clássico
                </button>
              )}
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ─── Resultado ─────────────────────────────────────────────────────────
  if (concluido) {
    const pct = totalUnicos > 0
      ? Math.round((acertosNaPrimeira / totalUnicos) * 100) : 0;

    const novosDominados = questoesOriginais.current.filter(
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
              {novosDominados > 0 && (
                <div className="sessao-stat verde">
                  <span className="sessao-stat-valor">+{novosDominados}</span>
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

            {/* No lugar do bloco de persuasão ("vamos consolidar? …DOMÍNIO
                permanente"): o fato. Dizer quando o card volta informa E
                ensina o app a funcionar -- é o que traz a pessoa de volta
                amanhã. Prometer domínio por uma rodada extra hoje era
                promessa que o algoritmo não cumpre. */}
            {avancadosParaValidacao > 0 && (
              <p className="sessao-proximo">
                {avancadosParaValidacao} card{avancadosParaValidacao !== 1 ? "s" : ""} novo
                {avancadosParaValidacao !== 1 ? "s" : ""} aprendido
                {avancadosParaValidacao !== 1 ? "s" : ""}.{" "}
                {avancadosParaValidacao !== 1 ? "Eles voltam" : "Ele volta"} amanhã.
              </p>
            )}

            {/* Fila Única: esta rodada era um lote. Diz o que sobrou (no
                mesmo "15+" da Home) ou que zerou -- antes a tela calava e
                a pessoa descobria de volta na Home. */}
            {modoGlobal && proximoLote !== null && (
              <p className="sessao-proximo sessao-restante">
                {proximoLote.length === 0
                  ? (folderName ? "Você zerou a revisão de hoje nesta pasta." : "Você zerou a revisão de hoje.")
                  : `Ainda ${proximoLote.length === 1 ? "tem 1 card vencido" : `tem ${rotuloRestante(proximoLote.length)} cards vencidos`} esperando. Dá pra continuar agora ou deixar pra depois.`}
              </p>
            )}

            {/* Terminar a sessão é o sucesso -- é a ação principal. Na
                Fila Única com lote sobrando, continuar É o que a pessoa
                pediu ao clicar em "Estudar Tudo", então assume o lugar. */}
            <div className="sessao-acoes">
              {modoGlobal && proximoLote?.length > 0 ? (
                <>
                  <button className="botao-principal estudo-concluido-botao"
                    onClick={continuarProximoLote} disabled={salvando}>
                    Continuar · {rotuloRestante(proximoLote.length)} restante{proximoLote.length !== 1 ? "s" : ""}
                  </button>
                  <button className="botao-texto" onClick={sair} disabled={salvando}>
                    Voltar à Home
                  </button>
                </>
              ) : (
                <button className="botao-principal estudo-concluido-botao"
                  onClick={sair} disabled={salvando}>
                  {salvando ? "Salvando…" : modoGlobal ? "Voltar à Home" : "Voltar ao deck"}
                </button>
              )}
              <button className="botao-texto" onClick={praticarDeNovo} disabled={salvando}
                title="Repete os cards agora, sem mudar quando eles voltam">
                Praticar de novo
              </button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // ─── Questão ───────────────────────────────────────────────────────────
  //
  // O número aqui conta CARDS CONCLUÍDOS (saíram da fila por acerto), não
  // perguntas respondidas -- errar devolve o card pra fila, então ele
  // continua pendente. Isso está certo, e a barra mede exatamente isso.
  //
  // O que estava errado era o RÓTULO: "Card 2 de 6" se lê como "pergunta 2
  // de 6", e a pessoa via o número travado na 4ª pergunta achando que
  // estava patinando. Medido: 1 acerto + 2 erros = tela na 4ª pergunta
  // dizendo "Card 2 de 6". Agora o texto diz o que o número é.
  //
  // Durante o "Rever vilões" a base é outra: a fila tem só os vilões, mas
  // totalUnicos continua sendo o total da sessão -- daí "5 de 6" numa
  // prática de 2 cards. Por isso totalDaEtapa.
  const totalDaEtapa    = modoPratica === "viloes" ? totalViloes : totalUnicos;
  const cardIdsNaFila   = new Set(fila.map(q => q.card_id));
  const cardsConcluidos = Math.max(0, totalDaEtapa - cardIdsNaFila.size);

  // Cards que você errou e ainda vão reaparecer. A conta antiga
  // (fila.length - ids distintos) dava SEMPRE zero -- errar move o card
  // dentro da fila, nunca duplica -- então esse aviso nunca apareceu na
  // vida. É justamente ele que explica por que o contador não anda.
  // Na prática de vilões não faz sentido: lá todo card é um erro.
  const aguardandoReacerto = modoPratica
    ? 0
    : fila.filter(q => (errosPorCard.current.get(q.card_id) ?? 0) > 0).length;

  return (
    <div className="pagina">{cabecalho}
      <main className="conteudo estudo-centro">
        <div className="quiz-progresso">
          <span className="quiz-progresso-contador">
            {modoPratica === "viloes"
              ? `Vilão ${Math.min(cardsConcluidos + 1, totalDaEtapa)} de ${totalDaEtapa}`
              : `${cardsConcluidos} de ${totalDaEtapa} concluídos`}
          </span>
          <div className="quiz-barra">
            <div className="quiz-barra-fill"
              style={{ width: `${concluindoAnimacao ? 100 : (cardsConcluidos / totalDaEtapa) * 100}%` }} />
          </div>
          {aguardandoReacerto > 0 && (
            <span className="quiz-repetindo"
              title="Cards que você errou — eles voltam antes de a sessão terminar">
              ↺ {aguardandoReacerto} {aguardandoReacerto === 1 ? "volta" : "voltam"}
            </span>
          )}
          <SeloOffline />
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
              <div className="quiz-explicacao-acoes">
                {/* Offline: desabilita em vez de deixar clicar e tomar erro --
                    é a diferença entre "app limitado agora" e "app quebrado". */}
                <button className="botao-texto tutor-botao" onClick={pedirTutor}
                  disabled={!online} title={online ? undefined : "Precisa de internet — disponível quando a conexão voltar"}>
                  Perguntar ao Tutor
                </button>
                {!acertouAtual && (
                  <button className="botao-texto tutor-botao" onClick={pedirExplicacaoErro}
                    disabled={!online} title={online ? undefined : "Precisa de internet — disponível quando a conexão voltar"}>
                    Por que errei?
                  </button>
                )}
              </div>
              <button className="botao-principal" onClick={proximo} disabled={concluindoAnimacao}>
                {acertouAtual && cardsConcluidos + 1 >= totalUnicos
                  ? "Ver resultado" : "Próxima →"}
              </button>
              <span className="revelar-kbd"><kbd>Space</kbd> / <kbd>Enter</kbd> para avançar</span>
            </div>
          )}
        </div>
      </main>

      <Modal aberto={tutorAberto} aoFechar={() => setTutorAberto(false)}
        titulo="Tutor Inteligente" className="modal-tutor">
            {tutorCarregando && <p className="tutor-status">Pensando na melhor forma de explicar…</p>}
            {tutorErro && !tutorCarregando && <p className="tutor-status tutor-status-erro">{tutorErro}</p>}
            {tutorTexto && !tutorCarregando && !tutorErro && (
              <div className="tutor-conteudo">
                <ReactMarkdown>{tutorTexto}</ReactMarkdown>
              </div>
            )}
      </Modal>

      <Modal aberto={erroExplicacaoAberto} aoFechar={() => setErroExplicacaoAberto(false)}
        titulo="Por que essa alternativa está errada?" className="modal-tutor">
            {erroExplicacaoVersao > 1 && !erroExplicacaoCarregando && (
              <span className="erro-feedback-versao">explicação refinada — v{erroExplicacaoVersao}</span>
            )}
            {erroExplicacaoCarregando && <p className="tutor-status">Pensando na melhor forma de explicar…</p>}
            {erroExplicacaoErro && !erroExplicacaoCarregando && (
              <p className="tutor-status tutor-status-erro">{erroExplicacaoErro}</p>
            )}
            {erroExplicacaoTexto && !erroExplicacaoCarregando && !erroExplicacaoErro && (
              <>
                <div className="tutor-conteudo">
                  <ReactMarkdown>{erroExplicacaoTexto}</ReactMarkdown>
                </div>

                {erroExplicacaoLimite ? (
                  <p className="erro-feedback-limite">
                    Já refinamos essa explicação o máximo possível por hoje.
                  </p>
                ) : feedbackEstado === "enviado" ? (
                  <p className="erro-feedback-obrigado">Obrigado pelo feedback!</p>
                ) : feedbackEstado === "motivo" ? (
                  <div className="erro-feedback-motivo">
                    <textarea
                      className="erro-feedback-textarea"
                      placeholder="O que faltou nessa explicação?"
                      value={motivoTexto}
                      onChange={e => setMotivoTexto(e.target.value)}
                    />
                    <div className="erro-feedback-motivo-botoes">
                      <button
                        className="botao-principal"
                        disabled={enviandoFeedback || !motivoTexto.trim()}
                        onClick={enviarMotivoNegativo}
                      >
                        {enviandoFeedback ? "Enviando…" : "Enviar"}
                      </button>
                      <button className="botao-texto" onClick={() => setFeedbackEstado(null)}>Cancelar</button>
                    </div>
                  </div>
                ) : (
                  <div className="erro-feedback-botoes">
                    <span className="erro-feedback-pergunta">Essa explicação te ajudou?</span>
                    <button
                      className="erro-feedback-btn"
                      onClick={enviarFeedbackPositivo}
                      disabled={enviandoFeedback}
                      aria-label="Gostei"
                    >👍</button>
                    <button
                      className="erro-feedback-btn"
                      onClick={() => setFeedbackEstado("motivo")}
                      disabled={enviandoFeedback}
                      aria-label="Não gostei"
                    >👎</button>
                  </div>
                )}
              </>
            )}
      </Modal>

      <QuotaLimitModal aberto={isQuotaModalOpen} aoFechar={() => setIsQuotaModalOpen(false)} />
    </div>
  );
}

// O lote tem teto de 15: quando vêm 15, pode haver mais -- o mesmo "15+"
// que a Home usa (rotuloPendentes em Dashboard.jsx), pra nunca mostrar
// aqui um número que a Home contradiga.
function rotuloRestante(n) {
  return n >= 15 ? "15+" : String(n);
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
