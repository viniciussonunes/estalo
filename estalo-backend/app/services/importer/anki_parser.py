"""
Parser de arquivos .apkg do Anki — extração CRUA, sem nenhuma conversão
semântica pro modelo do Estalo (isso é responsabilidade de um futuro
anki_mapping.py, ainda não implementado).

Um .apkg é um zip contendo o banco da coleção — collection.anki2 (schema
legado), collection.anki21 (schema 18+) ou collection.anki21b (mesma
coisa, comprimida em zstd — formato padrão desde o Anki 23.10) — mais
mídia, que este parser ignora. Aqui só lemos `notes`+`cards`+`col` e
devolvemos uma lista de dicts:

    {"front": str, "back": str, "tags": list[str], "ease": int, "interval": int}

com "ease" e "interval" nas unidades CRUAS do Anki: ease em permille (ex:
2500 = fator 2.5) e interval em dias se positivo OU segundos se negativo
(cards em relearning). Quem consumir isso decide como converter — este
módulo só extrai fielmente.

Escopo desta v1 (decidido no PMA do Motor de Importação Anki): só note
types "Basic-like" — mtype padrão (não-Cloze) E exatamente 1 template.
Isso cobre o "Basic" puro mas já exclui de propósito "Basic (e invertido)"
(2 templates, geraria 2 cards por nota, não mapeia 1:1 pra front/back) e
qualquer Cloze. Notas cujo note type não conseguimos classificar (ex:
uma coleção "schema 18+" sem o JSON de compatibilidade em col.models)
também são puladas — nunca adivinhamos, só pulamos e contamos.
"""
import json
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    import zstandard
except ImportError:  # só é preciso pra exports .anki21b (Anki 23.10+)
    zstandard = None

# Nomes possíveis do banco da coleção dentro do .apkg, na mesma ordem de
# preferência que o próprio Anki usa ao abrir um pacote (mais novo primeiro).
_NOMES_COLECAO = ("collection.anki21b", "collection.anki21", "collection.anki2")


class AnkiImportError(Exception):
    """Arquivo .apkg inválido, corrompido, ou num formato que este parser não suporta.

    O endpoint de importação (futuro) captura essa exceção e devolve
    400 Bad Request com a mensagem — nunca deixa um traceback cru vazar
    nem grava nada no banco quando isso acontece.
    """


@dataclass
class ResultadoParse:
    cards: list[dict]
    pulados: int = 0
    motivos_pulados: dict[str, int] = field(default_factory=dict)

    def _registrar_pulado(self, motivo: str) -> None:
        self.pulados += 1
        self.motivos_pulados[motivo] = self.motivos_pulados.get(motivo, 0) + 1


def _extrair_colecao(caminho_apkg: Path, destino: Path) -> Path:
    """Descompacta o .apkg e devolve o caminho do arquivo SQLite (já
    descomprimido, se era um .anki21b em zstd) pronto pra conectar."""
    try:
        with zipfile.ZipFile(caminho_apkg) as z:
            nomes_no_zip = set(z.namelist())
            nome_colecao = next((n for n in _NOMES_COLECAO if n in nomes_no_zip), None)
            if nome_colecao is None:
                raise AnkiImportError(
                    "Arquivo não parece um .apkg válido — nenhum banco de coleção "
                    "(collection.anki2/anki21/anki21b) encontrado dentro do zip."
                )
            z.extract(nome_colecao, path=destino)
    except zipfile.BadZipFile as e:
        raise AnkiImportError(
            "Arquivo não é um .apkg válido (zip corrompido ou formato errado)."
        ) from e

    caminho_extraido = destino / nome_colecao
    if nome_colecao == "collection.anki21b":
        return _descomprimir_zstd(caminho_extraido, destino)
    return caminho_extraido


def _descomprimir_zstd(caminho_comprimido: Path, destino: Path) -> Path:
    if zstandard is None:
        raise AnkiImportError(
            "Este .apkg foi exportado por uma versão recente do Anki (formato "
            "comprimido .anki21b) e o suporte a esse formato não está instalado "
            "no servidor."
        )
    caminho_saida = destino / "collection_descomprimida.anki21"
    try:
        with open(caminho_comprimido, "rb") as entrada, open(caminho_saida, "wb") as saida:
            zstandard.ZstdDecompressor().copy_stream(entrada, saida)
    except zstandard.ZstdError as e:
        raise AnkiImportError(
            "Não foi possível descomprimir o arquivo .apkg (dados corrompidos)."
        ) from e
    return caminho_saida


