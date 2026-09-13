import { useEffect, useState } from "react";
import { api, NetworkException } from "../api.js";
import { useToast } from "../hooks/ToastContext.jsx";
import useOnline from "../hooks/useOnline.js";
import ToggleTema from "../components/ToggleTema.jsx";
import TrocarSenhaModal from "../components/TrocarSenhaModal.jsx";

/**
 * Área da conta.
 *
 * Nasceu pra recolher o que estava espalhado pelo cabeçalho de TODAS as
 * telas (email, trocar senha, sair) e pra dar endereço ao que não tinha
 * nenhum. Está sendo montada por partes; esta é a primeira: identidade.
 *
 * O buraco concreto que a identidade fecha: no celular o email era
 * escondido por CSS (`.usuario-email { display: none }`), então não havia
 * como saber em qual conta você estava. Quem tem conta pessoal e de estudo
 * descobria pelo conteúdo -- ou não descobria.
 */
export default function Conta({ usuario, aoVoltar }) {
  const [trocandoSenha, setTrocandoSenha] = useState(false);
  const mostrarToast = useToast();
  const online = useOnline();

  return (
    <div className="pagina">
      <header className="topo">
        <div className="topo-esquerda">
          <button className="botao-texto" onClick={aoVoltar}>← Voltar</button>
          <span className="estudo-deck-nome">Sua conta</span>
        </div>
        <ToggleTema />
      </header>

      <main className="conteudo conta-conteudo">
        <section className="conta-bloco conta-identidade">
          <span className="conta-avatar" aria-hidden="true">
            {(usuario.email?.[0] ?? "?").toUpperCase()}
          </span>
          <div className="conta-identidade-texto">
            <span className="conta-email">{usuario.email}</span>
            {textoDesde(usuario.created_at) && (
              <span className="conta-desde">{textoDesde(usuario.created_at)}</span>
            )}
          </div>
        </section>

        <CotaDeIA />

        {/* A troca de senha morava no cabeçalho de TODAS as telas, por
            falta de lugar melhor. Aqui ela tem endereço, e o cabeçalho
            volta a caber no celular. */}
        <section className="conta-bloco conta-acoes">
          <div className="conta-acao">
            <div className="conta-acao-texto">
              <span className="conta-acao-titulo">Senha</span>
              <span className="conta-acao-sub">
                Não existe recuperação de senha no Estalo — guarde a sua em lugar seguro.
              </span>
            </div>
            <button className="botao-texto conta-acao-botao" onClick={() => setTrocandoSenha(true)}
              disabled={!online}
              title={online ? undefined : "Precisa de internet — disponível quando a conexão voltar"}>
              Trocar senha
            </button>
          </div>
        </section>
      </main>

      <TrocarSenhaModal
        aberto={trocandoSenha}
        aoFechar={() => setTrocandoSenha(false)}
        aoTrocar={() => mostrarToast("Senha trocada.", "sucesso")}
      />
    </div>
  );
}

/**
 * "No Estalo desde março de 2026".
 *
 * `created_at` sempre veio no /auth/me e nunca tinha sido usado em lugar
 * nenhum. Mês e ano bastam -- dia e hora do cadastro não dizem nada a
 * ninguém.
 *
 * Tolera ausência de propósito: uma identidade em cache de uma versão
 * anterior do app pode não ter o campo, e isso não é motivo pra quebrar a
 * página inteira (ver estalo_ultimo_usuario em App.jsx).
 */
function textoDesde(criadoEm) {
  if (!criadoEm) return "";
  const data = new Date(criadoEm);
  if (Number.isNaN(data.getTime())) return "";
  const quando = data.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
  return `No Estalo desde ${quando}`;
}

/**
 * Quanto de IA a conta já usou hoje.
 *
 * Antes disto, o limite era invisível até você bater nele: um modal
 * aparecia no meio de um Tutor dizendo que a cota acabou. Não havia
 * NENHUMA tela onde olhar antes. Aqui a informação existe sem alarme --
 * e a barra só ganha cor de alerta quando resta pouco.
 *
 * Falha em silêncio de propósito: se a cota não carregar (offline, por
 * exemplo), o bloco simplesmente não aparece. Um erro vermelho na área da
 * conta por causa de um número acessório seria pior que a ausência dele.
 */
function CotaDeIA() {
  const [cota, setCota] = useState(null);

  useEffect(() => {
    let vivo = true;
    api.minhaCota()
      .then(c => { if (vivo) setCota(c); })
      .catch(err => { if (!(err instanceof NetworkException)) console.error("[Conta] cota:", err.message); });
    return () => { vivo = false; };
  }, []);

  if (!cota) return null;

  const pct = cota.limite > 0 ? Math.min(100, Math.round((cota.consumido / cota.limite) * 100)) : 0;
  const apertado = pct >= 80;

  return (
    <section className="conta-bloco conta-cota">
      <div className="conta-cota-topo">
        <span className="conta-cota-titulo">Uso de IA hoje</span>
        <span className={`conta-cota-pct${apertado ? " apertado" : ""}`}>{pct}%</span>
      </div>
      <div className="conta-cota-barra">
        <div className={`conta-cota-fill${apertado ? " apertado" : ""}`} style={{ width: `${pct}%` }} />
      </div>
      {/* Sem "tokens": ninguém sabe quanto é um token, e o número exato não
          ajuda a decidir nada. O que importa é se dá pra continuar hoje. */}
      <p className="conta-cota-texto">
        {pct >= 100
          ? "Você usou toda a cota de hoje."
          : apertado
            ? "Resta pouco por hoje."
            : "Sobra bastante por hoje."}
        {" "}Serve pra gerar cards, o Tutor e as explicações.
      </p>
      <p className="conta-cota-renova">Renova {formatarRenovacao(cota.renova_em)}.</p>
    </section>
  );
}

/**
 * "hoje às 21:00" / "amanhã às 21:00".
 *
 * O backend devolve o instante em naive-UTC (o relógio do servidor é quem
 * manda no reset). Aqui vira horário de quem está lendo -- daí "amanhã às
 * 21h" pra quem está no Brasil, que é a verdade, por mais estranha que
 * pareça. Ver _proxima_virada no backend sobre por que não é meia-noite
 * local.
 */
function formatarRenovacao(iso) {
  const quando = new Date(`${iso}Z`); // naive-UTC: o Z é o que falta pro JS
  if (Number.isNaN(quando.getTime())) return "amanhã";
  const hora = quando.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const hoje = new Date();
  const mesmoDia = quando.toDateString() === hoje.toDateString();
  return `${mesmoDia ? "hoje" : "amanhã"} às ${hora}`;
}
