import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import * as Sentry from "@sentry/react";
import "./sentry.js"; // precisa inicializar antes de qualquer coisa renderizar
import App from "./App.jsx";
import { ToastProvider } from "./hooks/ToastContext.jsx";
import OfflineBanner from "./components/OfflineBanner.jsx";
import useOutboxSync from "./hooks/useOutboxSync.js";
import "./styles.css";

function ErroFallback({ error }) {
  return (
    <div className="tela-centro">
      <div className="cartao-auth" style={{ textAlign: "center" }}>
        <p style={{ fontWeight: 600, marginBottom: "0.5rem" }}>Algo deu errado.</p>
        <p className="vazio-dica" style={{ marginBottom: "1rem" }}>
          O erro já foi registrado. Recarregue a página pra tentar de novo.
        </p>
        <button className="botao-principal" onClick={() => window.location.assign("/")}>
          Voltar ao início
        </button>
        {import.meta.env.DEV && (
          <p className="erro" style={{ marginTop: "1rem", textAlign: "left" }}>{error?.message}</p>
        )}
      </div>
    </div>
  );
}

// Precisa ser um componente (e não JSX solto no render) porque
// useOutboxSync é um hook -- e precisa estar DENTRO do ToastProvider,
// já que a sincronização avisa por toast quando a fila sobe.
function Raiz() {
  useOutboxSync();
  return (
    <>
      <OfflineBanner />
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Sentry.ErrorBoundary fallback={({ error }) => <ErroFallback error={error} />}>
      <ToastProvider>
        <Raiz />
      </ToastProvider>
    </Sentry.ErrorBoundary>
  </React.StrictMode>
);
