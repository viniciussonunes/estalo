import { useId, useState } from "react";
import { api, token, NetworkException } from "../api.js";

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
  const [senhaVisivel, setSenhaVisivel] = useState(false);
  const [capsLigado, setCapsLigado] = useState(false);
  const idErro = useId();
  const idSenha = useId();

  function trocarModo(novo) {
    setModo(novo);
    setErro("");
    setSenhaVisivel(false);
  }

  // Caps Lock aceso é a explicação de boa parte dos "minha senha não
  // funciona" -- e, com o campo mascarado, não tem como perceber sozinho.
  // Teclado de celular não reporta o estado; lá o aviso simplesmente nunca
  // aparece, o que é o certo.
  function conferirCaps(e) {
    setCapsLigado(e.getModifierState?.("CapsLock") ?? false);
  }

  async function enviar(e) {
    e.preventDefault();
    setErro("");
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

          {/* Aqui o rótulo é um <label for>, e não um <label> envolvendo
              tudo como no campo de email: clique em qualquer filho de um
              label é redirecionado pro campo, o que faria o botão do olho
              disparar duas vezes. */}
          <div className="campo">
            <label htmlFor={idSenha}>Senha</label>
            <div className="campo-senha">
              <input
                id={idSenha}
                type={senhaVisivel ? "text" : "password"}
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                onKeyUp={conferirCaps}
                onKeyDown={conferirCaps}
                onBlur={() => setCapsLigado(false)}
                placeholder="••••••••"
                autoComplete={modo === "login" ? "current-password" : "new-password"}
                aria-invalid={erro ? true : undefined}
                aria-describedby={erro ? idErro : undefined}
                required
              />
              <button
                type="button"
                className="botao-ver-senha"
                onClick={() => setSenhaVisivel((v) => !v)}
                // O nome não muda com o estado: quem usa leitor de tela
                // ouve o mesmo botão sempre, e `aria-pressed` diz se está
                // ligado. Rótulo que troca de nome vira botão diferente.
                aria-label="Mostrar senha"
                aria-pressed={senhaVisivel}
                title={senhaVisivel ? "Ocultar senha" : "Mostrar senha"}
              >
                {senhaVisivel ? <IconeOlhoFechado /> : <IconeOlho />}
              </button>
            </div>
            {capsLigado && (
              <span className="campo-aviso">Caps Lock está ligado</span>
            )}
          </div>

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

function IconeOlho() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1.8 10S4.9 4.6 10 4.6 18.2 10 18.2 10 15.1 15.4 10 15.4 1.8 10 1.8 10z" />
      <circle cx="10" cy="10" r="2.4" />
    </svg>
  );
}

function IconeOlhoFechado() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8.8 5.1A7.4 7.4 0 0110 5c5.1 0 8.2 5 8.2 5a13.4 13.4 0 01-2.7 3.2" />
      <path d="M5.5 6.5A12.7 12.7 0 001.8 10s3.1 5 8.2 5c1.3 0 2.4-.3 3.4-.8" />
      <path d="M11.7 11.7a2.4 2.4 0 01-3.4-3.4" />
      <path d="M3.2 3.2l13.6 13.6" />
    </svg>
  );
}
