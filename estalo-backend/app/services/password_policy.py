"""
A regra da senha — um lugar só, usado pelo cadastro e pela troca de senha.

Contexto de por que isso passou a existir em 2026-09-13: o cadastro aceitava
literalmente qualquer coisa (`UserCreate.password: str`, sem constraint), e
como não havia como trocar de senha, quem entrasse com "1" ficava com "1"
pra sempre.

O que a regra NÃO faz, de propósito: exigir maiúscula, número e símbolo.
Regra de composição empurra todo mundo pro mesmo "Senha123!" -- previsível,
e mais difícil de lembrar do que uma frase longa. A recomendação atual
(NIST 800-63B) é o contrário: exigir tamanho, barrar as senhas óbvias, e
deixar o resto em paz. É o que está aqui.

A validação vive aqui, e não como `Field(min_length=8)` no schema Pydantic,
por um motivo prático: erro de validação do Pydantic é 422 com `detail`
sendo uma LISTA de objetos, e o frontend (api.js) espera `detail` string.
A mensagem chegaria na tela como "[object Object]". Um 400 com frase pronta
é o que o resto da API já faz.
"""

TAMANHO_MINIMO = 8

# bcrypt ignora tudo depois do 72º byte. Antes isso era silencioso
# (`senha.encode()[:72]` em core/security.py): quem colasse uma frase longa
# teria só o começo protegendo a conta, e ainda por cima duas senhas com os
# mesmos 72 bytes iniciais abririam a mesma conta. Melhor recusar e dizer.
TAMANHO_MAXIMO_BYTES = 72

# As que aparecem em qualquer lista de senhas vazadas. Não é uma tentativa
# de cobrir tudo -- é barrar o que um atacante testa nos dez primeiros
# chutes, que é justamente o que sobrevive a um mínimo de 8 caracteres.
OBVIAS = frozenset({
    "12345678", "123456789", "1234567890", "12341234", "11111111",
    "password", "senha123", "senhasenha", "qwertyui", "abc12345",
    "estalo123", "primeiro", "aaaaaaaa", "iloveyou", "princesa",
})


class SenhaFraca(ValueError):
    """Erro com mensagem já pronta pro usuário final."""


def validar(senha: str, email: str | None = None) -> None:
    """Levanta SenhaFraca com uma frase explicando o que está errado.

    `email` é opcional: quando vem, barra usar o próprio email como senha.
    """
    if len(senha) < TAMANHO_MINIMO:
        raise SenhaFraca(
            f"A senha precisa de pelo menos {TAMANHO_MINIMO} caracteres."
        )

    if len(senha.encode("utf-8")) > TAMANHO_MAXIMO_BYTES:
        raise SenhaFraca(
            "A senha é longa demais — use no máximo 72 caracteres. "
            "(Acentos e emojis contam mais de um.)"
        )

    if senha.lower() in OBVIAS:
        raise SenhaFraca(
            "Essa senha é uma das mais usadas do mundo e seria adivinhada "
            "em segundos. Escolha outra."
        )

    if email and senha.lower() == email.lower():
        raise SenhaFraca("A senha não pode ser igual ao seu email.")
