import useOnline from "../hooks/useOnline.js";

/**
 * Selo pequeno que aparece DENTRO do fluxo de estudo enquanto não há
 * conexão -- a sinalização de "estou respondendo em modo offline".
 *
 * Por que aqui e não só na faixa do rodapé: a faixa diz que o app está
 * offline; este selo diz que ESTA resposta está sendo registrada offline.
 * São coisas diferentes, e a segunda é a que responde a dúvida real de
 * quem está no meio de uma sessão ("isso aqui vai contar?").
 *
 * Ambiente, não interrupção: é um chip inline, não um toast. Some sozinho
 * quando a conexão volta, sem anunciar nada.
 */
export default function SeloOffline({ children = "Offline" }) {
  const online = useOnline();
  if (online) return null;

  return (
    <span className="selo-offline">
      <span className="selo-offline-ponto" aria-hidden="true" />
      {children}
    </span>
  );
}
