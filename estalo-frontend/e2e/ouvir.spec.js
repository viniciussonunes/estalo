/**
 * Tela "Ouvir": a conversa de dois locutores gerada a partir de um deck.
 *
 * O que estes testes seguram, e por que cada coisa importa:
 *
 *   - **O ciclo de vida.** Diferente dos outros modos, o áudio não
 *     existe até alguém mandar gerar. São três estados de entrada (nada,
 *     roteiro-sem-áudio, pronto) e errar qual aparece deixa a pessoa
 *     pagando IA de novo por um áudio que ela já tem.
 *   - **A fila é conduzida pelo cliente.** Um episódio não cabe no
 *     maxDuration de 60s de uma função serverless, então a tela pede
 *     bloco por bloco. Se ela pedir blocos a menos, o áudio sai cortado
 *     e ninguém percebe até ouvir.
 *   - **Offline não é erro.** Com o áudio no aparelho, falhar ao
 *     consultar o servidor não deve virar caixa vermelha: quem conta que
 *     está sem rede é a faixa do rodapé, uma vez. Esse defeito existiu e
 *     foi visto rodando -- o player tocava normalmente com um erro em
 *     cima dele.
 *
 * Não depende do backend nem da IA: a API é simulada aqui.
 */
import { test, expect } from "@playwright/test";

const CAMINHOS_API = /^\/(auth|folders|decks|cards|study)(\/|$)/;

const DECK = {
  id: 10, title: "Farmacologia", description: null, folder_id: null,
  created_at: "2026-01-01T00:00:00", total_cards: 4, memorization_pct: 0,
};

const CAPITULOS = [
  { indice: 0, titulo: "Penicilinas e segurança", caracteres: 566 },
  { indice: 1, titulo: "Resistência: betalactamases", caracteres: 472 },
  { indice: 2, titulo: "Inibidores de betalactamase", caracteres: 681 },
];

