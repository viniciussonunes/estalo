import { useState } from "react";
import { api, token } from "../api.js";

// Tela de login e cadastro. Um botão alterna entre os dois modos.
export default function Auth({ aoEntrar }) {
  const [modo, setModo] = useState("login"); // "login" ou "cadastro"
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

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
      setErro(err.message);
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
            className={modo === "login" ? "aba ativa" : "aba"}
            onClick={() => { setModo("login"); setErro(""); }}
          >
            Entrar
          </button>
          <button
            className={modo === "cadastro" ? "aba ativa" : "aba"}
            onClick={() => { setModo("cadastro"); setErro(""); }}
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
              required
            />
          </label>

          <label className="campo">
            <span>Senha</span>
            <input
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              placeholder="••••••••"
              required
            />
          </label>

          {erro && <p className="erro">{erro}</p>}

          <button className="botao-principal" type="submit" disabled={enviando}>
            {enviando ? "Aguarde…" : modo === "login" ? "Entrar" : "Criar conta e entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}
