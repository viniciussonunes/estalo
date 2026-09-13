import { useTema } from "../hooks/ThemeContext.jsx";

const ICONES = { light: IconeSol, dark: IconeLua, system: IconeMonitor };
const NOMES = { light: "Claro", dark: "Escuro", system: "Sistema" };

/**
 * Botão único que cicla claro → escuro → sistema.
 *
 * Saiu de dentro do Dashboard pra cá quando virou item de toda tela: era
 * o único lugar onde dava pra trocar o tema, e quem estuda de noite (a
 * tela do Aprender) tinha que voltar pro início pra escurecer.
 *
 * Sem props de propósito -- pega o tema do contexto. Assim uma tela nova
 * só precisa soltar <ToggleTema /> no cabeçalho, sem ninguém lembrar de
 * repassar estado por três camadas.
 */
export default function ToggleTema() {
  const { tema, proximoTema } = useTema();
  const Icone = ICONES[tema] ?? IconeMonitor;
  return (
    <button
      className="toggle-tema"
      onClick={proximoTema}
      // O nome acessível é fixo, e o estado atual vai no title: um botão
      // que muda de nome a cada clique soa como três botões diferentes
      // pra quem usa leitor de tela (mesma regra do olho da senha).
      aria-label="Trocar tema"
      title={`Tema: ${NOMES[tema] ?? "Sistema"} (clique para trocar)`}
    >
      <Icone />
    </button>
  );
}

function IconeSol() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <circle cx="10" cy="10" r="3.5" />
      <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.2 4.2l1.4 1.4M14.4 14.4l1.4 1.4M4.2 15.8l1.4-1.4M14.4 5.6l1.4-1.4" />
    </svg>
  );
}

function IconeLua() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path d="M16.7 12.4A7 7 0 018.1 3.3a.6.6 0 00-.7-.8A8 8 0 1017.5 13a.6.6 0 00-.8-.6z" />
    </svg>
  );
}

function IconeMonitor() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
      <rect x="2.5" y="4" width="15" height="10" rx="1.3" />
      <path d="M7 17.5h6M10 14v3.5" strokeLinecap="round" />
    </svg>
  );
}
