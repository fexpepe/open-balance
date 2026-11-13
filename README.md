# Open Balance

Painel de finanças pessoais que roda só no seu computador: contas, cartões, faturas,
parcelamentos, assinaturas, orçamento e investimentos em um lugar só.

- **Local:** os dados ficam em um arquivo SQLite na pasta `dados/`. O painel só atende em `127.0.0.1`.
- **Sem dependências:** Python 3.10 ou mais novo, apenas a biblioteca padrão. A interface é HTML, CSS e JavaScript puros.
- **Dois jeitos de alimentar:** arquivos exportados do banco (OFX, CSV, TXT, Excel) ou conexão automática pelo Open Finance, via Pluggy.

![Visão geral do mês: resumo, ritmo de gastos, contas, cartões e principais categorias](docs/visao-geral.png)

| Categorias | Cartões |
| --- | --- |
| ![Gasto do mês por categoria, comparado com a média de 6 meses](docs/categorias.png) | ![Fatura aberta, limite e parcelas já comprometidas nos próximos meses](docs/cartoes.png) |

As telas acima usam dados fictícios.

## O que tem

**Dia a dia**

- Visão geral do mês, previsão de saldo e lista de transações
- Parcelamentos, assinaturas e cartões (faturas, parcelas futuras, limite)
- Categorias com regras próprias e uma fila "A revisar" para o que ficou genérico
- Orçamento mensal por categoria e fechamento do mês

**Investimentos**

- Carteira por classe (renda fixa, Tesouro, ações, FIIs, ETFs, fundos, exterior, cripto) e metas de alocação
- Rentabilidade por cotas (TWR) comparada com CDI, IPCA e Ibovespa
- Evolução do patrimônio e rendimento mês a mês
- Proventos a receber, pela API pública da B3
- Tesouro Direto marcado a mercado com os preços do Tesouro Transparente
- Estimativa de imposto de renda: apuração mensal da renda variável e resumo para a declaração

## Como usar

1. Instale o [Python](https://www.python.org/downloads/) 3.10 ou mais novo. No Windows, marque "Add python.exe to PATH".
2. Baixe este repositório (botão **Code → Download ZIP**, ou `git clone`).
3. Abra o painel:
   - Windows: dois cliques em `Abrir Open Balance.bat`
   - Qualquer sistema: `python app.py`
4. O navegador abre em `http://127.0.0.1:8765`. Vá na aba **Importar** e arraste os extratos e faturas do seu banco.

O passo a passo completo, com dicas de exportação e de backup, está em [LEIA-ME.txt](LEIA-ME.txt).

A rotina diária agendada (`python app.py --agendar`) usa o Agendador de Tarefas do Windows. O restante funciona em qualquer sistema.

## Conexão pelo Open Finance (opcional)

Em vez de exportar arquivos todo mês, dá para conectar os bancos pela [Pluggy](https://pluggy.ai),
gratuita para uso pessoal pelo conector MeuPluggy. O passo a passo fica na aba **Importar**, em
"Conectar pelo Open Finance".

Você usa a sua própria conta da Pluggy. As credenciais ficam no arquivo `.env` desta pasta, que
não vai para o git. O Open Balance só lê dados; nunca faz pagamentos nem transferências.

## Seus dados

- Tudo o que é seu fica em `dados/`, `dados_brutos/` e `.env`, e os três estão no `.gitignore`.
- Uma cópia de segurança é guardada por dia em `dados/backup/`.
- Não coloque a pasta do projeto em serviços de sincronização (Google Drive, OneDrive, Dropbox).
- Se for contribuir, nunca use um extrato real como arquivo de teste. Os exemplos em `tests/arquivos/` são fictícios.

## Fontes de dados públicas

As cotações e os índices vêm de serviços públicos, consultados a partir do seu computador:
B3, CVM, Tesouro Transparente, Ipeadata e Yahoo Finance.

## Testes

```bash
python -m unittest
```

Os testes não usam rede nem o banco real.

## Avisos

O Open Balance é um projeto pessoal, sem garantia. Os valores de rentabilidade e de imposto são
estimativas feitas com os dados disponíveis e não substituem o informe do banco, um contador ou
orientação financeira.

## Licença

[MIT](LICENSE)
