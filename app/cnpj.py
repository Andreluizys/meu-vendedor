"""Importa empresas dos Dados Abertos do CNPJ (Receita Federal), a partir de arquivos que o usuário baixou.

Coloque em data/cnpj/ os arquivos "Estabelecimentos*.zip" (ou .csv) do portal de dados abertos do CNPJ.
Eles são lidos aos poucos (sem carregar tudo na memória) e só as empresas do ramo pedido são guardadas.
Os códigos de atividade (CNAE) abaixo são aproximados: confira no site do IBGE/CONCLA se precisar de exatidão.
O e-mail do cadastro costuma ser do contador. Use com base legal (LGPD) e respeite pedidos de descadastro.
"""
import csv
import io
import unicodedata
import zipfile
from pathlib import Path

from . import config

CNPJ_DIR = config.DATA_DIR / "cnpj"

# palavras do nicho -> CNAEs principais (7 dígitos, sem pontuação)
CNAE_BY_KEYWORD = {
    ("manicure", "pedicure", "cabeleireiro", "cabeleireira", "salao de beleza", "salao", "barbearia", "barbeiro"): ["9602501"],
    ("estetica", "esteticista", "depilacao", "sobrancelha", "spa"): ["9602502"],
    ("restaurante",): ["5611201"],
    ("lanchonete", "hamburgueria", "pizzaria"): ["5611203"],
    ("loja de roupa", "moda", "boutique", "vestuario"): ["4781400"],
    ("academia", "musculacao", "fitness"): ["9313100"],
    ("dentista", "odontologica", "odontologia"): ["8630504"],
    ("pet shop", "petshop"): ["4789004"],
    ("banho e tosa", "tosa"): ["9609208"],
    ("padaria", "panificadora"): ["1091101"],
    ("oficina mecanica", "mecanica"): ["4520001"],
    ("contabilidade", "contador", "escritorio contabil"): ["6920601"],
    ("advocacia", "advogado", "escritorio de advocacia"): ["6911701"],
}

# posições das colunas do arquivo Estabelecimentos (sem cabeçalho, separado por ";")
C_BASICO, C_ORDEM, C_DV, C_FANTASIA, C_SITUACAO, C_CNAE = 0, 1, 2, 4, 5, 11
C_LOGR_TIPO, C_LOGR, C_NUM, C_BAIRRO, C_CEP, C_UF = 13, 14, 15, 17, 18, 19
C_DDD1, C_TEL1, C_EMAIL = 21, 22, 27
ATIVA = "02"


class CnpjError(Exception):
    """Erro legível para mostrar ao usuário."""


def _norm(text: str) -> str:
    sem = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return sem.lower().strip()


def cnaes_for(niche: str) -> list[str]:
    """Aceita um nicho em texto ("manicure") ou um código CNAE direto ("9602-5/01")."""
    digitos = "".join(c for c in niche if c.isdigit())
    if len(digitos) == 7:
        return [digitos]
    n = _norm(niche)
    found: list[str] = []
    for palavras, codigos in CNAE_BY_KEYWORD.items():
        if any(p in n for p in palavras):
            found += [c for c in codigos if c not in found]
    return found


def _csv_streams(folder: Path):
    """Gera (nome, arquivo-texto) de cada CSV dentro da pasta (inclusive dentro de .zip)."""
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if not name.endswith("/"):
                        with z.open(name) as raw:
                            yield f"{path.name}/{name}", io.TextIOWrapper(raw, encoding="latin-1", newline="")
        elif path.suffix.lower() in (".csv", ".txt") or "ESTABELE" in path.name.upper():
            with open(path, encoding="latin-1", newline="") as f:
                yield path.name, f


def _lead(row: list[str], niche: str) -> dict:
    full = f"{row[C_BASICO]}{row[C_ORDEM]}{row[C_DV]}"
    ddd, tel = row[C_DDD1].strip(), row[C_TEL1].strip()
    rua = " ".join(x for x in (row[C_LOGR_TIPO], row[C_LOGR], row[C_NUM]) if x.strip())
    endereco = ", ".join(x for x in (rua, row[C_BAIRRO], row[C_UF], row[C_CEP]) if x.strip())
    return {
        "place_id": f"cnpj:{full}",
        "name": row[C_FANTASIA].strip().title() or f"CNPJ {full}",
        "address": endereco,
        "phone": f"({ddd}) {tel}" if ddd and tel else tel,
        "email": row[C_EMAIL].strip().lower(),
        "website": "", "maps_url": "", "rating": None, "reviews": None,
    }


def import_from_files(niche: str, uf: str = "", limit: int = 500, folder: Path | None = None) -> list[dict]:
    """Devolve até `limit` empresas ATIVAS do ramo (e UF, se informada)."""
    folder = folder or CNPJ_DIR
    codes = set(cnaes_for(niche))
    if not codes:
        raise CnpjError("Não conheço esse ramo. Digite o código CNAE com 7 dígitos (ex.: 9602501) ou um ramo comum, como manicure.")
    if not folder.exists() or not any(folder.iterdir()):
        raise CnpjError(f"Coloque os arquivos de Estabelecimentos da Receita na pasta {folder}")
    uf = uf.strip().upper()
    found: list[dict] = []
    for _nome, stream in _csv_streams(folder):
        for row in csv.reader(stream, delimiter=";", quotechar='"'):
            if len(row) <= C_EMAIL or row[C_SITUACAO] != ATIVA or row[C_CNAE] not in codes:
                continue
            if uf and row[C_UF].strip().upper() != uf:
                continue
            found.append(_lead(row, niche))
            if len(found) >= limit:
                return found
    return found
