import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Configuração do Vite (a ferramenta que roda e empacota o frontend).
export default defineConfig({
  plugins: [
    react(),
    // PWA (Nível 3A do roadmap de resiliência offline): o app passa a ser
    // instalável na tela inicial e a ABRIR sem conexão -- hoje, sem sinal,
    // o navegador mostraria a própria tela de erro e o Estalo nem
    // carregava, por mais que a fila offline (Nível 2) estivesse pronta
    // pra guardar respostas.
    VitePWA({
      // autoUpdate: quando sai um deploy novo, o service worker se
      // substitui sozinho -- sem isso o usuário ficaria preso numa versão
      // antiga até limpar o cache na mão, que é o pesadelo clássico de PWA.
      registerType: "autoUpdate",
      includeAssets: ["apple-touch-icon.png", "favicon-32x32.png"],
      manifest: {
        name: "Estalo",
        short_name: "Estalo",
        description: "Flashcards com repetição espaçada e IA.",
        lang: "pt-BR",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#f7f6fb", // --papel do tema claro
        theme_color: "#5c54e8",      // --violeta da marca
        icons: [
          { src: "pwa-192x192.png", sizes: "192x192", type: "image/png" },
          { src: "pwa-512x512.png", sizes: "512x512", type: "image/png" },
          {
            src: "pwa-maskable-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable", // Android recorta em círculo/squircle
          },
        ],
      },
      workbox: {
        // Qualquer rota do SPA (/deck/3/aprender etc.) abre offline
        // servindo o index.html -- mesmo papel do rewrite do vercel.json,
        // só que sem servidor no meio.
        navigateFallback: "/index.html",
        // O backend é outra origem (estalo-api.vercel.app): as chamadas de
        // API NÃO são navegações e não passam por aqui. O cache de dados de
        // deck é assunto do Nível 3B, e só pros decks que o usuário baixar
        // de propósito -- nada de cachear API por baixo dos panos.
        runtimeCaching: [
          {
            // Fontes da marca (Fraunces/Inter). Sem isso o app abre offline
            // com fonte fallback e "muda de cara" justamente quando o
            // usuário está numa situação já atípica.
            urlPattern: ({ url }) =>
              url.origin === "https://fonts.googleapis.com" ||
              url.origin === "https://fonts.gstatic.com",
            handler: "CacheFirst",
            options: {
              cacheName: "estalo-fontes",
              expiration: { maxEntries: 20, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173, // a mesma porta que liberamos no CORS do backend
  },
});
