# TeamViewer Human-in-the-Loop Agent

A Windows-first service-desk agent built with Microsoft Agent Framework, Microsoft Foundry Local,
and TeamViewer's official MCP server. Read-only TeamViewer tools can run automatically. Every
exposed state-changing tool is paused until a human reviews the exact tool name and arguments and
types `APPROVE`.

The project can also use a cloud Microsoft Foundry project, but Foundry Local is the default and
the primary setup documented below.

## What this project does

- Reads TeamViewer account, device, group, monitoring, session, and report data. Event-log reads
  fail closed when the pinned official MCP server returns an unusable pagination token.
- Uses the local tool-capable `qwen2.5-7b` model through Foundry Local for conversation and every
  supported TeamViewer request. Read arguments remain deterministic and large MCP responses are
  bounded by the host before the verified result returns to Qwen.
- Connects to TeamViewer's official MCP server over local stdio.
- Uses Qwen to analyze and confirm the exact host-validated operation before any TeamViewer MCP
  call can run. The operation is enforced in the planner function's JSON Schema enum; neighboring
  tools from another identifier namespace cannot be selected.
- Uses typed MCP-only read adapters for API-compatible identifiers, filters, and pagination.
- Adds one read-only legacy/managed group resolver built exclusively from official TeamViewer MCP
  tools.
- Requires a fresh human decision before every allowed state-changing MCP call.
- Validates argument shape, exact identifier provenance, and mutable values before approval and
  again before execution.
- Records approvals and rejections in `.audit/teamviewer-approvals.jsonl`.
- Hides high-risk TeamViewer administration tools from the model entirely.

The upstream MCP connection allows 30 TeamViewer operations: 24 reads and 6 writes. Qwen analyzes
and confirms the operation using an internal non-executing planning function whose schema contains
only the exact operation proven by host parsing. The host rejects any disagreement with explicit
identifiers, filters, or operation semantics. After planning, every model-visible TeamViewer tool name is published by the pinned
official TeamViewer MCP server. The model never sees the complete MCP tool set: it receives one
zero-argument host-bound wrapper for an ordinary read or exactly one route-selected write tool for
a state-changing request. The six application-level write adapters have strict schemas and call only their
identically named official MCP operations. Policy
assignment is temporarily disabled because the current upstream `assignments` schema is not
sufficiently typed.

## Architecture and approval boundary

```text
Operator prompt
    |
    v
Qwen operation planner (non-executing exact operation confirmation)
    |
    v
Deterministic host validation
    |-- disagreement -------------> fail closed; zero TeamViewer operations
    |-- conversation -------------> Qwen with zero TeamViewer tools
    |-- unclear/unsupported ------> clarification; zero TeamViewer operations
    |-- one read -----------------> bind exact arguments in the host
    |                                -> Qwen calls one zero-argument bound wrapper
    |                                -> wrapper invokes exactly one official MCP read
    |                                -> host bounds the verified MCP result
    |                                -> Qwen renders the operator response
    `-- one write ----------------> expose exactly one typed write wrapper to Qwen
                                     -> validate exact proposed call
                                     -> display tool + arguments
                                         |-- APPROVE -> validate again -> MCP
                                         `-- anything else -> reject

Named-group read ----------------> host resolves legacy + managed namespaces through MCP
                                    -> reject no-match or ambiguity
                                    -> bound and format verified membership
                                    -> Qwen renders the operator response
```

This approval gate supplements TeamViewer token scopes; it does not replace them. Keep the
TeamViewer token narrowly scoped and review the allow-list with `--show-policy`.

The CLI makes the runtime boundary visible. Model-produced read responses start with
`Qwen response (TeamViewer data retrieved exclusively through the official MCP server)`. Ordinary
conversation states that no TeamViewer operation ran. Before a write approval, the CLI states that
Qwen prepared the host-bound request and that execution uses the official MCP server exclusively.

### MCP-only TeamViewer boundary

Every account, device, group, monitoring, report, and session operation crosses the configured
official TeamViewer MCP transport. The Python host contains no TeamViewer Web API URL and no direct
HTTP client for TeamViewer. Typed write wrappers call `teamviewer.call_tool` with the same official
MCP tool name; typed read adapters and the named-group host workflow compose only read-only
`teamviewer.call_tool` calls. The named-group workflow is not exposed as an invented model tool.
Ordinary conversation can still initialize the MCP connection at application startup, but it
performs no TeamViewer data operation and exposes no tool to the model.

