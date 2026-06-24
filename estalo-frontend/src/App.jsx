import { useState, useEffect } from "react";
import { api, token } from "./api.js";
import Auth from "./pages/Auth.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Cards from "./pages/Cards.jsx";
import CriarDeck from "./pages/CriarDeck.jsx";
import Estudo from "./pages/Estudo.jsx";
import Aprender from "./pages/Aprender.jsx";
import Revelar from "./pages/Revelar.jsx";

export default function App() {
  const [usuario, setUsuario] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [tela, setTela] = useState("dashboard");
  const [deckAtivo, setDeckAtivo] = useState(null);
  const [pastaAtivaId, setPastaAtivaId] = useState(null);

  useEffect(() => {
    if (!token.get()) { setCarregando(false); return; }
    api.eu()
      .then(setUsuario)
      .catch(() => token.clear())
      .finally(() => setCarregando(false));
  }, []);

  function sair() {
    token.clear();
    setUsuario(null);
    setTela("dashboard");
    setDeckAtivo(null);
  }

  function aoVerCards(deck) { setDeckAtivo(deck); setTela("cards"); }
  function aoEstudar(deck)  { setDeckAtivo(deck); setTela("estudo"); }
  function aoAprender(deck) { setDeckAtivo(deck); setTela("aprender"); }
  function aoRevelar(deck)  { setDeckAtivo(deck); setTela("revelar"); }

  function aoCriarDeck(pastaId) {
    setPastaAtivaId(pastaId);
    setTela("criarDeck");
  }

  function voltarAoDashboard() { setDeckAtivo(null); setTela("dashboard"); }
  function voltarAoDeck()      { setTela("cards"); }

  if (carregando) return <div className="tela-centro">Carregando…</div>;
  if (!usuario)   return <Auth aoEntrar={setUsuario} />;

  if (tela === "criarDeck") {
    return (
      <CriarDeck
        pastaId={pastaAtivaId}
        aoVoltar={voltarAoDashboard}
        aoVerCards={(deck) => aoVerCards(deck)}
      />
    );
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

  if (tela === "estudo"   && deckAtivo) return <Estudo   deck={deckAtivo} aoVoltar={voltarAoDeck} />;
  if (tela === "aprender" && deckAtivo) return <Aprender deck={deckAtivo} aoVoltar={voltarAoDeck} />;
  if (tela === "revelar"  && deckAtivo) return <Revelar  deck={deckAtivo} aoVoltar={voltarAoDeck} />;

  return (
    <Dashboard
      usuario={usuario}
      aoSair={sair}
      aoVerCards={aoVerCards}
      aoEstudar={aoEstudar}
      aoCriarDeck={aoCriarDeck}
    />
  );
}
