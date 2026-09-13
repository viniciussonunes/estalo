import ToggleTema from "../components/ToggleTema.jsx";

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
      </main>
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
