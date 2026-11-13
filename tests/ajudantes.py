"""Ferramentas comuns aos testes: banco SQLite temporário, arquivos de exemplo e um gerador de .xlsx mínimo.

Nenhum teste toca no banco real (dados/open-balance.db), no .env nem na internet.
"""

import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock
from xml.sax.saxutils import escape

from openbalance import banco

PASTA_ARQUIVOS = Path(__file__).resolve().parent / "arquivos"


def arquivo(nome):
    """Bytes de um arquivo de exemplo de tests/arquivos (todos inventados)."""
    return (PASTA_ARQUIVOS / nome).read_bytes()


def _sem_rede(*args, **kwargs):
    raise AssertionError("teste tentou acessar a rede")


class TesteComBanco(unittest.TestCase):
    """Cada teste ganha um banco novo numa pasta temporária, com a rede bloqueada e o .env ignorado."""

    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        for alvo in ("socket.create_connection", "urllib.request.urlopen"):
            p = mock.patch(alvo, _sem_rede)
            p.start()
            self.addCleanup(p.stop)
        # Sem .env: só os itens importados aparecem (como para quem recebe o app pelo compartilhar.py).
        p = mock.patch("openbalance.analise.itens_configurados", return_value=[])
        p.start()
        self.addCleanup(p.stop)
        self.conexao = banco.conectar(Path(pasta.name) / "teste.db")
        self.addCleanup(self.conexao.close)

    def contar(self, tabela, onde="1=1", parametros=()):
        return self.conexao.execute(f"SELECT count(*) FROM {tabela} WHERE {onde}", parametros).fetchone()[0]


# ---------------------------------------------------------------- .xlsx mínimo (só biblioteca padrão)
def _referencia(linha, coluna):
    letras = ""
    coluna += 1
    while coluna:
        coluna, resto = divmod(coluna - 1, 26)
        letras = chr(65 + resto) + letras
    return f"{letras}{linha + 1}"


def gerar_xlsx(abas):
    """abas = {nome: [[células]]}. str vira texto compartilhado, int/float vira número e
    ('data', serial_do_excel) vira número com formato de data (estilo 1)."""
    textos, indices = [], {}

    def indice_texto(t):
        if t not in indices:
            indices[t] = len(textos)
            textos.append(t)
        return indices[t]

    folhas = []
    for linhas in abas.values():
        xml_linhas = []
        for i, linha in enumerate(linhas):
            celulas = []
            for j, valor in enumerate(linha):
                ref = _referencia(i, j)
                if valor is None or valor == "":
                    continue
                if isinstance(valor, tuple) and valor[0] == "data":
                    celulas.append(f'<c r="{ref}" s="1"><v>{valor[1]}</v></c>')
                elif isinstance(valor, (int, float)):
                    celulas.append(f'<c r="{ref}"><v>{valor}</v></c>')
                else:
                    celulas.append(f'<c r="{ref}" t="s"><v>{indice_texto(str(valor))}</v></c>')
            xml_linhas.append(f'<row r="{i + 1}">{"".join(celulas)}</row>')
        folhas.append('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
                      f'spreadsheetml/2006/main"><sheetData>{"".join(xml_linhas)}</sheetData></worksheet>')

    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    ns_r = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    livro = (f'<?xml version="1.0" encoding="UTF-8"?><workbook {ns} {ns_r}><sheets>'
             + "".join(f'<sheet name="{escape(nome)}" sheetId="{k + 1}" r:id="rId{k + 1}"/>' for k, nome in enumerate(abas))
             + "</sheets></workbook>")
    relacoes = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
                '2006/relationships">'
                + "".join(f'<Relationship Id="rId{k + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                          f'relationships/worksheet" Target="worksheets/sheet{k + 1}.xml"/>' for k in range(len(abas)))
                + "</Relationships>")
    compartilhadas = (f'<?xml version="1.0" encoding="UTF-8"?><sst {ns} count="{len(textos)}" uniqueCount="{len(textos)}">'
                      + "".join(f"<si><t>{escape(t)}</t></si>" for t in textos) + "</sst>")
    estilos = (f'<?xml version="1.0" encoding="UTF-8"?><styleSheet {ns}><cellXfs count="2">'
               '<xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs></styleSheet>')

    saida = BytesIO()
    with zipfile.ZipFile(saida, "w") as z:
        z.writestr("xl/workbook.xml", livro)
        z.writestr("xl/_rels/workbook.xml.rels", relacoes)
        z.writestr("xl/sharedStrings.xml", compartilhadas)
        z.writestr("xl/styles.xml", estilos)
        for k, folha in enumerate(folhas):
            z.writestr(f"xl/worksheets/sheet{k + 1}.xml", folha)
    return saida.getvalue()
