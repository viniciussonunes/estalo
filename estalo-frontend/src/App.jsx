import { useState, useEffect } from "react";
import { api, token } from "./api.js";
import Auth from "./pages/Auth.jsx";
import Dashboard from "./pages/Dashboard.jsx";

// App é o "porteiro" do frontend: decide qual tela mostrar.
// Sem crachá válido -> tela de login/cadastro.
// Com crachá -> o painel (decks).
export default function App() {
  const [usuario, setUsuario] = useState(null);
  const [carregando, setCarregando] = useState(true);

  // Ao abrir o app, se já tem crachá guardado, confere se ainda vale.
  useEffect(() => {
    if (!token.get()) {
      setCarregando(false);
      return;
    }
    api
      .eu()
      .then(setUsuario)
      .catch(() => token.clear()) // crachá velho/inválido: descarta
      .finally(() => setCarregando(false));
  }, []);

  function aoEntrar(dadosUsuario) {
    setUsuario(dadosUsuario);
  }

  function sair() {
    token.clear();
    setUsuario(null);
  }

  if (carregando) {
    return <div className="tela-centro">Carregando…</div>;
  }

  return usuario ? (
    <Dashboard usuario={usuario} aoSair={sair} />
  ) : (
    <Auth aoEntrar={aoEntrar} />
  );
}
