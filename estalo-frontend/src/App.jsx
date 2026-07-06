import { useState, useEffect } from "react";
import { Routes, Route, Navigate, useNavigate, useLocation, useParams } from "react-router-dom";
import { api, token } from "./api.js";
import useTheme from "./hooks/useTheme.js";
import Auth from "./pages/Auth.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Cards from "./pages/Cards.jsx";
import CriarDeck from "./pages/CriarDeck.jsx";
import Estudo from "./pages/Estudo.jsx";
import Aprender from "./pages/Aprender.jsx";
import Revelar from "./pages/Revelar.jsx";
import Admin from "./pages/Admin.jsx";

function useAuth() {
  const [usuario, setUsuario] = useState(null);
  const [carregando, setCarregando] = useState(true);

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
  }

  return { usuario, setUsuario, sair, carregando };
}

function RequireAuth({ usuario, children }) {
  const location = useLocation();
  if (!usuario) return <Navigate to="/login" state={{ from: location }} replace />;
  return children;
}

// ─── Páginas com acesso ao router ──────────────────────────────────────────

function DashboardPage({ usuario, sair, tema, proximoTema }) {
  const navigate = useNavigate();
  return (
    <Dashboard
      usuario={usuario}
      aoSair={sair}
      tema={tema}
      proximoTema={proximoTema}
      aoVerCards={deck => navigate(`/deck/${deck.id}`, { state: { deck } })}
      aoEstudar={deck => navigate(`/deck/${deck.id}/aprender`, { state: { deck } })}
      aoCriarDeck={pastaId => navigate("/criar-deck", { state: { pastaId } })}
      aoEstudarTudo={() => navigate("/revisao-global")}
      aoEstudarPasta={(folderId, folderName) =>
        navigate("/revisao-global", { state: { folderId, folderName } })}
    />
  );
}

function CardsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const deck = location.state?.deck;

  if (!deck) return <Navigate to="/" replace />;

  return (
    <Cards
      deck={deck}
      aoVoltar={() => navigate("/")}
      aoEstudar={() => navigate(`/deck/${deck.id}/estudo`, { state: { deck } })}
      aoAprender={() => navigate(`/deck/${deck.id}/aprender`, { state: { deck } })}
      aoRevelar={() => navigate(`/deck/${deck.id}/revelar`, { state: { deck } })}
    />
  );
}

function CriarDeckPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const pastaId = location.state?.pastaId ?? null;

  return (
    <CriarDeck
      pastaId={pastaId}
      aoVoltar={() => navigate("/")}
      aoVerCards={deck => navigate(`/deck/${deck.id}`, { state: { deck } })}
    />
  );
}

function EstudoPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const deck = location.state?.deck;

  if (!deck) return <Navigate to="/" replace />;
  return <Estudo deck={deck} aoVoltar={() => navigate(`/deck/${deck.id}`, { state: { deck } })} />;
}

function RevisaoGlobalPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const folderId = location.state?.folderId ?? null;
  const folderName = location.state?.folderName ?? null;
  return (
    <Aprender
      modoGlobal
      folderId={folderId}
      folderName={folderName}
      // Volta pra dentro da mesma pasta (se veio de uma) em vez de sempre
      // pro Início — mais natural que "Estudar Pasta" te tirar dela.
      aoVoltar={() => navigate(folderId ? `/?folder=${folderId}` : "/")}
    />
  );
}

function AprenderPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const deck = location.state?.deck;

  if (!deck) return <Navigate to="/" replace />;
  return (
    <Aprender
      deck={deck}
      aoVoltar={() => navigate(`/deck/${deck.id}`, { state: { deck } })}
      aoEstudoClassico={() => navigate(`/deck/${deck.id}/estudo`, { state: { deck } })}
    />
  );
}

function RevelarPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const deck = location.state?.deck;

  if (!deck) return <Navigate to="/" replace />;
  return <Revelar deck={deck} aoVoltar={() => navigate(`/deck/${deck.id}`, { state: { deck } })} />;
}

function AdminPage() {
  const navigate = useNavigate();
  return <Admin aoVoltar={() => navigate("/")} />;
}

// ─── App root ──────────────────────────────────────────────────────────────

export default function App() {
  const { usuario, setUsuario, sair, carregando } = useAuth();
  const { tema, proximoTema } = useTheme();

  if (carregando) return <div className="tela-centro">Carregando…</div>;

  return (
    <Routes>
      <Route path="/login" element={
        usuario ? <Navigate to="/" replace /> : <Auth aoEntrar={setUsuario} />
      } />

      <Route path="/" element={
        <RequireAuth usuario={usuario}>
          <DashboardPage usuario={usuario} sair={sair} tema={tema} proximoTema={proximoTema} />
        </RequireAuth>
      } />

      <Route path="/criar-deck" element={
        <RequireAuth usuario={usuario}><CriarDeckPage /></RequireAuth>
      } />

      <Route path="/deck/:id" element={
        <RequireAuth usuario={usuario}><CardsPage /></RequireAuth>
      } />

      <Route path="/deck/:id/estudo" element={
        <RequireAuth usuario={usuario}><EstudoPage /></RequireAuth>
      } />

      <Route path="/revisao-global" element={
        <RequireAuth usuario={usuario}><RevisaoGlobalPage /></RequireAuth>
      } />

      <Route path="/deck/:id/aprender" element={
        <RequireAuth usuario={usuario}><AprenderPage /></RequireAuth>
      } />

      <Route path="/deck/:id/revelar" element={
        <RequireAuth usuario={usuario}><RevelarPage /></RequireAuth>
      } />

      <Route path="/admin" element={
        <RequireAuth usuario={usuario}><AdminPage /></RequireAuth>
      } />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
