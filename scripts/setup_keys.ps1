$ErrorActionPreference = 'Stop'

function Read-Secret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

$envPath = Join-Path $PSScriptRoot '..\.env'
$existing = @{}
if (Test-Path $envPath) {
    foreach ($line in Get-Content $envPath) {
        if ($line -match '^([^#=\s]+)=(.*)$') {
            $existing[$matches[1]] = $matches[2]
        }
    }
}

$googleApiKey = $existing['GOOGLE_API_KEY']
$geminiApiKey = $existing['GEMINI_API_KEY']
if ([string]::IsNullOrWhiteSpace($googleApiKey) -and [string]::IsNullOrWhiteSpace($geminiApiKey)) {
    $googleApiKey = Read-Secret 'Google / Gemini API key'
}

$realtyApiKey = Read-Secret 'RealtyAPI key'
if ([string]::IsNullOrWhiteSpace($realtyApiKey)) {
    throw 'RealtyAPI key cannot be empty.'
}

$geminiModels = $existing['GEMINI_MODELS']
if ([string]::IsNullOrWhiteSpace($geminiModels)) {
    $geminiModels = 'gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash,gemini-3.5-flash,gemini-2.5-flash'
}
$geminiSearchModel = $existing['GEMINI_SEARCH_MODEL']
if ([string]::IsNullOrWhiteSpace($geminiSearchModel)) {
    $geminiSearchModel = 'gemini-3.7-flash'
}

$envContent = @"
GOOGLE_API_KEY=$googleApiKey
GEMINI_API_KEY=$geminiApiKey
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GEMINI_SEARCH_MODEL=$geminiSearchModel
GEMINI_MODELS=$geminiModels
LISTING_PROVIDER=realtyapi
REALTYAPI_API_KEY=$realtyApiKey
"@

$envDir = (Resolve-Path (Split-Path $envPath -Parent)).Path
[System.IO.File]::WriteAllText($envDir + '\.env', $envContent, [System.Text.UTF8Encoding]::new($false))

Write-Host 'Saved credentials to .env (git-ignored).'
Write-Host 'LISTING_PROVIDER=realtyapi is now enabled.'
Write-Host "Gemini search/intent model: $geminiSearchModel"
Write-Host "Gemini fallback order: $geminiModels"
