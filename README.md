# TeamViewer Human-in-the-Loop Agent

A Windows-first service-desk agent built with Microsoft Agent Framework, Microsoft Foundry Local,
and TeamViewer's official MCP server. Read-only TeamViewer tools can run automatically. Every
exposed state-changing tool is paused until a human reviews the exact tool name and arguments and
types `APPROVE`.

The project can also use a cloud Microsoft Foundry project, but Foundry Local is the default and
the primary setup documented below.

## What this project does

- Reads TeamViewer account, device, group, monitoring, session, report, and event-log data.
- Uses a local `phi-4-mini` model through Foundry Local for prompt processing and tool selection.
- Connects to TeamViewer's official MCP server over local stdio.
- Adds one narrow read-only managed-group composition built exclusively from official TeamViewer
  MCP tools.
- Requires a fresh human decision before every allowed state-changing MCP call.
- Records approvals and rejections in `.audit/teamviewer-approvals.jsonl`.
- Hides high-risk TeamViewer administration tools from the model entirely.

The current policy exposes 32 of the TeamViewer MCP server's tools plus one application-level
read-only composition that calls only those MCP tools. Operations such as account creation, user
deletion, TFA deactivation, permanent-token management, device deletion, and policy deletion are
not available to the agent.

## Architecture and approval boundary

```text
Operator prompt
    |
    v
Microsoft Agent Framework agent
    |
    v
TeamViewer MCP allow-list
    |-- read-only tool -----------> execute and return evidence
    |
    `-- state-changing tool ------> display exact call
                                      |
                                      `-- APPROVE -> execute
                                          anything else -> reject

Managed-group query -------------> exact group-name resolution via TeamViewer MCP
                                    -> company devices via TeamViewer MCP
                                    -> device group membership via TeamViewer MCP
                                    -> return verified membership
```

This approval gate supplements TeamViewer token scopes; it does not replace them. Keep the
TeamViewer token narrowly scoped and review the allow-list with `--show-policy`.

## Prerequisites

This guide assumes Windows 10 or 11 and PowerShell.

- Git
- Python 3.10 or newer
- Node.js 18 or newer
- Microsoft Foundry Local
- A TeamViewer account and license with Web API access
- Internet access for the first dependency and model downloads

Install the command-line prerequisites with `winget` if they are not already available:

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Microsoft.FoundryLocal -e
```

Close and reopen PowerShell after installing them, then verify:

```powershell
git --version
py --version
node --version
cmd /c npm --version
foundry --version
```

`cmd /c npm` is used throughout this guide because some Windows environments block `npm.ps1`
through the PowerShell execution policy.

## Complete setup from scratch

### 1. Clone this repository

```powershell
Set-Location $env:USERPROFILE
git clone https://github.com/pta19059/teamviewer-hitl-agent-foundry-local.git
Set-Location .\teamviewer-hitl-agent-foundry-local
```

### 2. Create the Python environment

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

This creates the local command:

```text
.venv\Scripts\teamviewer-hitl.exe
```

It is the console entry point for the Python distribution `teamviewer-hitl-agent` and calls
`teamviewer_hitl.cli:main`.

### 3. Download and build TeamViewer's official MCP server

The TeamViewer MCP source is an external dependency and is intentionally not copied into this
repository.

```powershell
New-Item -ItemType Directory -Force external | Out-Null
git clone https://github.com/teamviewer/TV_Remote_MCP.git external\TV_Remote_MCP
cmd /c npm install --prefix external\TV_Remote_MCP
cmd /c npm run build --prefix external\TV_Remote_MCP
Test-Path external\TV_Remote_MCP\dist\index.js
```

The final command must return `True`.

If the MCP repository already exists but is not built, run only:

```powershell
cmd /c npm install --prefix external\TV_Remote_MCP
cmd /c npm run build --prefix external\TV_Remote_MCP
```

### 4. Create a TeamViewer script token

Create a **script token**, not an OAuth Client ID or Client Secret:

1. Sign in to the TeamViewer web app or Management Console.
2. Open your profile and select **Apps & Tokens** or **Apps**.
3. Select **Create script token**.
4. Choose User/Account access when the UI asks for an access level.
5. Select only the permissions required by your use case.
6. Copy the complete token value.

For the first read-only tests, the relevant technical scopes are:

- `UserInfo.View` for account information.
- `Computers.View` for the device list and online state. Some TeamViewer interfaces label this
  **Computers & Contacts - View entries**.

For support-session and reporting workflows, add the corresponding permissions such as
`SessionCode.Create`, `Reports.View`, and `EventLogging.View`. Add monitoring and policy scopes
only when those features are needed.

TeamViewer tokens cannot be edited after creation. If a scope is missing, create a replacement
token. Never commit or paste a real token into an issue, terminal transcript, or chat.

### 5. Create the local configuration

```powershell
Copy-Item .env.example .env
notepad .env
```

For Foundry Local and a local TeamViewer MCP process, configure at least:

```dotenv
MODEL_PROVIDER=foundry_local
FOUNDRY_LOCAL_MODEL=phi-4-mini
FOUNDRY_LOCAL_ENDPOINT=

