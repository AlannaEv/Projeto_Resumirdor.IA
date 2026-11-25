# Projeto_Resumirdor.IA

Aplicação para resumir, fichar e consultar documentos científicos e técnicos.
O projeto combina uma API REST em FastAPI, uma interface em Streamlit e análise
de texto com Google Gemini, mantendo as respostas fundamentadas no documento
fornecido.

## Funcionalidades

- Upload de documentos PDF, TXT e Markdown ou colagem direta de texto.
- Extração de texto de PDF com PyMuPDF e opção de remover referências finais.
- Análise em streaming e consulta livre sobre o documento.
- Modos: Tópicos Principais, Fichamento Científico, Glossário de Termos
  Complexos, Gerar Questões de Estudo e Perguntas e Respostas.
- Histórico persistente de conversas em SQLite, com opção para excluir chats.
- Exportação do histórico em Markdown ou texto simples.
- Respostas orientadas por regras para evitar informações que não constem na
  fonte. O sistema instrui o modelo a indicar quando uma informação não está
  presente no documento.
- Retry com backoff e fallback entre modelos Gemini para erros temporários e
  limites de requisição.

## Arquitetura

- `api.py`: backend FastAPI, upload, análise em streaming e endpoints de chats.
- `app.py`: frontend Streamlit, que consome a API por HTTP.
- `core/pdf_parser.py`: extração e normalização dos documentos.
- `core/summarizer.py`: presets, instruções de fundamentação e integração Gemini.
- `core/database.py`: persistência SQLite de conversas, mensagens e documentos.
- `docs/API_INTEGRATION.md`: especificação dos endpoints e exemplo de consumo
  do streaming.

## Requisitos

- Python 3.10 ou superior.
- Uma chave de API do Google Gemini.
- Docker e Docker Compose (opcional, para execução containerizada).

## Configuração local

Crie um ambiente virtual e instale as dependências. No PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Crie um arquivo `.env` na raiz do projeto:

```dotenv
GOOGLE_API_KEY=sua_chave_da_api
API_BASE_URL=http://localhost:8001
```

O `.env` é ignorado pelo Git; não coloque chaves ou credenciais no código-fonte.
`DB_PATH` é opcional para escolher outro caminho para o banco SQLite. Sem essa
variável, o banco local é criado como `chats.db` na raiz do projeto.

### Iniciar os serviços

Inicie o backend em um terminal:

```powershell
python -m uvicorn api:app --reload --port 8001
```

Inicie o frontend em outro terminal:

```powershell
python -m streamlit run app.py --server.port 8501
```

A aplicação fica disponível em <http://localhost:8501>. A documentação
interativa da API fica em <http://localhost:8001/docs>, e o health check em
<http://localhost:8001/health>.

Se usar outro endereço para o backend, ajuste `API_BASE_URL` no ambiente do
Streamlit.

## Executar com Docker Compose

Com Docker Compose instalado e o `.env` criado na raiz:

```powershell
docker compose up --build
```

O frontend fica em <http://localhost:8501> e a API em
<http://localhost:8001>. O Compose guarda o banco em um volume nomeado para
preservar conversas entre reinicializações dos containers.

Para parar os serviços, use `Ctrl+C` ou execute:

```powershell
docker compose down
```

O volume SQLite é mantido ao parar os containers.

## Testes e validação

Com o ambiente virtual ativado:

```powershell
python -m unittest discover -s tests
python -m py_compile app.py api.py core/summarizer.py
```

## API

Os endpoints incluem `GET /health`, `POST /api/upload`, `POST /api/analyze`,
`POST /api/analyze-direct` e operações de histórico em `/api/chats`.
A análise retorna texto em streaming; o upload retorna os metadados e o hash
usado para identificar o documento.

Consulte [docs/API_INTEGRATION.md](docs/API_INTEGRATION.md) para payloads,
respostas, erros e exemplo de consumo do stream.