"""
Forma e normalização do email — a chave da conta.

Dois problemas que isto fecha, os dois descobertos em 2026-09-13:

1. **A API aceitava qualquer string como email.** `UserCreate.email: str`,
   sem validação. O `type="email"` do navegador segurava no formulário,
   mas quem chamasse a API direto (ou um cliente futuro) criava conta com
   "fulano" mesmo. E como não existe recuperação de senha, um email
   inválido é uma conta que ninguém consegue recuperar.

2. **Maiúscula criava duas contas diferentes** -- pior, criava uma conta
   inacessível. Quem se cadastrava como "Vini@x.com" e depois digitava
   "vini@x.com" no login não entrava: a comparação era exata. O dono não
   tinha como saber o que estava errado, porque a senha estava certa.

Sobre a validação: é de propósito FROUXA. O objetivo é pegar erro de
digitação óbvio (sem @, sem domínio, com espaço), não implementar a
RFC 5322 -- regex "completa" pra email é famosa por rejeitar endereços
válidos, e rejeitar o email de alguém no cadastro é pior que aceitar um
esquisito. Quem valida de verdade é a caixa de entrada: no dia em que
existir confirmação por email, ela é que dá a palavra final.
"""
import re

# Um @, algo antes, algo.algo depois, sem espaços em lugar nenhum.
_FORMATO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

TAMANHO_MAXIMO = 254  # limite prático de endereço de email (RFC 5321)


class EmailInvalido(ValueError):
    """Erro com mensagem já pronta pro usuário final."""


def normalizar(email: str) -> str:
    """Tira espaços das pontas e baixa a caixa.

    Guardar sempre normalizado é o que impede "Vini@x.com" e "vini@x.com"
    de virarem contas diferentes. Formalmente a parte antes do @ é
    sensível a maiúsculas, mas nenhum provedor de verdade trata assim, e
    o custo do rigor aqui seria trancar gente fora da própria conta.
    """
    return (email or "").strip().lower()


def validar(email: str) -> None:
    """Levanta EmailInvalido com uma frase explicando o problema."""
    if not email:
        raise EmailInvalido("Informe um email.")
    if len(email) > TAMANHO_MAXIMO:
        raise EmailInvalido("Esse email é longo demais.")
    if not _FORMATO.match(email):
        raise EmailInvalido("Esse email não parece válido. Confira se está completo.")