TEAMVIEWER_MCP_TRANSPORT=local
TEAMVIEWER_MCP_COMMAND=node
TEAMVIEWER_MCP_SCRIPT=external/TV_Remote_MCP/dist/index.js
TEAMVIEWER_API_TOKEN=PASTE_THE_COMPLETE_SCRIPT_TOKEN_HERE

OPERATOR_ID=your.name@company.example
```

The `.env` file is ignored by Git. Keep it only on the machine running the agent.

### 6. Start Foundry Local and load the model

First inspect the CLI command groups available in your installed version:

```powershell
foundry --help
```

Foundry Local CLI 0.10.x, which this project has been tested against, uses `server`:

```powershell
foundry server start
foundry model info phi-4-mini
foundry model download phi-4-mini
foundry model load phi-4-mini
foundry server status
```

Newer Foundry Local documentation uses `service`. If `foundry --help` lists `service` instead of
`server`, use:

```powershell
foundry service start
foundry model info phi-4-mini
foundry model download phi-4-mini
foundry model load phi-4-mini
foundry service status
```

The first model download is several gigabytes and can take several minutes. The model alias lets
Foundry Local select a compatible CPU, GPU, or NPU variant for the machine.

The status command prints an OpenAI-compatible loopback URL such as:

```text
http://127.0.0.1:62911
```

Foundry Local can assign a different port after a restart. The application tries to discover the
URL automatically with the tested `server` CLI. If automatic discovery fails, set the URL shown
by the status command explicitly in `.env` without `/v1`:

```dotenv
FOUNDRY_LOCAL_ENDPOINT=http://127.0.0.1:62911
```

The application validates that this override is an HTTP loopback address and appends `/v1`
automatically.

Optionally verify the local API, replacing the port with the one shown on your machine:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:62911/v1/models" -Method Get
```

### 7. Verify the installation without TeamViewer calls

Display the exact read-only and approval-required tool policy:

```powershell
.\.venv\Scripts\teamviewer-hitl.exe --show-policy
```

Run the automated tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests do not call TeamViewer or Microsoft Foundry cloud services.

### 8. Run read-only live tests

Start with one TeamViewer operation per prompt. This is especially reliable with the small local
`phi-4-mini` model.

Test account access:

```powershell
.\.venv\Scripts\teamviewer-hitl.exe "Use only tv_get_account and show my TeamViewer account summary."
```

Test the online device list:

```powershell
.\.venv\Scripts\teamviewer-hitl.exe "Use only tv_list_devices with online_state Online and list the online TeamViewer devices."
```

Test a newer managed device group by exact name:

```powershell
.\.venv\Scripts\teamviewer-hitl.exe "Use tv_list_devices_in_managed_group to show the devices in StefanoGroup."
```

