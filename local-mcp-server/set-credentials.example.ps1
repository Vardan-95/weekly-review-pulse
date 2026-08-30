# Copy this file to set-credentials.local.ps1 (already gitignored) and fill
# in your real values. Never edit THIS file (the .example one) with real
# values — it's the template that stays in the repo.

$env:GOOGLE_OAUTH_CLIENT_ID = "YOUR_CLIENT_ID.apps.googleusercontent.com"
$env:GOOGLE_OAUTH_CLIENT_SECRET = "YOUR_CLIENT_SECRET"

$env:USER_GOOGLE_EMAIL = "you@example.com"

# Needed for Phase 3's real LLM summarization (GroqLLMClient, the
# orchestrator's default - free-tier friendly) - get a key from
# https://console.groq.com/keys.
$env:GROQ_API_KEY = "gsk_..."

# (Or, to use Anthropic instead - paid, not the default - set this instead
# and pass clients=PipelineClients(llm_client=p.AnthropicLLMClient())
# to run_pipeline():)
# $env:ANTHROPIC_API_KEY = "sk-ant-..."
