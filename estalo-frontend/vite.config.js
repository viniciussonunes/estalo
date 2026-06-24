import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Configuração do Vite (a ferramenta que roda e empacota o frontend).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173, // a mesma porta que liberamos no CORS do backend
  },
});
