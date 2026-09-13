/**
 * Ponte entre o service worker e a interface, pra avisar que saiu versão
 * nova.
 *
 * O problema que isso resolve, sentido na pele em 2026-09-13: o
 * `registerType: "autoUpdate"` do vite-plugin-pwa TROCA a versão sozinho,
 * mas só depois que TODAS as abas do app são fechadas. Num app instalado na
 * tela inicial isso pode levar dias -- e nesse meio-tempo a pessoa continua
 * numa versão antiga sem nenhuma pista. Um deploy que corrige um bug
 * simplesmente não chega em quem está com o app aberto.
 *
 * Agora o registro é `prompt`: a versão nova fica baixada e ESPERANDO, e a
 * interface pergunta se pode aplicar (ver components/AvisoNovaVersao.jsx).
 *
 * Este módulo existe pra desacoplar as duas pontas. O componente não sabe
 * o que é service worker; só escuta este barramento. Isso também deixa o
 * aviso testável sem precisar de dois builds e de um service worker de
 * verdade -- o mesmo evento pode ser disparado à mão:
 *
 *   window.dispatchEvent(new CustomEvent("estalo:nova-versao"))
 */
const EVENTO = "estalo:nova-versao";

// Preenchido pelo registro do service worker (ver registrarAtualizacoes).
// Chamar isso é o que manda o SW novo assumir e recarregar a página.
let aplicar = () => window.location.reload();

/** Avisa a interface que existe versão nova esperando. */
export function anunciarNovaVersao() {
  window.dispatchEvent(new CustomEvent(EVENTO));
}

/** Escuta o anúncio. Devolve a função de cancelar (pro cleanup do efeito). */
export function aoSairNovaVersao(callback) {
  window.addEventListener(EVENTO, callback);
  return () => window.removeEventListener(EVENTO, callback);
}

// Quanto esperar o service worker assumir e recarregar sozinho antes de
// recarregar na marra. Não é paranoia: o `updateSW(true)` recarrega quando
// o SW novo assume o controle, e esse aviso pode não chegar (SW já ativo,
// navegador sem suporte, registro que falhou). Sem essa rede, o botão
// "Atualizar" vira um botão que não faz nada -- pior que não ter botão.
const ESPERA_ATE_RECARREGAR_MS = 3000;

/** Aplica a versão nova: o SW em espera assume e a página recarrega. */
export function aplicarNovaVersao() {
  aplicar();
  setTimeout(() => window.location.reload(), ESPERA_ATE_RECARREGAR_MS);
}

/**
 * Liga o service worker neste barramento. Chamado uma vez, no boot.
 *
 * O import é dinâmico porque `virtual:pwa-register` só existe quando o
 * vite-plugin-pwa está no meio; num ambiente sem ele (ou se o registro
 * falhar), o app tem que subir do mesmo jeito -- sem aviso de atualização
 * é uma limitação, não um motivo pra tela branca.
 */
export async function registrarAtualizacoes() {
  try {
    const { registerSW } = await import("virtual:pwa-register");
    const atualizar = registerSW({
      immediate: true,
      onNeedRefresh() { anunciarNovaVersao(); },
    });
    aplicar = () => atualizar(true);
  } catch {
    /* sem service worker (dev, navegador sem suporte): segue sem aviso */
  }
}
