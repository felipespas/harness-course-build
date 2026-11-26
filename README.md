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
   - `AZURE_OPENAI_ENDPOINT`: the full OpenAI v1 endpoint from your Foundry
     deployment's code sample, such as
     `https://YOUR-RESOURCE.services.ai.azure.com/openai/v1`.
   - `AZURE_OPENAI_DEPLOYMENT`: your deployment name, not necessarily the model name.
5. Use a deployed model supporting Chat Completions and tool calling.
   Have an administrator assign your identity the **Cognitive Services OpenAI User**
   role on the Azure OpenAI resource.
6. Install the Azure CLI if needed and sign in with `az login`.
   Authentication uses `DefaultAzureCredential`; no API key is required.
   An existing local `az-login.ps1` helper is gitignored.
   When hosted in Azure, enable a managed identity and assign it the same role.
7. Start Docker Desktop (or a compatible Docker daemon) with Linux containers.
8. Set `TAVILY_API_KEY` in `.env` to use the existing web search tool.
   Tavily authentication is separate from Azure model authentication.

The harness uses the `OpenAI` v1 client with the
`https://ai.azure.com/.default` token scope. No API version setting is needed.
The endpoint must already include `/openai/v1`; a bare project endpoint ending
in `/api/projects/YOUR-PROJECT` is not an OpenAI v1 base URL.

Azure settings take precedence over the original backends. If either Azure
setting is present, both must be nonblank or startup fails with a clear error.
To use the original OpenAI or Kimi backend, remove both Azure settings from
your environment and `.env`, then configure the original API keys.
The model from [harness/config.py](harness/config.py) remains the default for
those original backends; Foundry uses `AZURE_OPENAI_DEPLOYMENT` instead.
The ReAct loop, step budget, tools, prompts, Docker sandbox, Tavily web search,
and memory consolidation are unchanged. Consolidation uses the same Foundry
deployment as the conversation.

## Running

With your virtual environment activated, Docker running, and `.env` configured:

```
python -m harness.agent
```

Type `quit` or `exit` to consolidate memory and tear down the sandbox.

### Debugging in VS Code

Install the Python and Python Debugger extensions and select your virtual
environment with **Python: Select Interpreter**. Set breakpoints, choose
**Debug Agent Harness** in Run and Debug, and press **F5**.
The [launch configuration](.vscode/launch.json) runs `harness.agent`, loads
`.env`, and uses the integrated terminal for conversation input.
Docker must also be running when debugging.

If Foundry reports a token tenant mismatch, sign in to the resource's tenant
and select its subscription before restarting:

```
az login --tenant <resource-tenant-id>
az account set --subscription <resource-subscription-id>
```

Run regression tests without Azure, Docker, or Tavily access:

```
python -m unittest discover -s tests -v
```