import * as Sentry from "@sentry/react";

const dsn = import.meta.env.VITE_SENTRY_DSN;

// Sem DSN configurado, o SDK simplesmente não manda nada pra lugar nenhum
// (fica "enabled: false") — dá pra rodar local/CI sem precisar de conta
// no Sentry. Defina VITE_SENTRY_DSN pra ativar de verdade.
Sentry.init({
  dsn,
  enabled: Boolean(dsn),
  environment: import.meta.env.MODE,
  integrations: [Sentry.browserTracingIntegration()],
  tracesSampleRate: 0.1,
  beforeSend(event, hint) {
    // Log local sempre visível, mesmo sem DSN — útil pra verificar que um
    // erro foi capturado sem depender do dashboard do Sentry.
    console.info("[Sentry] evento capturado:", event.exception?.values?.[0]?.value ?? event.message, hint);
    return event;
  },
});

export default Sentry;