The `tv_list_devices` read adapter intentionally hides the upstream optional `full_list` field.
This prevents local models from adding an unrequested deleted-device filter while preserving the
official MCP tool name and the supported group-ID and online/offline filters.

An unqualified request such as `List the online TeamViewer devices` uses a deterministic host
workflow over both `tv_list_devices` and `tv_list_company_managed_devices`. Results are presented
in separate legacy and company-managed sections. Say `legacy devices` or `company-managed devices`
when only one official inventory namespace is wanted.

All other routed reads also prevent model argument generation: Qwen sees one zero-argument wrapper
whose official MCP operation and arguments were already bound by the host. This prevents Qwen from
adding unsupported filters such as `name`, `shared`, or `shouldMatchFullName`, while still keeping
Qwen in the request and response path. Results are bounded before Qwen receives them. List output
displays at most 4 items per non-device collection and the serialized evidence is capped at 2,500
characters for the memory-constrained local CPU model. Device inventories use a compact name,
TeamViewer ID, and device-ID projection with an 8,000-character Qwen evidence budget. Qwen analyzes
the complete compact inventory and produces only a short count/filter summary; the host appends
every verified MCP device row verbatim. This avoids slow model regeneration and allows the current
inventory to be shown completely. The response reports if a larger future inventory exceeds the
Qwen analysis budget. Use a specific-ID read to inspect omitted details.

Connection-report listings use a smaller five-item sample so Qwen can include the report ID, user
name, and device name for every displayed entry without exhausting its response budget.

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
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

If PowerShell blocks the activation script, allow it only for the current shell and retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Activation puts the environment's executable directory on `PATH`, so every command below can use:

```text
teamviewer-hitl
```

`teamviewer-hitl.exe` is generated by the Python distribution `teamviewer-hitl-agent`; it is not a
TeamViewer binary or a package of its own. It calls `teamviewer_hitl.cli:main`. In each new
PowerShell window, activate `.venv` once before using the bare command.

### 3. Download and build TeamViewer's official MCP server

The TeamViewer MCP source is an external dependency and is intentionally not copied into this
repository.

```powershell
New-Item -ItemType Directory -Force external | Out-Null
git clone https://github.com/teamviewer/TV_Remote_MCP.git external\TV_Remote_MCP
git -C external\TV_Remote_MCP checkout 7039b9c2e9ea26c2bfb50cd7580c89f9fb3da517
cmd /c npm install --prefix external\TV_Remote_MCP
cmd /c npm run build --prefix external\TV_Remote_MCP
Test-Path external\TV_Remote_MCP\dist\index.js
```

The final command must return `True`.

The checkout pins the official server revision used to validate this application's tool names and
schemas. Review schema changes and rerun the complete test suite before moving that pin.

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
FOUNDRY_LOCAL_MODEL=qwen2.5-7b
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
foundry model info qwen2.5-7b
foundry model download qwen2.5-7b
foundry model load qwen2.5-7b
foundry server status
```

Newer Foundry Local documentation uses `service`. If `foundry --help` lists `service` instead of
`server`, use:

```powershell
foundry service start
foundry model info qwen2.5-7b
foundry model download qwen2.5-7b
foundry model load qwen2.5-7b
foundry service status
```

The first model download is several gigabytes and can take several minutes. The model alias lets
Foundry Local select a compatible CPU, GPU, or NPU variant for the machine.

Keep `FOUNDRY_LOCAL_MODEL=qwen2.5-7b` as an alias rather than pinning a full `-cpu`, `-gpu`, or
`-npu` variant. This lets Foundry Local select the fastest compatible execution provider. Check the
`id` returned by `/v1/models`: an ID ending in `generic-cpu` confirms CPU inference. Use
`foundry model list --variants` to inspect accelerated variants after Foundry has registered the
machine's execution providers.

The application tunes Qwen for this workload: deterministic write-tool preparation uses
`temperature=0` with a 128-token ceiling, rejected-call settlement uses one token, approved-call
continuation uses 160 tokens, and ordinary conversation uses `temperature=0.2` with a 384-token
ceiling. Read-only TeamViewer requests bypass LLM inference entirely while still using the
official MCP server. For several conversational or write requests, use the interactive
`teamviewer-hitl` session instead of starting multiple one-shot processes concurrently.

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
teamviewer-hitl --show-policy
```