def _conectar_leitura(caminho_sqlite: Path) -> sqlite3.Connection:
    """Conexão explicitamente read-only (mode=ro) — nunca escrevemos na
    cópia extraída do banco do Anki, só lemos."""
    try:
        conn = sqlite3.connect(f"file:{caminho_sqlite}?mode=ro", uri=True)
        # "SELECT 1" é uma expressão constante — não força o SQLite a ler o
        # cabeçalho/páginas do arquivo, então não detecta corrupção. Ler de
        # sqlite_master (sempre presente em qualquer banco válido) força
        # essa leitura de verdade e falha cedo se o arquivo não é um SQLite.
        conn.execute("SELECT * FROM sqlite_master LIMIT 1")
    except sqlite3.DatabaseError as e:
        raise AnkiImportError(
            "O banco de dados dentro do .apkg está corrompido ou não é um SQLite válido."
        ) from e
    return conn


def _carregar_modelos(conn: sqlite3.Connection) -> dict[int, dict]:
    """Lê col.models (JSON legado de compatibilidade, que o Anki mantém
    populado mesmo em coleções "schema 18+") pra saber, por note type
    (mid), se é 'Basic-like' — ver escopo no docstring do módulo.

    Se esse JSON não existir ou vier vazio, devolve {} — toda nota cai em
    "tipo de nota desconhecido" e é pulada, nunca um palpite errado.
    """
    try:
        (models_json,) = conn.execute("SELECT models FROM col").fetchone()
    except (sqlite3.OperationalError, TypeError) as e:
        raise AnkiImportError(
            "Tabela 'col' ausente ou ilegível — não parece uma coleção Anki válida."
        ) from e

    if not models_json:
        return {}
    try:
        modelos = json.loads(models_json)
    except json.JSONDecodeError:
        return {}

    return {
        int(mid): {
            "basic_like": modelo.get("type", 0) == 0 and len(modelo.get("tmpls", [])) == 1,
        }
        for mid, modelo in modelos.items()
    }


def _ler_cards(conn: sqlite3.Connection) -> ResultadoParse:
    modelos = _carregar_modelos(conn)

    try:
        linhas = conn.execute(
            "SELECT c.factor, c.ivl, n.flds, n.tags, n.mid "
            "FROM cards c JOIN notes n ON c.nid = n.id"
        ).fetchall()
    except sqlite3.OperationalError as e:
        raise AnkiImportError(
            "Tabelas 'cards'/'notes' ausentes ou ilegíveis — coleção Anki incompleta ou corrompida."
        ) from e

    resultado = ResultadoParse(cards=[])
    for factor, ivl, flds, tags_raw, mid in linhas:
        info_modelo = modelos.get(mid)
        if info_modelo is None:
            resultado._registrar_pulado("tipo_de_nota_desconhecido")
            continue
        if not info_modelo["basic_like"]:
            resultado._registrar_pulado("cloze_ou_tipo_customizado")
            continue

        campos = flds.split("\x1f")
        if len(campos) < 2:
            resultado._registrar_pulado("campos_insuficientes")
            continue

        tags = [t for t in (tags_raw or "").split(" ") if t]
        resultado.cards.append({
            "front": campos[0],
            "back": campos[1],
            "tags": tags,
            "ease": factor,    # cru: permille (ex: 2500 = fator 2.5) — conversão fica pro mapeamento
            "interval": ivl,   # cru: dias (positivo) ou segundos (negativo, relearning) — idem
        })

    if not resultado.cards and resultado.pulados == 0:
        raise AnkiImportError("A coleção não tem nenhum card.")

    return resultado


def parse_apkg(caminho_apkg: str | Path) -> ResultadoParse:
    """Extrai front/back/tags/ease/interval de um .apkg.

    Levanta AnkiImportError se o arquivo não existir, não for um .apkg
    válido, estiver corrompido, ou não tiver nenhum card. O diretório
    temporário de extração e a conexão SQLite são sempre fechados/
    apagados ao final, mesmo em erro (TemporaryDirectory + contextlib.closing).
    """
    caminho_apkg = Path(caminho_apkg)
    if not caminho_apkg.exists():
        raise AnkiImportError(f"Arquivo não encontrado: {caminho_apkg}")

    try:
        with TemporaryDirectory(prefix="estalo_anki_import_") as tmp:
            destino = Path(tmp)
            caminho_sqlite = _extrair_colecao(caminho_apkg, destino)
            conn = _conectar_leitura(caminho_sqlite)
            with closing(conn):
                return _ler_cards(conn)
    except AnkiImportError:
        raise
    except Exception as e:
        raise AnkiImportError(
            "Falha inesperada ao processar o .apkg — o arquivo pode estar corrompido."
        ) from e
