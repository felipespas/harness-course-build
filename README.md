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
   - `AZURE_OPENAI_DEPLOYMENT`: your Azure deployment name, not necessarily the model name.
5. Deploy a model in Foundry supporting Chat Completions and tool calling.
   Have an administrator assign your identity the **Cognitive Services OpenAI User**
   role on the Azure OpenAI resource.
6. Install the Azure CLI if needed and sign in with `az login`.
   Authentication uses `DefaultAzureCredential`; no OpenAI, Kimi, or Azure API key
   is required. When hosted in Azure, enable a managed identity and assign it
   the same resource role.

The harness uses the `OpenAI` client with the
`https://ai.azure.com/.default` token scope. No API version setting is needed.
The endpoint must already include `/openai/v1`; a bare project endpoint ending
in `/api/projects/YOUR-PROJECT` is not an OpenAI v1 base URL.
Chat Completions, filesystem and git tools, and AGENTS.md memory are retained.

## Running

With your virtual environment activated and `.env` configured:

```
python -m harness.agent
```

Type `quit` or `exit` to stop. Blank required Azure settings produce a startup
error identifying the setting to fill in.

### Debugging in VS Code

Install the Microsoft Python and Python Debugger extensions, then use
**Python: Select Interpreter** to select the virtual environment created during
setup. Set breakpoints, select **Debug Agent Harness** in Run and Debug, and
press **F5**. The configuration in [.vscode/launch.json](.vscode/launch.json)
runs `harness.agent` from the repository root, loads `.env`, and accepts input
in the integrated terminal. The same Azure setup and sign-in are required.

If Foundry reports that the token tenant does not match the resource tenant,
sign in to the resource's tenant and select its subscription before restarting:

```
az login --tenant <resource-tenant-id>
az account set --subscription <resource-subscription-id>
```

Run the configuration and conversation regression tests without Azure access:

```
python -m unittest discover -s tests -v
```