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
$existing = [ordered]@{}
if (Test-Path $envPath) {
    foreach ($line in Get-Content $envPath) {
        if ($line -match '^([^#=\s]+)=(.*)$') {
            $existing[$matches[1]] = $matches[2]
        }
    }
}

$googleApiKey = $existing['GOOGLE_API_KEY']
$geminiApiKey = $existing['GEMINI_API_KEY']
$useVertexAi = $existing['GOOGLE_GENAI_USE_VERTEXAI'] -ieq 'TRUE'
if (-not $useVertexAi -and [string]::IsNullOrWhiteSpace($googleApiKey) -and [string]::IsNullOrWhiteSpace($geminiApiKey)) {
    $googleApiKey = Read-Secret 'Google / Gemini API key'
}

$realtyApiKey = Read-Secret 'RealtyAPI key'
if ([string]::IsNullOrWhiteSpace($realtyApiKey)) {
    throw 'RealtyAPI key cannot be empty.'
}

$existing.Remove('GEMINI_SEARCH_MODEL')
$existing.Remove('GEMINI_MODELS')
$existing['GOOGLE_API_KEY'] = $googleApiKey
$existing['GEMINI_API_KEY'] = $geminiApiKey
$existing['GOOGLE_GENAI_USE_VERTEXAI'] = if ($useVertexAi) { 'TRUE' } else { 'FALSE' }
$existing['LISTING_PROVIDER'] = 'realtyapi'
$existing['REALTYAPI_API_KEY'] = $realtyApiKey

$envContent = (($existing.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`n") + "`n"

$envDir = (Resolve-Path (Split-Path $envPath -Parent)).Path
[System.IO.File]::WriteAllText($envDir + '\.env', $envContent, [System.Text.UTF8Encoding]::new($false))

Write-Host 'Saved credentials to .env (git-ignored).'
Write-Host 'LISTING_PROVIDER=realtyapi is now enabled.'