function tokenFalso() {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp: 9999999999 })}.assinatura-de-teste`;
}

/** PCM de meio segundo: silêncio basta, ninguém escuta num teste. */
function pcmFalso() {
  return Buffer.alloc(24000, 0);
}

/**
 * `estado`: "nada" (nem roteiro), "roteiro" (escrito, áudio não gravado
 * aqui), "atrasado" (roteiro existe e os cards mudaram depois).
 * `semRede`: toda chamada à API falha, pra simular o avião.
 */
async function abrirOuvir(page, { estado = "nada", semRede = false, semEspaco = false } = {}) {
  // `ref` é o servidor de mentira, e também o painel de controle do teste:
  // `ref.quebrar` passa a derrubar aquele bloco, `ref.versao` finge um
  // roteiro reescrito (inclusive por outro aparelho).
  const ref = { blocosPedidos: [], roteirosPedidos: [], quebrar: null, versao: "2026-11-05T10:00:00" };

  await page.route("**/*", async (route) => {
    const req = route.request();
    const p = new URL(req.url()).pathname;
    if (!["xhr", "fetch"].includes(req.resourceType()) || !CAMINHOS_API.test(p)) return route.continue();
    if (semRede) return route.abort("failed");

    const json = (c, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(c) });

    const bloco = p.match(/^\/decks\/10\/audio\/bloco\/(\d+)$/);
    if (bloco) {
      const i = Number(bloco[1]);
      ref.blocosPedidos.push(i);
      // Derruba só este bloco: é o 503 do provedor no meio da fila.
      if (i === ref.quebrar) return json({ detail: "Serviço de IA indisponível." }, 503);
      return route.fulfill({
        status: 200,
        contentType: "application/octet-stream",
        headers: { "X-Taxa-Amostragem": "24000" },
        body: pcmFalso(),
      });
    }
    if (p === "/decks/10/audio/roteiro") {
      ref.roteirosPedidos.push(new URL(req.url()).search);
      ref.estado = "roteiro";
      return json({ existe: true, desatualizado: false, total_blocos: 3, capitulos: CAPITULOS, criado_em: ref.versao });
    }
    if (p === "/decks/10/audio") {
      if (req.method() === "DELETE") return route.fulfill({ status: 204, body: "" });
      if (ref.estado === "nada") return json({ existe: false });
      return json({
        existe: true,
        desatualizado: ref.estado === "atrasado",
        total_blocos: 3,
        capitulos: CAPITULOS,
        criado_em: ref.versao,
      });
    }

    if (p === "/auth/me") return json({ id: 1, email: "estudante@estalo.dev", created_at: "2026-03-05T14:20:00", is_admin: false, cards_por_sessao: 15 });
    if (p === "/auth/me/quota") return json({ consumido: 0, limite: 50000, restante: 50000, renova_em: "2026-12-01T03:00:00" });
    if (p === "/folders") return json([]);
    if (p === "/decks") return json([DECK]);
    return json({});
  });

  ref.estado = estado === "nada" ? "nada" : estado;

  // addInitScript, não page.evaluate depois do goto: o token precisa
  // existir ANTES de qualquer script da página rodar, senão o App monta
  // deslogado e o RequireAuth joga pro /login. Com evaluate havia uma
  // corrida -- a maior parte das vezes passava, e de vez em quando o
  // teste caía na tela de login sem explicação.
  await page.addInitScript((t) => {
    localStorage.setItem("estalo_token", t);
    localStorage.setItem("estalo_ultimo_usuario", JSON.stringify({ id: 1, email: "estudante@estalo.dev" }));
  }, tokenFalso());

  // Aparelho cheio: o localStorage recusa o registro do áudio. É o que um
  // iPhone perto do teto faz, e é a falha mais cruel do caminho -- chega
  // DEPOIS de a geração inteira ter sido paga.
  if (semEspaco) {
    await page.addInitScript(() => {
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function (chave, valor) {
        if (chave === "estalo_audio_decks") {
          const e = new Error("QuotaExceededError");
          e.name = "QuotaExceededError";
          throw e;
        }
        return original.call(this, chave, valor);
      };
    });
  }

  // A tela exige o deck no state da rota (mesmo padrão das irmãs). O
  // caminho de verdade é Dashboard -> deck -> Outros modos -> Ouvir;
  // aqui vamos direto, com o state posto na mão.
  await irPraOuvir(page);
  return ref;
}

/** Entra na rota de Ouvir com o deck no history state, e espera a tela. */
async function irPraOuvir(page) {
  await page.goto("/");
  await page.waitForSelector(".pagina");
  await page.evaluate((d) => {
    window.history.replaceState({ usr: { deck: d } }, "", `/deck/${d.id}/ouvir`);
    window.dispatchEvent(new PopStateEvent("popstate", { state: { usr: { deck: d } } }));
  }, DECK);
  await page.waitForSelector(".ouvir-vazio, .ouvir-player, .ouvir-gerando");
}

test.describe("Ouvir", () => {
  test("deck sem nada oferece gerar a conversa", async ({ page }) => {
    await abrirOuvir(page, { estado: "nada" });
    await expect(page.locator(".ouvir-vazio-titulo")).toHaveText("Ouvir este deck");
    await expect(page.getByRole("button", { name: "Gerar conversa" })).toBeVisible();
    await expect(page.locator(".ouvir-vazio-fatos")).toContainText("Rafael e Beatriz");
  });

  test("roteiro pronto sem áudio aqui oferece só gravar", async ({ page }) => {
    await abrirOuvir(page, { estado: "roteiro" });
    await expect(page.locator(".ouvir-vazio-titulo")).toHaveText("Falta gravar neste aparelho");
    await expect(page.getByRole("button", { name: "Gravar áudio" })).toBeVisible();
    // Não repete a propaganda: quem chegou aqui já decidiu.
    await expect(page.locator(".ouvir-vazio-fatos")).toHaveCount(0);
  });

  test("gerar pede TODOS os blocos, em ordem, e abre o player", async ({ page }) => {
    const ref = await abrirOuvir(page, { estado: "nada" });
    await page.getByRole("button", { name: "Gerar conversa" }).click();

    await expect(page.locator(".ouvir-player")).toBeVisible({ timeout: 20000 });
    expect(ref.blocosPedidos).toEqual([0, 1, 2]);

    const capitulos = page.locator(".ouvir-capitulo-nome");
    await expect(capitulos).toHaveCount(3);
    await expect(capitulos.first()).toHaveText("Penicilinas e segurança");
  });

  test("durante a gravação mostra o progresso e avisa pra não sair", async ({ page }) => {
    await abrirOuvir(page, { estado: "nada" });
    await page.getByRole("button", { name: "Gerar conversa" }).click();
    await expect(page.locator(".ouvir-gerando")).toContainText("Mantenha esta tela aberta");
    await expect(page.locator(".ouvir-player")).toBeVisible({ timeout: 20000 });
  });

  test("card mudado depois acende o aviso de atrasado", async ({ page }) => {
    const ref = await abrirOuvir(page, { estado: "nada" });
    await page.getByRole("button", { name: "Gerar conversa" }).click();
    await expect(page.locator(".ouvir-player")).toBeVisible({ timeout: 20000 });
    await expect(page.locator(".ouvir-aviso-velho")).toHaveCount(0);

    ref.estado = "atrasado";
    await irPraOuvir(page);
    await expect(page.locator(".ouvir-aviso-velho")).toContainText("Este áudio está atrasado");
  });

  test("o áudio sobrevive a recarregar a página", async ({ page }) => {
    await abrirOuvir(page, { estado: "nada" });
    await page.getByRole("button", { name: "Gerar conversa" }).click();
    await expect(page.locator(".ouvir-player")).toBeVisible({ timeout: 20000 });

    await irPraOuvir(page);
    await expect(page.locator(".ouvir-player")).toBeVisible();
    await expect(page.locator(".ouvir-acao-desc").first()).toContainText("Toca sem internet");
  });

  test("sem rede, com cópia no aparelho, o player aparece sem caixa de erro", async ({ page }) => {
    await abrirOuvir(page, { estado: "nada" });
    await page.getByRole("button", { name: "Gerar conversa" }).click();
    await expect(page.locator(".ouvir-player")).toBeVisible({ timeout: 20000 });

    // Cai a rede e a pessoa volta pra tela: é o caso que a tela promete
    // atender, não um erro.
    await page.route("**/*", (route) => {
      const r = route.request();
      const p = new URL(r.url()).pathname;
      if (["xhr", "fetch"].includes(r.resourceType()) && CAMINHOS_API.test(p)) return route.abort("failed");
      return route.continue();
    });
    await irPraOuvir(page);

    await expect(page.locator(".ouvir-player")).toBeVisible();
    await expect(page.locator(".erro")).toHaveCount(0);
    await expect(page.locator(".selo-offline")).toBeVisible();
  });

  test("remover apaga a cópia e volta a oferecer a gravação", async ({ page }) => {
    await abrirOuvir(page, { estado: "nada" });
    await page.getByRole("button", { name: "Gerar conversa" }).click();
    await expect(page.locator(".ouvir-player")).toBeVisible({ timeout: 20000 });

    await page.getByRole("button", { name: "Remover" }).click();
    await expect(page.locator(".ouvir-player")).toHaveCount(0);
    await expect(page.locator(".ouvir-vazio-titulo")).toHaveText("Falta gravar neste aparelho");
  });

  test("bloco que falha no meio não joga fora os blocos já pagos", async ({ page }) => {
    // O defeito que este teste segura: os pedaços ficavam numa variável em
    // memória e só iam pro aparelho DEPOIS do último bloco. Falhar no
    // bloco 2 de 3 descartava os dois primeiros -- cuja cota de IA já
    // tinha sido debitada -- e tentar de novo pagava tudo outra vez.
    const ref = await abrirOuvir(page, { estado: "nada" });
    ref.quebrar = 2;
    await page.getByRole("button", { name: "Gerar conversa" }).click();

    await expect(page.locator(".erro")).toBeVisible({ timeout: 20000 });
    expect(ref.blocosPedidos).toEqual([0, 1, 2]);

    // Segunda tentativa, agora com o provedor de pé: só o bloco que
    // faltava pode ir ao servidor.
    ref.quebrar = null;
    ref.blocosPedidos.length = 0;
    await page.getByRole("button", { name: /^(Gerar conversa|Gravar áudio)$/ }).click();

    await expect(page.locator(".ouvir-player")).toBeVisible({ timeout: 20000 });
    expect(ref.blocosPedidos).toEqual([2]);
  });

  test("roteiro reescrito não herda os blocos do antigo", async ({ page }) => {
    // O outro lado da moeda: retomar é bom, retomar o roteiro ERRADO
    // seria um episódio costurado de duas conversas diferentes. Aqui o
    // roteiro é reescrito (neste ou em outro aparelho) depois da falha.
    const ref = await abrirOuvir(page, { estado: "nada" });
    ref.quebrar = 2;
    await page.getByRole("button", { name: "Gerar conversa" }).click();
    await expect(page.locator(".erro")).toBeVisible({ timeout: 20000 });

    ref.quebrar = null;
    ref.versao = "2026-11-06T09:00:00"; // roteiro novo
    ref.blocosPedidos.length = 0;
    await page.getByRole("button", { name: /^(Gerar conversa|Gravar áudio)$/ }).click();

    await expect(page.locator(".ouvir-player")).toBeVisible({ timeout: 20000 });
    expect(ref.blocosPedidos).toEqual([0, 1, 2]);
  });

  test("aparelho sem espaço diz o que fazer, em vez de erro cru", async ({ page }) => {
    // Falhar ao GUARDAR é a única falha que acontece depois de a cota já
    // ter sido gasta. Antes vazava um QuotaExceededError do navegador na
    // cara de quem esperou a geração inteira.
    await abrirOuvir(page, { estado: "nada", semEspaco: true });
    await page.getByRole("button", { name: "Gerar conversa" }).click();

    const erro = page.locator(".erro");
    await expect(erro).toBeVisible({ timeout: 20000 });
    await expect(erro).toContainText("não cabe neste aparelho");
    await expect(erro).toContainText("Libere espaço");
    await expect(erro).not.toContainText("QuotaExceeded");
    // E não finge que deu certo: o player não aparece.
    await expect(page.locator(".ouvir-player")).toHaveCount(0);
  });

  test("sem internet e sem cópia, o botão de gerar fica indisponível", async ({ page }) => {
    await abrirOuvir(page, { estado: "nada", semRede: true });
    await expect(page.getByRole("button", { name: "Gerar conversa" })).toBeDisabled();
    await expect(page.locator(".ouvir-nota-offline")).toContainText("Precisa de internet");
  });
});
