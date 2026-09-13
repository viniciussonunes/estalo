import { useState, useEffect } from "react";
import { Routes, Route, Navigate, useNavigate, useLocation, useParams } from "react-router-dom";
import { api, token, NetworkException } from "./api.js";
import Auth from "./pages/Auth.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Cards from "./pages/Cards.jsx";
import CriarDeck from "./pages/CriarDeck.jsx";
import Estudo from "./pages/Estudo.jsx";
import Aprender from "./pages/Aprender.jsx";
import Revelar from "./pages/Revelar.jsx";
import Admin from "./pages/Admin.jsx";
import Conta from "./pages/Conta.jsx";

// Última identidade confirmada pelo servidor, guardada pra conseguir abrir
// o app offline sem parecer deslogado. Não é credencial (quem autentica é
// o token JWT, que o backend valida em toda request) -- é só o nome/email
// pra desenhar a tela.
const CHAVE_USUARIO = "estalo_ultimo_usuario";

function _lembrarUsuario(u) {
  try { localStorage.setItem(CHAVE_USUARIO, JSON.stringify(u)); } catch { /* sem persistência */ }
  return u;
}

function _usuarioLembrado() {
  try { return JSON.parse(localStorage.getItem(CHAVE_USUARIO) || "null"); } catch { return null; }
}

function useAuth() {
  const [usuario, setUsuario] = useState(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    if (!token.get()) { setCarregando(false); return; }
    api.eu()
      .then(u => setUsuario(_lembrarUsuario(u)))
      .catch(err => {
        // Distinguir os dois motivos importa MUITO pro modo offline:
        //
        //  - Falha de REDE: o token provavelmente continua válido, só não
        //    dá pra confirmar agora. Limpar aqui (o que o código fazia
        //    antes, pra qualquer erro) jogava o usuário na tela de login
        //    justamente quando ele não tem como logar -- beco sem saída.
        //    Então segue logado com a última identidade conhecida; a
        //    primeira request de verdade que voltar 401 é que decide.
        //  - Qualquer outro erro (401/403 = token inválido ou expirado):
        //    aí sim é deslogar pra valer.
        if (err instanceof NetworkException) {
          setUsuario(_usuarioLembrado());
        } else {
          token.clear();
          try { localStorage.removeItem(CHAVE_USUARIO); } catch { /* ignora */ }
        }
      })
      .finally(() => setCarregando(false));
  }, []);

  function sair() {
    token.clear();
    try { localStorage.removeItem(CHAVE_USUARIO); } catch { /* ignora */ }
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

function DashboardPage({ usuario, sair }) {
  const navigate = useNavigate();
  return (
    <Dashboard
      usuario={usuario}
      aoSair={sair}
      aoVerCards={deck => navigate(`/deck/${deck.id}`, { state: { deck } })}
      aoEstudar={deck => navigate(`/deck/${deck.id}/aprender`, { state: { deck } })}
      aoCriarDeck={pastaId => navigate("/criar-deck", { state: { pastaId } })}
      aoEstudarTudo={() => navigate("/revisao-global")}
      aoEstudarPasta={(folderId, folderName) =>
        navigate("/revisao-global", { state: { folderId, folderName } })}
      aoAbrirConta={() => navigate("/conta")}
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
      // Volta pra dentro da mesma pasta (se o deck pertence a uma) em vez
      // de sempre pro Início -- mesmo padrão do voltar de RevisaoGlobalPage.
      aoVoltar={() => navigate(deck.folder_id ? `/?folder=${deck.folder_id}` : "/")}
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

function ContaPage({ usuario }) {
  const navigate = useNavigate();
  return <Conta usuario={usuario} aoVoltar={() => navigate("/")} />;
}

// ─── App root ──────────────────────────────────────────────────────────────

export default function App() {
  const { usuario, setUsuario, sair, carregando } = useAuth();

  if (carregando) return <div className="tela-centro">Carregando…</div>;

  return (
    <Routes>
      <Route path="/login" element={
        usuario ? <Navigate to="/" replace /> : <Auth aoEntrar={u => setUsuario(_lembrarUsuario(u))} />
      } />

      <Route path="/" element={
        <RequireAuth usuario={usuario}>
          <DashboardPage usuario={usuario} sair={sair} />
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

      <Route path="/conta" element={
        <RequireAuth usuario={usuario}><ContaPage usuario={usuario} /></RequireAuth>
      } />

      <Route path="/admin" element={
        <RequireAuth usuario={usuario}><AdminPage /></RequireAuth>
      } />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
