import { useState, useEffect, useRef, useCallback } from "react";
import { api, NetworkException } from "../api.js";
import useOnline from "../hooks/useOnline.js";
import ToggleTema from "../components/ToggleTema.jsx";
import SeloOffline from "../components/SeloOffline.jsx";
import { audioGuardado, gerarAudio, removerAudio, urlDoAudio } from "../audioDecks.js";

const VELOCIDADES = [1, 1.25, 1.5, 2];

function mmss(s) {
  if (!Number.isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

function mb(bytes) {
  return `${(bytes / 1048576).toFixed(1).replace(".", ",")} MB`;
}

function quandoFoi(iso) {
  const dias = Math.floor((Date.now() - new Date(iso)) / 86400000);
  if (dias <= 0) return "hoje";
  if (dias === 1) return "ontem";
  return `há ${dias} dias`;
}

/**
 * Tela de escuta de um deck ("Ouvir").
 *
 * Diferente dos outros modos: o áudio não existe até alguém mandar
 * gerar, custa dinheiro pra nascer e ocupa espaço no aparelho. Daí a
 * tela ter ciclo de vida, não só um player.
 *
 * O ROTEIRO (texto do diálogo) mora no servidor; o ÁUDIO mora só neste
 * aparelho, na Cache API. Por isso existe o estado do meio -- roteiro
 * pronto, áudio ainda não gravado aqui -- que é o que se vê ao abrir o
 * mesmo deck num segundo aparelho: nesse caso regravar custa só a
 * locução, não a escrita.
 */
export default function Ouvir({ deck, aoVoltar }) {
  const online = useOnline();

  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [servidor, setServidor] = useState(null);   // { existe, desatualizado, capitulos, ... }
  const [local, setLocal] = useState(null);         // registro do aparelho, ou null
  const [progresso, setProgresso] = useState(null); // { feitos, total } enquanto grava

  const [url, setUrl] = useState(null);
  const [tocando, setTocando] = useState(false);
  const [pos, setPos] = useState(0);
  const [dur, setDur] = useState(0);
  const [velocidade, setVelocidade] = useState(1);

  const audioRef = useRef(null);
  const abortRef = useRef(null);

  const carregar = useCallback(async () => {
    setErro("");
    const guardado = audioGuardado(deck.id);
    try {
      setServidor(await api.audioDoDeck(deck.id));
    } catch (e) {
      // Sem rede, mas com o áudio no aparelho: isto não é um erro pra
      // quem veio ouvir -- é exatamente o caso que a tela promete
      // atender. Quem conta que está offline é a faixa do rodapé, uma
      // vez, como no resto do app (ver o comentário sobre toast por
      // request em api.js). O que se perde é só saber se o áudio
      // envelheceu, e isso reaparece sozinho quando a conexão voltar.
      if (!(e instanceof NetworkException) || !guardado) setErro(e.message);
    } finally {
      setLocal(guardado);
      setCarregando(false);
    }
  }, [deck.id]);

  useEffect(() => { carregar(); }, [carregar]);

  // Sair da tela no meio da gravação interrompe a fila no fim do bloco
  // atual, nunca no meio -- abortar uma síntese já paga não devolveria a
  // cota. O bloco concluído fica guardado no aparelho (ver
  // audioDecks.js), então voltar pra cá retoma de onde parou em vez de
  // pagar tudo de novo.
  useEffect(() => () => abortRef.current?.abort(), []);

  // A URL do blob é criada sob demanda e revogada ao trocar de áudio ou
  // sair: sem revogar, o blob fica preso na memória da aba até recarregar.
  useEffect(() => {
    let vivo = true;
    let atual = null;
    if (!local) { setUrl(null); return undefined; }
    urlDoAudio(deck.id).then(u => {
      if (!vivo) { if (u) URL.revokeObjectURL(u); return; }
      atual = u;
      setUrl(u);
    });
    return () => { vivo = false; if (atual) URL.revokeObjectURL(atual); };
  }, [deck.id, local]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = velocidade;
  }, [velocidade, url]);

  async function gravar() {
    setErro("");
    setProgresso({ feitos: 0, total: servidor?.total_blocos ?? 0 });
    abortRef.current = new AbortController();
    try {
      const registro = await gerarAudio(deck.id, {
        aoAvancar: setProgresso,
        sinal: abortRef.current.signal,
      });
      setLocal(registro);
      setServidor(await api.audioDoDeck(deck.id));
    } catch (e) {
      if (e.name !== "AbortError") setErro(e.message);
    } finally {
      setProgresso(null);
    }
  }

  async function regravar() {
    setErro("");
    try {
      await api.criarRoteiroDeAudio(deck.id, { refazer: true });
      await removerAudio(deck.id);
      setLocal(null);
      await gravar();
    } catch (e) {
      setErro(e.message);
    }
  }

  async function apagar() {
    await removerAudio(deck.id);
    setLocal(null);
    setTocando(false);
  }

  function pular(segundos) {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = Math.max(0, Math.min(a.duration || 0, a.currentTime + segundos));
  }

  function irPara(segundos) {
    if (audioRef.current) audioRef.current.currentTime = segundos;
  }

  const capitulos = servidor?.capitulos ?? local?.capitulos ?? [];
  // Cada bloco vira um capítulo; o início de cada um é proporcional ao
  // texto que o antecede. É estimativa, não marcação exata -- o
  // servidor não devolve a duração por bloco, e pedir isso custaria
  // guardar o áudio lá (fase 3).
  const totalChars = capitulos.reduce((s, c) => s + (c.caracteres || 0), 0);
  let acumulado = 0;
  const comInicio = capitulos.map(c => {
    const inicio = totalChars > 0 && dur > 0 ? (acumulado / totalChars) * dur : 0;
    acumulado += c.caracteres || 0;
    return { ...c, inicio_s: inicio };
  });
  const indiceAtual = comInicio.findIndex((c, i) => {
    const fim = comInicio[i + 1]?.inicio_s ?? dur;
    return pos >= c.inicio_s && pos < fim;
  });

  return (
    <div className="pagina">
      <header className="topo">
        <div className="topo-esquerda">
          <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
          <span className="estudo-deck-nome">{deck.title}</span>
          {local && <SeloOffline />}
        </div>
        <div className="topo-direita"><ToggleTema /></div>
      </header>

      <main className="conteudo ouvir-main">
        {carregando && <p className="ouvir-nota-offline">Carregando…</p>}
        {erro && <p className="erro">{erro}</p>}

        {/* ---------- Gravando ---------- */}
        {progresso && (
          <div className="ouvir-gerando">
            <div className="ouvir-vazio-icone" aria-hidden="true">🎙️</div>
            <h1 className="ouvir-vazio-titulo">Gravando a conversa…</h1>
            <div className="ouvir-progresso-trilha">
              <div className="ouvir-progresso-preenchido"
                   style={{ width: `${progresso.total ? (progresso.feitos / progresso.total) * 100 : 5}%` }} />
            </div>
            <p className="ouvir-progresso-texto">
              {progresso.total
                ? `Trecho ${progresso.feitos} de ${progresso.total}`
                : "Escrevendo o roteiro…"}
            </p>
            <p className="ouvir-nota-offline">
              Mantenha esta tela aberta até terminar. Se sair, os trechos já gravados
              ficam salvos e você continua de onde parou.
            </p>
          </div>
        )}

        {/* ---------- Nada ainda ---------- */}
        {!carregando && !progresso && !local && (
          <div className="ouvir-vazio">
            <div className="ouvir-vazio-icone" aria-hidden="true">🎧</div>
            <h1 className="ouvir-vazio-titulo">
              {servidor?.existe ? "Falta gravar neste aparelho" : "Ouvir este deck"}
            </h1>
            <p className="ouvir-vazio-texto">
              {servidor?.existe
                ? "A conversa já está escrita. Falta gravar o áudio aqui — é mais rápido e mais barato do que da primeira vez."
                : `Duas pessoas conversam sobre os ${deck.total_cards ?? ""} cards deste deck, pra você revisar andando, no ônibus ou na academia — sem olhar a tela.`}
            </p>
            {!servidor?.existe && (
              <ul className="ouvir-vazio-fatos">
                <li>Uma conversa entre <strong>Rafael e Beatriz</strong></li>
                <li>Gravada <strong>uma vez</strong> — depois é só ouvir</li>
                <li>Fica <strong>no aparelho</strong>, toca sem internet</li>
              </ul>
            )}
            <button className="botao-principal ouvir-botao-gerar" onClick={gravar} disabled={!online}>
              {servidor?.existe ? "Gravar áudio" : "Gerar conversa"}
            </button>
            {!online && (
              <p className="ouvir-nota-offline">
                Precisa de internet pra gravar. Depois de pronto, o áudio toca offline.
              </p>
            )}
          </div>
        )}

        {/* ---------- Player ---------- */}
        {!progresso && local && (
          <>
            {servidor?.desatualizado && (
              <div className="ouvir-aviso-velho">
                <strong>Este áudio está atrasado.</strong> Os cards mudaram depois que
                ele foi gravado — essas mudanças não estão na conversa.
                <button className="botao-texto ouvir-aviso-acao" onClick={regravar} disabled={!online}>
                  Gravar de novo
                </button>
              </div>
            )}

            <audio
              ref={audioRef}
              src={url || undefined}
              onLoadedMetadata={e => setDur(e.currentTarget.duration || local.duracao_s || 0)}
              onTimeUpdate={e => setPos(e.currentTarget.currentTime)}
              onEnded={() => setTocando(false)}
              onPlay={() => setTocando(true)}
              onPause={() => setTocando(false)}
            />

            <div className="ouvir-player">
              <div className="ouvir-player-cabecalho">
                <h1 className="ouvir-player-titulo">{deck.title}</h1>
                <span className="ouvir-player-meta">
                  {mmss(dur || local.duracao_s)} · gravado {quandoFoi(local.gravadoEm)}
                </span>
              </div>

              <div className="ouvir-trilha-area">
                <div
                  className="ouvir-trilha"
                  role="slider"
                  tabIndex={0}
                  aria-label="Posição no áudio"
                  aria-valuemin={0}
                  aria-valuemax={Math.round(dur)}
                  aria-valuenow={Math.round(pos)}
                  aria-valuetext={`${mmss(pos)} de ${mmss(dur)}`}
                  onKeyDown={e => {
                    if (e.key === "ArrowRight") { e.preventDefault(); pular(5); }
                    if (e.key === "ArrowLeft") { e.preventDefault(); pular(-5); }
                  }}
                  onClick={e => {
                    const r = e.currentTarget.getBoundingClientRect();
                    irPara(((e.clientX - r.left) / r.width) * dur);
                  }}
                >
                  <div className="ouvir-trilha-preenchida"
                       style={{ width: `${dur ? (pos / dur) * 100 : 0}%` }} />
                  {comInicio.map(c => (
                    <span key={c.indice} className="ouvir-trilha-marca"
                          style={{ left: `${dur ? (c.inicio_s / dur) * 100 : 0}%` }} />
                  ))}
                </div>
                <div className="ouvir-tempos">
                  <span>{mmss(pos)}</span>
                  <span>−{mmss(dur - pos)}</span>
                </div>
              </div>

              <div className="ouvir-controles">
                <button className="ouvir-botao-pular" onClick={() => pular(-15)}
                        aria-label="Voltar 15 segundos">↺ 15</button>
                <button
                  className="ouvir-botao-play"
                  onClick={() => (tocando ? audioRef.current?.pause() : audioRef.current?.play())}
                  aria-label={tocando ? "Pausar" : "Tocar"}
                >
                  {tocando ? "❚❚" : "▶"}
                </button>
                <button className="ouvir-botao-pular" onClick={() => pular(15)}
                        aria-label="Avançar 15 segundos">15 ↻</button>
                <button
                  className="ouvir-botao-velocidade"
                  onClick={() => setVelocidade(v => VELOCIDADES[(VELOCIDADES.indexOf(v) + 1) % VELOCIDADES.length])}
                  aria-label={`Velocidade ${velocidade}x`}
                >
                  {String(velocidade).replace(".", ",")}×
                </button>
              </div>
            </div>

            {comInicio.length > 0 && (
              <section className="ouvir-capitulos">
                <h2 className="ouvir-capitulos-titulo">Na conversa</h2>
                <ul className="ouvir-capitulos-lista">
                  {comInicio.map((c, i) => (
                    <li key={c.indice}>
                      <button className={`ouvir-capitulo${i === indiceAtual ? " atual" : ""}`}
                              onClick={() => irPara(c.inicio_s)}>
                        <span className="ouvir-capitulo-tempo">{mmss(c.inicio_s)}</span>
                        <span className="ouvir-capitulo-nome">{c.titulo}</span>
                        {i === indiceAtual && <span className="ouvir-capitulo-agora">tocando</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section className="ouvir-acoes">
              <div className="ouvir-acao-linha">
                <div>
                  <span className="ouvir-acao-nome">No aparelho</span>
                  <span className="ouvir-acao-desc">
                    Ocupa {mb(local.bytes)}. Toca sem internet.
                  </span>
                </div>
                <button className="botao-modo-ghost" onClick={apagar}>Remover</button>
              </div>
              <div className="ouvir-acao-linha">
                <div>
                  <span className="ouvir-acao-nome">Gravar de novo</span>
                  <span className="ouvir-acao-desc">
                    Reescreve a conversa com a versão mais nova dos cards.
                  </span>
                </div>
                <button className="botao-modo-ghost" onClick={regravar} disabled={!online}>
                  Gravar
                </button>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
