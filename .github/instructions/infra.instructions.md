---
applyTo: "infra/**"
description: Azure Bicep/azd infra stack rules for provisioning the Azure OpenAI resource
---

- `infra/main.bicep` is subscription-scoped: it creates a resource group, an Azure OpenAI (Cognitive
  Services) account with a `gpt-5.5` deployment, and a `Cognitive Services OpenAI User` role assignment.
  Keep new resources at the correct scope rather than nesting them under an assumed resource-group-scoped
  deployment.
- `infra/write_dot_env.sh` / `.ps1` are `azd` `postprovision` hooks that write Azure OpenAI env vars into
  `.env`, which both `invitations_manager.py` and `inbox_manager.py` read at runtime. If you rename or add
  an output in `main.bicep`, update both the `.sh` and `.ps1` variants together — they must stay in sync.
- Do not run `azd provision` or `azd down` yourself; both incur real Azure costs and provisioning changes
  should be reviewed with the user first (see README for the full auth flow).
