import { useId, useState } from "react";
import { api, token, NetworkException } from "../api.js";
import CampoSenha from "../components/CampoSenha.jsx";
import { TAMANHO_MINIMO_SENHA, validarSenha } from "../senha.js";

/**
 * Traduz a falha pra uma frase que ajuda.
 *
 * O backend já responde bem nos casos previstos ("Email ou senha
 * incorretos", "Esse email já está cadastrado") -- esses passam direto. O
 * que vazava cru era o resto: um "Erro 502" na cara de quem só queria
 * entrar, sem dizer se a culpa é da senha, da internet ou do servidor.
 */
function mensagemAmigavel(err) {
  if (err instanceof NetworkException) {
    return "Não conseguimos falar com o servidor. Verifique sua internet e tente de novo.";
  }
  const bruta = String(err?.message ?? "").trim();
  if (/^Erro 5\d\d$/.test(bruta)) {
    return "O servidor não respondeu agora. Espere alguns instantes e tente de novo.";
  }
  if (/^Erro 4\d\d$/.test(bruta)) {
    return "Não deu pra concluir. Confira os dados e tente de novo.";
  }
  return bruta || "Algo deu errado. Tente de novo.";
}

// Tela de login e cadastro. Um botão alterna entre os dois modos.
export default function Auth({ aoEntrar }) {
  const [modo, setModo] = useState("login"); // "login" ou "cadastro"
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);
  const idErro = useId();

  function trocarModo(novo) {
    setModo(novo);
    setErro("");
  }


  async function enviar(e) {
    e.preventDefault();
    setErro("");

    // Recusa o que dá pra saber aqui, sem gastar uma ida ao servidor. Só
    // no cadastro: no login, senha curta é problema do backend responder
    // "incorretos" -- dizer "curta demais" aqui contaria a um atacante que
    // aquela senha nem poderia existir.
    if (modo === "cadastro") {
      const problema = validarSenha(senha);
      if (problema) { setErro(problema); return; }
    }

    setEnviando(true);
    try {
      if (modo === "cadastro") {
        await api.registrar(email, senha);
      }
      // Tanto no cadastro quanto no login, no fim a gente loga.
      const { access_token } = await api.login(email, senha);
      token.set(access_token);
      const usuario = await api.eu();
      aoEntrar(usuario);
    } catch (err) {
      setErro(mensagemAmigavel(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="tela-centro">
      <div className="cartao-auth">
        <div className="marca">
          <span className="marca-nome">Estalo</span>
          <span className="marca-sub">o clique que fixa o que você estuda</span>
        </div>

        <div className="abas">
          <button
            type="button"
            className={modo === "login" ? "aba ativa" : "aba"}
            onClick={() => trocarModo("login")}
          >
            Entrar
          </button>
          <button
            type="button"
            className={modo === "cadastro" ? "aba ativa" : "aba"}
            onClick={() => trocarModo("cadastro")}
          >
            Criar conta
          </button>
        </div>

        <form onSubmit={enviar}>
          <label className="campo">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="voce@email.com"
              // Sem autocomplete o gerenciador de senhas preenche mal ou
              // não preenche -- e é ele que faz as pessoas usarem senha
              // boa. "username" é o que os gerenciadores procuram no campo
              // de identificação, mesmo quando ele é um email.
              autoComplete="username"
              aria-invalid={erro ? true : undefined}
              aria-describedby={erro ? idErro : undefined}
              required
            />
          </label>

          <CampoSenha
            rotulo="Senha"
            valor={senha}
            aoMudar={setSenha}
            autoComplete={modo === "login" ? "current-password" : "new-password"}
            invalido={!!erro}
            descritoPor={erro ? idErro : undefined}
            // A exigência aparece ANTES de tentar, não como recusa depois
            // do clique -- é o mesmo texto que o backend usaria pra negar.
            dica={modo === "cadastro" ? `Mínimo de ${TAMANHO_MINIMO_SENHA} caracteres.` : undefined}
          />

          {/* role="alert" faz o leitor de tela anunciar a falha na hora.
              Sem isso, quem não enxerga clica em "Entrar", nada acontece e
              nada explica o porquê. */}
          {erro && <p className="erro" id={idErro} role="alert">{erro}</p>}

          <button className="botao-principal" type="submit" disabled={enviando}>
            {enviando ? "Aguarde…" : modo === "login" ? "Entrar" : "Criar conta e entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}

