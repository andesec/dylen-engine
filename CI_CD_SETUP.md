## CI/CD, security, and deployment setup

This workflow expects GitHub and AWS to be configured with secure defaults before it can deploy the FastAPI Lambda. The sections below outline the required steps.

### GitHub configuration

- **Create the `production` environment** (Settings → Environments) and require reviewers/approvals. Add environment variables and secrets scoped to this environment:
  - `AWS_REGION` (env var): AWS region for the stack, e.g. `us-east-1`.
  - `SAM_STACK_NAME` (env var): CloudFormation/SAM stack name, e.g. `dgs-backend`.
  - `SAM_TEMPLATE` (env var, optional): Path to the SAM template if it differs from `template.yaml`.
  - `AWS_DEPLOY_ROLE_ARN` (secret): The IAM role ARN that GitHub will assume via OIDC.
  - `SAM_ARTIFACT_BUCKET` (secret): Private S3 bucket used by `sam deploy` for build artifacts.
  - `GITLEAKS_LICENSE` (secret, optional): Only if you use a licensed gitleaks build.
- **Protect the `main` branch** so merges require green checks from `validate` and `security`.
- **Repository secrets/variables (global scope)**: only add values that truly are not environment-specific. Prefer the environment-scoped values above.
- **Enable Dependabot/secret scanning** in repository security settings if available, complementing the workflow scans.

### AWS configuration

1. **Create/verify the GitHub OIDC provider** (IAM → Identity providers) pointing to `https://token.actions.githubusercontent.com` with audience `sts.amazonaws.com`.
2. **Create an IAM role for deployments** with:
   - **Trust policy** limiting access to this repository and branch/environment, e.g.:
     - `token.actions.githubusercontent.com:sub`: `repo:<OWNER>/<REPO>:ref:refs/heads/main`
     - `token.actions.githubusercontent.com:aud`: `sts.amazonaws.com`
   - **Permissions policy** with least privilege, covering:
     - `cloudformation:*` on the target stack.
     - `lambda:*`, `apigateway:*`/`lambda:CreateFunctionUrlConfig` (for Function URL), and `logs:*` on the stack resources.
     - `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on the artifact bucket.
     - `iam:PassRole` only for roles referenced by the SAM template.
3. **Provision a private S3 bucket** for SAM build artifacts (value used for `SAM_ARTIFACT_BUCKET`).
4. **Author SAM template** (e.g., `dgs-backend/template.yaml`) defining the FastAPI Lambda, Function URL, and required IAM roles. Prefer Function URL `AuthType: AWS_IAM` and configure CORS to only allow necessary origins/methods.
5. **Create or reuse CloudWatch log groups** if you want to pre-provision retention; otherwise allow SAM to create them.
6. **Optionally create a VPC** and subnets/security groups if the function needs VPC access; reference them in the template.

### How the workflow runs

- **validate job**: Installs dependencies (or falls back to FastAPI/Mangum/Uvicorn), runs ruff, black `--check`, mypy, and pytest across Python 3.11 and 3.12 with pip caching.
- **security job**: Runs `pip-audit` against available requirements (or the current environment) and executes a `gitleaks` secret scan.
- **deploy job**: On pushes to `main`, assumes `AWS_DEPLOY_ROLE_ARN` via OIDC, validates/builds the SAM template, and runs `sam deploy` to the `SAM_STACK_NAME` stack using the `SAM_ARTIFACT_BUCKET` bucket. The job is bound to the `production` environment to honor approvals.

### Local expectations

Run `make format lint typecheck test` (or the equivalent `black`, `ruff`, `mypy`, and `pytest` commands) before opening PRs so CI mirrors local results.
