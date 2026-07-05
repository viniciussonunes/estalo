"""
Mapeamento Anki → Estalo: converte o dict cru do parser
(app/services/importer/anki_parser.py) pro formato de domínio do Estalo —
conversão de algoritmo (ease/interval), limpeza de HTML e content_hash.
Não persiste nada no banco; isso é responsabilidade de quem promove
staging → Card/Review (endpoint ainda não implementado).
"""
from dataclasses import dataclass

import nh3

from app.models.card import calcular_content_hash

# Faixas aceitáveis pros valores crus do Anki — fora disso é tratado como
# dado corrompido, não um estado válido de card.
_EASE_MIN_PERMILLE = 1300    # mesmo piso que o SM-2 do Estalo já aplica (sm2.py: max(1.3, ease))
_EASE_MAX_PERMILLE = 5000    # teto generoso — Anki não deixa passar disso na prática
_INTERVAL_MAX_DIAS = 36_500  # ~100 anos — qualquer coisa acima é claramente corrompida

EASE_PADRAO = 2.5   # mesmo default de Review.ease_factor (app/models/review.py)
INTERVAL_PADRAO = 0  # card "novo"/sem histórico confiável

# Só formatação básica sobrevive — negrito/itálico/quebra de linha. O
# resto (div, span, img, estilos inline, [sound:...] não é tag então nem
# chega aqui) é removido; tags perigosas (script e afins) somem com o
# conteúdo interno, tags "só desnecessárias" (u, font...) são desembrulhadas
# mantendo o texto.
_TAGS_PERMITIDAS = {"b", "strong", "i", "em", "br"}


@dataclass
class CardPayload:
    front: str
    back: str
    tags: list[str]
    ease_factor: float
    interval: int
    content_hash: str
    was_defaulted: bool


def _limpar_html(texto: str) -> str:
    """Remove tudo que não for negrito/itálico/quebra de linha, incluindo
    qualquer atributo mesmo nas tags permitidas (style, onclick, etc).

    Usa nh3 (binding Python do Ammonia/html5ever) em vez de regex — HTML
    não dá pra sanitizar com segurança via regex (tags aninhadas/malformadas
    quebram qualquer regex, e é exatamente por aí que sanitização baseada em
    regex historicamente vaza XSS).
    """
    return nh3.clean(texto or "", tags=_TAGS_PERMITIDAS, attributes={})


def _mapear_ease(ease_bruto) -> tuple[float, bool]:
    """(ease_factor, foi_defaultado).

    ease_bruto == 0 é o estado NORMAL de um card Anki nunca revisado (o
    Anki não guarda ease antes da primeira revisão) — não é corrupção, só
    ainda não tem ease, então não conta como "defaultado" pro relatório.
    """
    if not isinstance(ease_bruto, (int, float)) or isinstance(ease_bruto, bool):
        return EASE_PADRAO, True
    if ease_bruto == 0:
        return EASE_PADRAO, False
    if _EASE_MIN_PERMILLE <= ease_bruto <= _EASE_MAX_PERMILLE:
        return round(ease_bruto / 1000, 2), False
    return EASE_PADRAO, True


def _mapear_interval(interval_bruto) -> tuple[int, bool]:
    """(interval_dias, foi_defaultado).

    Negativo = o card está em relearning/passo curto no Anki e a unidade
    muda pra segundos, não dias — normalizar pra 0 é conversão de unidade
    esperada (acontece pra qualquer card que já falhou uma vez), não
    corrupção, então também não conta como "defaultado".
    """
    if not isinstance(interval_bruto, (int, float)) or isinstance(interval_bruto, bool):
        return INTERVAL_PADRAO, True
    if interval_bruto < 0:
        return 0, False
    if interval_bruto <= _INTERVAL_MAX_DIAS:
        return int(interval_bruto), False
    return INTERVAL_PADRAO, True


def mapear_para_estalo(dados_brutos: dict) -> CardPayload:
    """Converte {front, back, tags, ease, interval} (formato cru devolvido
    por anki_parser.parse_apkg) num CardPayload pronto pra virar Card/Review.

    content_hash é calculado sobre o conteúdo JÁ LIMPO (pós-sanitização) —
    é isso que de fato vai ser persistido em Card.front/back, então o hash
    tem que corresponder a esse valor final, não ao HTML bruto do Anki.
    """
    front = _limpar_html(dados_brutos.get("front", ""))
    back = _limpar_html(dados_brutos.get("back", ""))
    tags = list(dados_brutos.get("tags", []))

    ease_factor, ease_defaultado = _mapear_ease(dados_brutos.get("ease"))
    interval, interval_defaultado = _mapear_interval(dados_brutos.get("interval"))

    return CardPayload(
        front=front,
        back=back,
        tags=tags,
        ease_factor=ease_factor,
        interval=interval,
        content_hash=calcular_content_hash(front, back),
        was_defaulted=ease_defaultado or interval_defaultado,
    )
