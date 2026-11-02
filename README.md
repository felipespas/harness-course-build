# Agent Harness

A from-scratch agent harness, built over the course of nine chapters.

## Setup

1. Clone the repo and `cd` into it.
2. Create a virtual environment:
```
   python -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   .venv\Scripts\activate      # Windows
```
3. Install dependencies:
```
   pip install -r requirements.txt
```
4. Copy [.env.example](.env.example) to `.env` and configure:
   - `AZURE_OPENAI_ENDPOINT`: your resource endpoint, such as `https://YOUR-RESOURCE.openai.azure.com/`.
   - `AZURE_OPENAI_DEPLOYMENT`: your Azure deployment name, not necessarily the model name.
   - `AZURE_OPENAI_API_VERSION`: defaults in the example to `2024-10-21`; use a version supported by your deployment.
5. Deploy an Azure OpenAI model supporting Chat Completions and tool calling.
   Have an administrator assign your identity the **Cognitive Services OpenAI User**
   role on the Azure OpenAI resource.
6. Install the Azure CLI if needed and sign in with `az login`.
   Authentication uses `DefaultAzureCredential`; no OpenAI, Kimi, or Azure API key
   is required. When hosted in Azure, enable a managed identity and assign it
   the same resource role.

## Running

With your virtual environment activated and `.env` configured:

```
python -m harness.agent
```

Type `quit` or `exit` to stop. Blank required Azure settings produce a startup
error identifying the setting to fill in.