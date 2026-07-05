"""
Motor de Importação Anki — módulos de parsing/mapeamento de .apkg.

Nota de nomenclatura: o caminho pedido originalmente era
app/services/import/anki_parser.py, mas `import` é palavra reservada do
Python — "from app.services.import.anki_parser import X" é SyntaxError.
Este pacote chama-se "importer" pelo mesmo motivo que qualquer variável
que precisaria ser `type` vira `type_`: contorna a palavra reservada sem
perder o sentido.
"""
