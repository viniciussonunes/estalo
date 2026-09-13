import { createContext, useContext } from "react";
import useTheme from "./useTheme.js";

/**
 * Tema num contexto, pra qualquer tela poder trocar sem receber props.
 *
 * Antes disso o `useTheme()` era chamado uma vez só (App.jsx) e o botão
 * vivia dentro do Dashboard: quem estivesse estudando à noite na tela do
 * Aprender precisava voltar pro início pra escurecer a tela -- justamente
 * quem mais precisa.
 *
 * Por que contexto e não simplesmente chamar useTheme() em cada tela: cada
 * chamada cria um estado PRÓPRIO. Todas escreveriam no mesmo localStorage
 * e na mesma classe do <html>, então a tela até mudaria, mas o botão de
 * outra tela ficaria mostrando o ícone antigo até remontar. Uma fonte só.
 */
const ThemeContext = createContext(null);

export function ThemeProvider({ children }) {
  const tema = useTheme();
  return <ThemeContext.Provider value={tema}>{children}</ThemeContext.Provider>;
}

export function useTema() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTema precisa estar dentro de <ThemeProvider>");
  return ctx;
}
