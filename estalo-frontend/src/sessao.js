/**
 * Fim de sessão: o servidor recusou o crachá.
 *
 * Por que existe: o app só conferia o token UMA vez, no boot (ver useAuth
 * em App.jsx). Depois disso, um 401 era tratado como erro qualquer da tela
 * que o recebeu -- então quem ficasse com a sessão derrubada no meio do
 * caminho continuava navegando por dados velhos, com toda ação falhando
 * sem explicação. Dois caminhos levam a isso no uso normal:
 *
 *   - o token expirou (ele tem validade);
 *   - a senha foi trocada em outro aparelho, e `token_version` derrubou
 *     de propósito as sessões antigas (ver core/security.py).
 *
 * Mesmo padrão de conexao.js: um módulo avisa, quem desenha reage. A fila
 * de respostas de estudo NÃO é tocada aqui -- ela mora no localStorage
 * escopada por usuário e sobe sozinha depois do próximo login (ver
 * outbox.js).
 */
const ouvintes = new Set();

/** Registra quem reage ao fim de sessão. Devolve a função de cancelar. */
export function assinarFimDeSessao(ouvinte) {
  ouvintes.add(ouvinte);
  return () => ouvintes.delete(ouvinte);
}

/** Chamado pelo api.js quando uma request autenticada leva 401. */
export function marcarSessaoExpirada() {
  for (const ouvinte of ouvintes) ouvinte();
}
