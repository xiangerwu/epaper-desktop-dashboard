$ErrorActionPreference = "Stop"

$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) { throw "找不到 $envFile" }

$config = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([^#=]+?)\s*=\s*(.*?)\s*$') { $config[$matches[1]] = $matches[2] }
}

$hostName = $config.PI_SSH_HOST
$userName = if ($config.PI_SSH_USER) { $config.PI_SSH_USER } else { "pi" }
$source = Join-Path $HOME ".codex\auth.json"
$identity = Join-Path $HOME ".ssh\id_ed25519_for_pi"
if (-not $hostName) { throw ".env 缺 PI_SSH_HOST" }
if (-not (Test-Path $source)) { throw "找不到 $source，請先在 Windows 登入 Codex" }
if (-not (Test-Path $identity)) { throw "找不到 SSH 私鑰 $identity" }

$target = "$userName@$hostName"
ssh -i $identity $target 'mkdir -p ~/.codex && chmod 700 ~/.codex'
if ($LASTEXITCODE) { throw "SSH 連線或建立目錄失敗" }
scp -i $identity $source "${target}:~/.codex/auth.json.tmp"
if ($LASTEXITCODE) { throw "上傳 Codex 憑證失敗" }
ssh -i $identity $target 'chmod 600 ~/.codex/auth.json.tmp && mv ~/.codex/auth.json.tmp ~/.codex/auth.json'
if ($LASTEXITCODE) { throw "安裝 Codex 憑證失敗" }

Write-Host "Codex 憑證已更新到 $target"
