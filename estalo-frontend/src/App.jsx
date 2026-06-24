import { useState, useEffect } from "react";
import { api, token } from "./api.js";
import Auth from "./pages/Auth.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Cards from "./pages/Cards.jsx";
import Estudo from "./pages/Estudo.jsx";
import Aprender from "./pages/Aprender.jsx";
import Revelar from "./pages/Revelar.jsx";

// App é o "porteiro" do frontend: decide qual tela mostrar.
// Sem crachá válido -> tela de login/cadastro.
// Com crachá -> painel (decks) ou tela de estudo.
export default function App() {
  const [usuario, setUsuario] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [tela, setTela] = useState("dashboard"); // "dashboard" | "estudo"
  const [deckAtivo, setDeckAtivo] = useState(null);

  useEffect(() => {
    if (!token.get()) {
      setCarregando(false);
      return;
    }
    api
      .eu()
      .then(setUsuario)
      .catch(() => token.clear())
      .finally(() => setCarregando(false));
  }, []);

  function aoEntrar(dadosUsuario) {
    setUsuario(dadosUsuario);
  }

  function sair() {
    token.clear();
    setUsuario(null);
    setTela("dashboard");
    setDeckAtivo(null);
  }

  function aoVerCards(deck) {
    setDeckAtivo(deck);
    setTela("cards");
  }

  function aoEstudar(deck) {
    setDeckAtivo(deck);
    setTela("estudo");
  }

  function aoAprender(deck) {
    setDeckAtivo(deck);
    setTela("aprender");
  }

  function aoRevelar(deck) {
    setDeckAtivo(deck);
    setTela("revelar");
  }

  function voltarAosDeck() {
    setTela("cards");
  }

  function voltarAoDashboard() {
    setDeckAtivo(null);
    setTela("dashboard");
  }

  if (carregando) {
    return <div className="tela-centro">Carregando…</div>;
  }

  if (!usuario) {
    return <Auth aoEntrar={aoEntrar} />;
  }

  if (tela === "cards" && deckAtivo) {
    return (
      <Cards
        deck={deckAtivo}
        aoVoltar={voltarAoDashboard}
        aoEstudar={() => aoEstudar(deckAtivo)}
        aoAprender={() => aoAprender(deckAtivo)}
        aoRevelar={() => aoRevelar(deckAtivo)}
      />
    );
  }

  if (tela === "estudo" && deckAtivo) {
    return <Estudo deck={deckAtivo} aoVoltar={voltarAosDeck} />;
  }

  if (tela === "aprender" && deckAtivo) {
    return <Aprender deck={deckAtivo} aoVoltar={voltarAosDeck} />;
  }

  if (tela === "revelar" && deckAtivo) {
    return <Revelar deck={deckAtivo} aoVoltar={voltarAosDeck} />;
  }

  return <Dashboard usuario={usuario} aoSair={sair} aoEstudar={aoEstudar} aoVerCards={aoVerCards} />;
}
