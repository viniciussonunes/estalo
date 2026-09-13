/**
 * Regra de senha do lado do cliente.
 *
 * O backend é a autoridade (estalo-backend/app/services/password_policy.py).
 * Isto aqui existe só pra dizer o óbvio na hora, sem uma ida ao servidor
 * pra ouvir "tem menos de 8 caracteres" -- coisa que a própria tela já
 * sabe.
 *
 * De propósito, só as regras de TAMANHO estão duplicadas: são estáveis e
 * fáceis de manter iguais. A lista de senhas óbvias fica só no servidor;
 * duplicá-la aqui criaria duas listas pra manter em sincronia (e a cópia
 * do cliente é pública de qualquer jeito). Quando o servidor recusa por
 * esse motivo, a frase dele aparece na tela como qualquer outro erro.
 */
export const TAMANHO_MINIMO_SENHA = 8;

// bcrypt ignora tudo depois do 72º byte -- ver o mesmo limite no backend.
const MAXIMO_BYTES = 72;

/** Devolve a frase do problema, ou null se a senha passa. */
export function validarSenha(senha) {
  if (senha.length < TAMANHO_MINIMO_SENHA) {
    return `A senha precisa de pelo menos ${TAMANHO_MINIMO_SENHA} caracteres.`;
  }
  if (new TextEncoder().encode(senha).length > MAXIMO_BYTES) {
    return "A senha é longa demais — use no máximo 72 caracteres. (Acentos e emojis contam mais de um.)";
  }
  return null;
}