Run the automated tests:

```powershell
python -m unittest discover -s tests -v
```

The tests do not call TeamViewer or Microsoft Foundry cloud services.

### 8. Run read-only live tests

Start with one TeamViewer operation per prompt. This keeps routing and argument validation
predictable when using the local `qwen2.5-7b` model.

Test account access:

```powershell
teamviewer-hitl "Show my TeamViewer account summary."
```

Test the combined online device list. This reads both the legacy Computers & Contacts inventory
and the company-managed inventory through official MCP tools, then displays separate sections:

```powershell
teamviewer-hitl "List the online TeamViewer devices."
```

Request only the legacy Computers & Contacts namespace:

```powershell
teamviewer-hitl "List the online legacy TeamViewer devices."
```

Request only the company-managed namespace:

```powershell
teamviewer-hitl "List the online company-managed TeamViewer devices."
teamviewer-hitl "List the online company-managed TeamViewer devices starting with p."
```

Test a group by exact name, replacing `<EXACT_GROUP_NAME>`. The resolver checks both legacy
Computers & Contacts groups and managed groups through MCP, and stops if the name is ambiguous:

```powershell
teamviewer-hitl "Show the devices in <EXACT_GROUP_NAME>."
```

Run an interactive session:

```powershell
teamviewer-hitl
```

Type `exit` or `quit` to stop the interactive session.

### 9. Test Human-in-the-Loop approval

TeamViewer service cases must be created in a legacy Computers & Contacts group. List those groups
through MCP first and copy the exact group ID:

```powershell
teamviewer-hitl "List all device groups."
```

Then use a test target that you are authorized to operate, replacing `<GROUP_ID>` with an ID from
that result:

```powershell
teamviewer-hitl "Create a TeamViewer support session with description HITL-Test in group ID <GROUP_ID>."
```

Before the MCP call executes, the application displays:

```text
--- HUMAN APPROVAL REQUIRED ---
Tool: tv_create_session
Arguments:
{
  "description": "HITL-Test",
  "groupid": "<GROUP_ID>"
}
Type APPROVE to execute this exact call. Any other response rejects it.
```

For a rejection-path test, type anything other than `APPROVE`. For an execution test, verify the
target and arguments carefully and then type exactly `APPROVE`.

Qwen analyzes and confirms the exact operation proven by deterministic host parsing. `clarify` is
offered only when host parsing finds an incomplete or ambiguous request, so a fully validated
operation cannot be downgraded or switched to a neighboring namespace by the model. Ordinary reads
then use one zero-argument wrapper
over the exact official MCP operation. Device inventories use the validated Qwen plan, call the
official MCP operation with host-bound arguments, let Qwen analyze the compact complete result,
and append all verified rows. For writes, the host pins the model to one exact official tool.
Named-group lookup remains a deterministic MCP-only composition after Qwen selects that workflow.
Hardware inventory groups only byte-for-byte duplicate MCP records and reports their quantity;
same-name components with different details remain separate. Qwen analyzes the totals and the host
appends the complete authoritative component list.
TeamViewer may display an Instant Support session ID without its API prefix. For get, update, and
close prompts, an explicitly labeled numeric session code is canonicalized to `s<digits>` and the
prefixed value is shown in the approval screen before any write can execute.
For a write, the host also binds the approved tool name and canonical arguments to the continuation;
any post-approval change is blocked before MCP execution.

Approval decisions are appended to:

```text
.audit\teamviewer-approvals.jsonl
```

The audit entry records the decision, not proof that the downstream TeamViewer operation
succeeded. The agent reports tool success only when the MCP call itself returns success.

## Available commands

