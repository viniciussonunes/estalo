"""Teste do mapeamento Anki -> Estalo (app/services/importer/anki_mapping.py)."""
from app.models.card import calcular_content_hash
from app.services.importer.anki_mapping import (
    EASE_PADRAO, INTERVAL_PADRAO, mapear_para_estalo,
)

print("1) Ease 2500 -> 2.5x...")
p = mapear_para_estalo({"front": "F", "back": "B", "tags": [], "ease": 2500, "interval": 10})
assert p.ease_factor == 2.5
assert p.was_defaulted is False
print("   OK\n")

print("2) Interval negativo (relearning, unidade segundos) -> 0, não conta como corrompido...")
p = mapear_para_estalo({"front": "F", "back": "B", "tags": [], "ease": 2500, "interval": -600})
assert p.interval == 0
assert p.was_defaulted is False
print("   OK\n")

print("3) HTML sujo -> só negrito/itálico/br sobrevivem, sem atributos...")
sujo_front = '<div style="color:red" class="x"><b>Paris</b></div>'
sujo_back = '<span>É a <i>capital</i></span> da França<script>alert(1)</script><img src=x onerror=alert(1)><u>sublinhado</u><br>linha 2'
p = mapear_para_estalo({"front": sujo_front, "back": sujo_back, "tags": [], "ease": 2500, "interval": 10})
assert p.front == "<b>Paris</b>", p.front
assert p.back == "É a <i>capital</i> da Françasublinhado<br>linha 2", p.back
print(f"   front limpo: {p.front!r}")
print(f"   back limpo:  {p.back!r}")
print("   OK\n")

print("4) content_hash bate com o hash do CONTEÚDO LIMPO (não do HTML bruto)...")
esperado = calcular_content_hash(p.front, p.back)
assert p.content_hash == esperado
# checagem extra: garante que NÃO bateria com o hash do HTML sujo
assert p.content_hash != calcular_content_hash(sujo_front, sujo_back)
print("   OK\n")

print("5) Tags passam intactas (não são HTML, não passam pelo sanitizador)...")
p = mapear_para_estalo({"front": "F", "back": "B", "tags": ["geografia", "capitais"], "ease": 2500, "interval": 10})
assert p.tags == ["geografia", "capitais"]
print("   OK\n")

print("6) Resiliência -- ease fora do range aceitável (corrompido) usa default e sinaliza...")
p = mapear_para_estalo({"front": "F", "back": "B", "tags": [], "ease": 99999, "interval": 10})
assert p.ease_factor == EASE_PADRAO
assert p.was_defaulted is True
print("   OK\n")

print("7) Resiliência -- interval positivo absurdo (corrompido) usa default e sinaliza...")
p = mapear_para_estalo({"front": "F", "back": "B", "tags": [], "ease": 2500, "interval": 10**9})
assert p.interval == INTERVAL_PADRAO
assert p.was_defaulted is True
print("   OK\n")

print("8) Resiliência -- tipo errado (string em vez de número) usa default e sinaliza...")
p = mapear_para_estalo({"front": "F", "back": "B", "tags": [], "ease": "lixo", "interval": None})
assert p.ease_factor == EASE_PADRAO and p.interval == INTERVAL_PADRAO
assert p.was_defaulted is True
print("   OK\n")

print("9) ease==0 e interval==0 (card Anki nunca revisado) -- NÃO conta como defaultado...")
p = mapear_para_estalo({"front": "F", "back": "B", "tags": [], "ease": 0, "interval": 0})
assert p.ease_factor == EASE_PADRAO and p.interval == INTERVAL_PADRAO
assert p.was_defaulted is False, "card novo do Anki não deveria disparar aviso de dado corrompido"
print("   OK\n")

print("Todos os testes de mapeamento Anki -> Estalo passaram.")
