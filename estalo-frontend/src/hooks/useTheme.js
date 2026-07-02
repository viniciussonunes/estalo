import { useState, useEffect, useCallback } from "react";

const CHAVE = "tema_estalo";
const OPCOES = ["light", "dark", "system"];

function prefereEscuroNoSistema() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function aplicarTema(modo) {
  const escuro = modo === "dark" || (modo === "system" && prefereEscuroNoSistema());
  document.documentElement.classList.toggle("tema-escuro", escuro);
}

/**
 * Tema do app: 'light' | 'dark' | 'system'. Aplica a classe .tema-escuro em
 * <html> e persiste a escolha no localStorage. Em modo 'system', acompanha
 * mudanças de preferência do SO em tempo real.
 */
export default function useTheme() {
  const [tema, setTema] = useState(() => {
    try {
      const salvo = localStorage.getItem(CHAVE);
      return OPCOES.includes(salvo) ? salvo : "system";
    } catch {
      return "system";
    }
  });

  useEffect(() => {
    aplicarTema(tema);
    try { localStorage.setItem(CHAVE, tema); } catch { /* localStorage indisponível */ }
  }, [tema]);

  useEffect(() => {
    if (tema !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => aplicarTema("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [tema]);

  const proximoTema = useCallback(() => {
    setTema(t => OPCOES[(OPCOES.indexOf(t) + 1) % OPCOES.length]);
  }, []);

  return { tema, setTema, proximoTema };
}