```powershell
# Help
teamviewer-hitl --help

# Show the security policy without credentials
teamviewer-hitl --show-policy

# One-shot request
teamviewer-hitl "Show my TeamViewer account summary."

# Interactive mode
teamviewer-hitl

# Run the module without the generated console executable
python -m teamviewer_hitl.cli

# Run tests
python -m unittest discover -s tests -v
```

## Supported prompt examples

These examples are intentionally explicit. Submit one operation at a time.

```powershell
# No TeamViewer call
teamviewer-hitl "Hello"

# Read-only requests using official MCP tools only
teamviewer-hitl "Show my TeamViewer account summary."

# Combined inventory: legacy Computers & Contacts + company-managed devices
teamviewer-hitl "List the online TeamViewer devices."

# One inventory namespace only
teamviewer-hitl "List the online legacy TeamViewer devices."
teamviewer-hitl "List the online company-managed TeamViewer devices."

# Exact-name group lookup across legacy and managed group namespaces
teamviewer-hitl "Show the devices in <EXACT_GROUP_NAME>."

# Group inventories
teamviewer-hitl "List all legacy device groups."
teamviewer-hitl "List all managed device groups."

# Additional read-only examples
teamviewer-hitl "List all TeamViewer sessions."
teamviewer-hitl "List closed TeamViewer sessions."
teamviewer-hitl "Get TeamViewer session code s123."
# Legacy device IDs start with d
teamviewer-hitl "Get device ID d1234567890."
# Managed device IDs are UUIDs
teamviewer-hitl "Get device ID 550e8400-e29b-41d4-a716-446655440000."
# TeamViewer display spacing is accepted and normalized
teamviewer-hitl "Show hardware for monitored device with TeamViewer ID 987 654 321."
teamviewer-hitl "List all connection reports."
teamviewer-hitl "Get connection report ID 550e8400-e29b-41d4-a716-446655440000."

# Writes: each stops for exact APPROVE input
teamviewer-hitl "Create a TeamViewer support session with description HITL-Test in group ID <GROUP_ID>."
teamviewer-hitl "Update TeamViewer session code s123 with description Customer confirmed."
```

For a targeted read or write, label the identifier explicitly as `session code`, `device ID`,
`connection report ID`, `group ID`, or `TeamViewer ID`. The value must match exactly; a device or
session name is never silently treated as an ID. If you know only a name, run a read/list command
first, then submit a second command containing the returned identifier. Relative dates such as
`yesterday` are not inferred; supported date-based routes require an explicit ISO 8601 range.

Session creation requires exactly one explicit legacy Computers & Contacts selector: `in group ID
<GROUP_ID>`. Use the ID returned by `List all device groups.`; a managed-device group is a separate
TeamViewer namespace and cannot be used for a service case. Group-name creation is intentionally
not exposed because a typo can create an unintended legacy group. A missing, malformed, or double
group selector is rejected before the model, approval prompt, or MCP write runs.

Session updates expose only `description`. Session `tag`, `notes`, `supporter_name`, and
end-customer fields are not sent because they are advertised by the pinned MCP schema but are not
accepted by the current TeamViewer session API contract. Monitoring activation accepts only one
numeric TeamViewer ID; policy assignment remains disabled separately.

### MCP contract compatibility and complete-result policy

The pinned official MCP server and the current TeamViewer Web API do not agree on every parameter.
This application corrects only the mismatches that can be handled while still sending every
TeamViewer request through MCP:

- Monitoring hardware, system, and software prompts require a numeric `TeamViewer ID`; the adapter
  maps it to the official MCP tool's `device_id` field.
- Connection-report and device-report lists follow the API's UUID `offset_id` cursor through a
  narrow Agent Framework per-tool argument allow-list.
- Managed-device lists and monitoring alarms follow their MCP pagination tokens automatically.
- Online/offline and open/closed filters are host-bound to the exact filter stated in the prompt.

The application never silently returns a known partial result. If a managed-group, event-log, or
session-list response announces another page that the pinned MCP handler cannot request with the
current API cursor, the read stops with an explicit compatibility error. Upgrade the pinned MCP
revision only after reviewing its schemas and rerunning the full tests.

The following operations are deliberately unavailable:

- Monitoring-policy and patch-policy assignment, until the official MCP assignment payload is
  fully typed.
- Session metadata updates other than `description`, and session-list filters other than one
  `open` or `closed` state.
