import { useId, useState } from "react";

/**
 * Campo de senha com olho de mostrar/ocultar, aviso de Caps Lock e dica.
 *
 * Virou componente quando a troca de senha chegou: são quatro campos de
 * senha no app agora (entrar, criar conta e três no modal de troca), e
 * cada cópia seria uma chance de esquecer o autocomplete, o Caps Lock ou
 * o rótulo acessível.
 *
 * Detalhe do rótulo do olho: o nome NÃO muda quando a senha fica visível
 * (só o `aria-pressed`), porque um botão que troca de nome soa como outro
 * botão pra quem usa leitor de tela. Mas ele inclui o nome do campo --
 * "Mostrar senha atual", "Mostrar nova senha" -- senão, num formulário com
 * três campos, seriam três botões idênticos e indistinguíveis.
 */
export default function CampoSenha({
  rotulo,
  valor,
  aoMudar,
  autoComplete,
  invalido = false,
  descritoPor,
  dica,
  autoFocus = false,
}) {
  const [visivel, setVisivel] = useState(false);
  const [capsLigado, setCapsLigado] = useState(false);
  const idCampo = useId();
  const idDica = useId();

  // Caps Lock aceso explica boa parte dos "minha senha não funciona" -- e,
  // com o campo mascarado, não tem como perceber sozinho. Teclado de
  // celular não reporta o estado, então lá o aviso nunca aparece, que é o
  // certo.
  const conferirCaps = (e) => setCapsLigado(e.getModifierState?.("CapsLock") ?? false);

  return (
    <div className="campo">
      <label htmlFor={idCampo}>{rotulo}</label>
      <div className="campo-senha">
        <input
          id={idCampo}
          type={visivel ? "text" : "password"}
          value={valor}
          onChange={(e) => aoMudar(e.target.value)}
          onKeyUp={conferirCaps}
          onKeyDown={conferirCaps}
          onBlur={() => setCapsLigado(false)}
          placeholder="••••••••"
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          aria-invalid={invalido ? true : undefined}
          aria-describedby={[dica ? idDica : null, descritoPor].filter(Boolean).join(" ") || undefined}
          required
        />
        <button
          type="button"
          className="botao-ver-senha"
          onClick={() => setVisivel((v) => !v)}
          aria-label={`Mostrar ${rotulo.toLowerCase()}`}
          aria-pressed={visivel}
          title={visivel ? "Ocultar" : "Mostrar"}
        >
          {visivel ? <IconeOlhoFechado /> : <IconeOlho />}
        </button>
      </div>
      {dica && <span className="campo-dica" id={idDica}>{dica}</span>}
      {capsLigado && <span className="campo-aviso">Caps Lock está ligado</span>}
    </div>
  );
}

function IconeOlho() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1.8 10S4.9 4.6 10 4.6 18.2 10 18.2 10 15.1 15.4 10 15.4 1.8 10 1.8 10z" />
      <circle cx="10" cy="10" r="2.4" />
    </svg>
  );
}

function IconeOlhoFechado() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8.8 5.1A7.4 7.4 0 0110 5c5.1 0 8.2 5 8.2 5a13.4 13.4 0 01-2.7 3.2" />
      <path d="M5.5 6.5A12.7 12.7 0 001.8 10s3.1 5 8.2 5c1.3 0 2.4-.3 3.4-.8" />
      <path d="M11.7 11.7a2.4 2.4 0 01-3.4-3.4" />
      <path d="M3.2 3.2l13.6 13.6" />
    </svg>
  );
}
