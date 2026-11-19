# DarGlobal x Wasalt AI Property Concierge

(Skeleton - final README written later. See SPEC.md.)

## Run locally
    docker build -t concierge . && docker run --rm -p 7860:7860 --env-file .env concierge

## Deploy
- Hugging Face Docker Space: `pwsh deploy/hf/deploy.ps1 -Space <user>/<space>` (see header of that script for secrets setup)
- Fallback: Render using `deploy/render.yaml`
- Pre-upload secret scan: `pwsh deploy/check_secrets.ps1`