- Filtered monitoring-alarm and report-list queries; request the complete list, then make a second
  targeted request using an explicit identifier.
- Any write not listed above, including deleting devices, groups, reports, users, or policies.
- Multiple state changes in one prompt.

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

### Session creation returns `Missing parameter groupid or groupname`

The TeamViewer API requires every new service case to identify a legacy Computers & Contacts
group. Current builds reject an incomplete create request before approval. Obtain the group ID and
include it explicitly:

```powershell
teamviewer-hitl "List all device groups."
teamviewer-hitl "Create a TeamViewer support session with description HITL-Test in group ID <GROUP_ID>."
```

The pinned official MCP schema does not advertise the required `groupid`, but its call handler
forwards supplied session fields to TeamViewer. This application therefore uses Agent Framework's
narrow per-tool extra-argument allow-list and a stricter local wrapper while keeping the write
exclusively on the official MCP transport.

### The local model describes a tool but does not call it

Read operations pass through Qwen planning, but Qwen cannot unilaterally authorize parameters: the
host verifies the selected operation and every explicit filter or identifier. Ordinary reads then
expose one zero-argument wrapper bound to the validated official MCP operation. Device inventories
are compacted for Qwen analysis and rendered completely from verified MCP evidence. For writes,
the host requires the exact routed function name and verifies that its invocation middleware ran.
Keep prompts explicit and request one operation at a time.

Qwen may duplicate a valid structured function call inside a textual
`<tool_call>...</tool_call>` envelope. Phi variants may use
`<|tool_call|>...<|/tool_call|>`. The host removes both provider-specific envelopes from operator
output; neither textual form counts as execution. Only invocation middleware confirms execution.

### Event-log pagination

The pinned official `tv_get_event_logs` MCP handler advertises `continuation_token` but cannot
forward the current event-log pagination token correctly. When TeamViewer reports another page,
the application recursively divides the requested UTC range and calls the same official MCP tool
for each subrange. Incomplete parent pages are discarded, exact cross-boundary overlaps are removed,
and results are returned only after every subrange is complete. The composition is limited to 127
MCP calls and a one-millisecond minimum range; exceeding either guard fails closed without returning
partial logs. The Python host never calls the TeamViewer Web API directly.

### A named group returns unrelated devices

TeamViewer has two separate inventory models:

- `tv_list_device_groups` and `tv_list_devices` read legacy Computers & Contacts groups.
- The deterministic host workflow searches both namespaces using the official MCP server, matches
  the name exactly, and rejects ambiguity. It is not a model-visible tool. For a managed group it
  verifies membership by composing `tv_list_managed_groups`,
  `tv_list_company_managed_devices`, and `tv_get_managed_device_groups`. For a legacy group it
  composes `tv_list_device_groups` and `tv_list_devices`.

The resolver follows managed pagination and returns only membership supplied by TeamViewer MCP.
If the same exact name exists in both namespaces, rename one group or query it by an explicit ID;
the application will not guess.

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
teamviewer-hitl
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

The pinned `TV_Remote_MCP` revision is verified by this project over local stdio. Its custom
`--http` branch does not currently return the standard MCP `CallToolResult` envelope, so do not use
that branch directly as `TEAMVIEWER_MCP_URL`; remote mode requires a conformant Streamable HTTP MCP
deployment or adapter.

The named-group host workflow works with both local stdio and remote HTTP MCP transports. It never
calls TeamViewer Web API directly from Python; every TeamViewer request crosses the configured MCP
transport.

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
- [Microsoft Agent Framework tool availability controls](https://learn.microsoft.com/en-us/agent-framework/agents/tools/controlling-tool-availability)
- [Microsoft Agent Framework Human-in-the-Loop workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop)
- [Microsoft Foundry Local CLI](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-cli)
- [TeamViewer MCP interface](https://www.teamviewer.com/en/global/support/knowledge-base/teamviewer-remote/teamviewer-ai/teamviewer-mcp-interface/)
- [TeamViewer official self-hosted MCP server](https://github.com/teamviewer/TV_Remote_MCP)
- [TeamViewer Web API documentation](https://webapi.teamviewer.com/api/v1/docs/index)
