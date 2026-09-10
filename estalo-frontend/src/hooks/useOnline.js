import { useEffect, useState } from "react";

/**
 * true/false conforme o navegador acha que tem conexão, acompanhando os
 * eventos `online`/`offline` em tempo real.
 *
 * Limite conhecido: `navigator.onLine` só sabe se existe *alguma* rede
 * (wifi conectado, dados ligados) -- não garante que o servidor responde.
 * Cobre bem o caso comum (avião, sem sinal, wifi caiu) e a volta da
 * conexão; falha de rede com `onLine === true` continua sendo pega pelo
 * toast automático do api.js.
 */
export default function useOnline() {
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const marcarOnline = () => setOnline(true);
    const marcarOffline = () => setOnline(false);
    window.addEventListener("online", marcarOnline);
    window.addEventListener("offline", marcarOffline);
    return () => {
      window.removeEventListener("online", marcarOnline);
      window.removeEventListener("offline", marcarOffline);
    };
  }, []);

  return online;
}
