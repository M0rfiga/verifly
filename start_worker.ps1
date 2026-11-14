param(
    [string]$CredentialsPath = (Join-Path $PSScriptRoot 'verifly-56717-firebase-adminsdk-fbsvc-3f1251030a.json'),
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$workerPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $workerPython)) {
    throw 'Crie a .venv e instale requirements-local.txt conforme o README.md.'
}

# A credencial fica somente no ambiente deste processo e do worker filho.
$env:GOOGLE_APPLICATION_CREDENTIALS = (Resolve-Path -LiteralPath $CredentialsPath).Path
if ($env:FIREBASE_SERVICE_ACCOUNT_JSON) {
    throw 'FIREBASE_SERVICE_ACCOUNT_JSON tem precedencia. Remova essa variavel deste terminal para usar a chave local.'
}
$env:VERIFLY_HEADLESS = if ($Headless) { '1' } else { '0' }
Push-Location -LiteralPath $PSScriptRoot
try {
    & $workerPython -m python_modules.local_worker
    $workerExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $workerExitCode