Do not use `tv_list_devices` for a group displayed in TeamViewer's newer managed-device hierarchy.
That tool reads the separate legacy Computers & Contacts inventory.

Run an interactive session:

```powershell
.\.venv\Scripts\teamviewer-hitl.exe
```

Type `exit` or `quit` to stop the interactive session.

### 9. Test Human-in-the-Loop approval

Use a test target that you are authorized to operate:

```powershell
.\.venv\Scripts\teamviewer-hitl.exe "Create a TeamViewer support session named HITL-Test."
```

Before the MCP call executes, the application displays:

```text
--- HUMAN APPROVAL REQUIRED ---
Tool: tv_create_session
Arguments:
...
Type APPROVE to execute this exact call. Any other response rejects it.
```

For a rejection-path test, type anything other than `APPROVE`. For an execution test, verify the
target and arguments carefully and then type exactly `APPROVE`.

Approval decisions are appended to:

```text
.audit\teamviewer-approvals.jsonl
```

The audit entry records the decision, not proof that the downstream TeamViewer operation
succeeded. The agent reports tool success only when the MCP call itself returns success.

## Available commands

```powershell
# Help
.\.venv\Scripts\teamviewer-hitl.exe --help

# Show the security policy without credentials
.\.venv\Scripts\teamviewer-hitl.exe --show-policy

# One-shot request
.\.venv\Scripts\teamviewer-hitl.exe "Use only tv_get_account and summarize the account."

# Interactive mode
.\.venv\Scripts\teamviewer-hitl.exe

# Run the module without the generated console executable
.\.venv\Scripts\python.exe -m teamviewer_hitl.cli

# Run tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Troubleshooting

### `TEAMVIEWER_MCP_SCRIPT does not exist`

The official MCP server has not been built, or `TEAMVIEWER_MCP_SCRIPT` points to the wrong file:

```powershell
cmd /c npm install --prefix external\TV_Remote_MCP
cmd /c npm run build --prefix external\TV_Remote_MCP
Test-Path external\TV_Remote_MCP\dist\index.js
```

### npm returns `ECONNRESET`

A VPN, proxy, TLS-inspection product, or firewall is interrupting access to the npm registry.
Verify access to the official package archive before retrying:

```powershell
curl.exe -I https://registry.npmjs.org/zod-to-json-schema/-/zod-to-json-schema-3.25.2.tgz
```

If your organization requires a proxy, use the proxy or internal npm registry supplied by your
IT team. Do not disable corporate security controls without authorization.

### Foundry reports that the daemon is already running

Do not repeatedly start it. Inspect the existing instance:

```powershell
foundry server status
foundry server logs
```

For a CLI that uses the newer command family:

```powershell
foundry service status
foundry service diag
```

Copy the reported loopback URL into `FOUNDRY_LOCAL_ENDPOINT` if automatic discovery is unable to
see the existing daemon.

### `Could not discover Foundry Local`

1. Confirm that the service/server is running.
2. Confirm that the model is loaded.
3. Set the current loopback URL explicitly in `.env`.
4. Verify `/v1/models` with `Invoke-RestMethod`.

### TeamViewer returns `Access token invalid`

The value supplied to `TEAMVIEWER_API_TOKEN` is not accepted as a bearer token. Confirm that:

- The token is a TeamViewer **script token** rather than an OAuth Client ID or Client Secret.
- The complete token was copied into the root `.env` file.
- The token has not been deleted or revoked.
- There is exactly one `TEAMVIEWER_API_TOKEN=` line.

Do not post the token while troubleshooting.

### TeamViewer returns `Access token does not have the required permissions`

The token is valid but lacks the scope for the requested endpoint. For example,
`tv_list_devices` requires `Computers.View`, commonly shown as **Computers & Contacts - View
entries**. Create a replacement script token with the missing scope and update `.env`.

### The local model describes a tool but does not call it

This project requires the first tool selection for Foundry Local so that `phi-4-mini` emits a
structured call instead of merely describing one. Keep prompts explicit and request one operation
at a time for the most predictable local-model behavior.

### A named group returns unrelated devices

TeamViewer has two separate inventory models:

- `tv_list_device_groups` and `tv_list_devices` read legacy Computers & Contacts groups.
- `tv_list_devices_in_managed_group` resolves the newer managed group and verifies membership by
  composing the official `tv_list_managed_groups`, `tv_list_company_managed_devices`, and
  `tv_get_managed_device_groups` MCP tools.

For a group shown in the modern managed-device hierarchy, use the managed-group composition. It
matches the group name exactly, rejects ambiguous names, follows pagination, and returns only the
membership supplied by TeamViewer.

## Cloud Microsoft Foundry option

Set the following values instead of the Foundry Local settings:

```dotenv
MODEL_PROVIDER=foundry_cloud
FOUNDRY_PROJECT_ENDPOINT=https://YOUR-RESOURCE.services.ai.azure.com/api/projects/YOUR-PROJECT
FOUNDRY_MODEL=YOUR-DEPLOYMENT-NAME
```

Authenticate before running the agent:

```powershell
az login
.\.venv\Scripts\teamviewer-hitl.exe
```

The local TeamViewer MCP and HITL policy remain the same. Only model inference moves to the cloud
provider.

## Remote MCP transport

To connect to a TeamViewer MCP server that you host over Streamable HTTP:

```dotenv
TEAMVIEWER_MCP_TRANSPORT=http
TEAMVIEWER_MCP_URL=https://your-mcp-host.example/mcp
TEAMVIEWER_MCP_BEARER_TOKEN=YOUR_MCP_SERVER_BEARER_TOKEN
```

Use HTTPS outside localhost. `TEAMVIEWER_MCP_BEARER_TOKEN` protects access to your MCP server; it
is separate from the TeamViewer API token used by that server.

The `tv_list_devices_in_managed_group` composition works with both local stdio and remote HTTP MCP
transports. It never calls TeamViewer Web API directly from Python; every TeamViewer request crosses
the configured MCP transport.

## Data locality

With `MODEL_PROVIDER=foundry_local`, prompts, inference, conversation history, and tool-selection
reasoning run through the model on the local machine. The Agent Framework host and HITL gate also
run locally.

The solution is not fully offline. The TeamViewer MCP server still calls TeamViewer Web API, and
returned TeamViewer data is passed to the local model to formulate an answer. The Python agent host
does not call TeamViewer Web API directly. Foundry Local also requires internet access for initial
model and execution-provider downloads.

## Production hardening

- Replace console approvals with authenticated approval cards or an internal approval portal.
- Persist sessions and pending approvals in a durable store before running multiple replicas.
- Add operator RBAC, approval expiry, target binding, and separation of duties.
- Send decisions and MCP execution telemetry to an append-only audit or SIEM system.
- Use delegated OAuth per operator instead of a shared script token.
- Keep the MCP allow-list smaller than the token scope whenever possible.
- Pin and review dependency updates and run security scans before deployment.

## Primary references

- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Microsoft Agent Framework local MCP tools](https://learn.microsoft.com/en-us/agent-framework/agents/tools/local-mcp-tools)
- [Microsoft Agent Framework tool approval](https://learn.microsoft.com/en-us/agent-framework/agents/tools/tool-approval)
- [Microsoft Agent Framework Human-in-the-Loop workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop)
- [Microsoft Foundry Local CLI](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-cli)
- [TeamViewer MCP interface](https://www.teamviewer.com/en/global/support/knowledge-base/teamviewer-remote/teamviewer-ai/teamviewer-mcp-interface/)
- [TeamViewer official self-hosted MCP server](https://github.com/teamviewer/TV_Remote_MCP)
- [TeamViewer Web API documentation](https://webapi.teamviewer.com/api/v1/docs/index)
