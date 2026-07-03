import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import * as Sentry from "@sentry/react";
import "./sentry.js"; // precisa inicializar antes de qualquer coisa renderizar
import App from "./App.jsx";
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

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Sentry.ErrorBoundary fallback={({ error }) => <ErroFallback error={error} />}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </Sentry.ErrorBoundary>
  </React.StrictMode>
);
