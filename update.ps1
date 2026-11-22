$ErrorActionPreference = 'Stop'

function Read-List([string]$url) {
    $response = Invoke-WebRequest -Uri $url -TimeoutSec 40
    $body = $response.Content
    if ($body -is [byte[]]) {
        $body = [Text.Encoding]::UTF8.GetString($body)
    }
    foreach ($line in ($body -split '\r?\n')) {
        $entry = $line.Trim().ToLowerInvariant()
        if ($entry -and -not $entry.StartsWith('#')) { $entry }
    }
}

$inside = @(Read-List 'https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-raw.lst')
$telegram = @(Read-List 'https://raw.githubusercontent.com/marcomc/glinet-vpn-subscription-lists/main/output/telegram/telegram-all-combined-v4.txt')
# A failed or partial download must not replace the last published file.
foreach ($entry in @('chatgpt.com', 'youtube.com', 'instagram.com', 'whatsapp.com')) {
    if ($entry -notin $inside) { throw "Missing domain in Russia inside: $entry" }
}
if ('149.154.160.0/20' -notin $telegram -or 'telegram.org' -notin $telegram) {
    throw 'Incomplete Telegram feed.'
}

$direct = @(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'direct.txt') | Where-Object { $_ -and -not $_.StartsWith('#') })
$rules = [Collections.Generic.SortedSet[string]]::new([StringComparer]::Ordinal)
$label = '[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
foreach ($entry in ($inside + $telegram)) {
    # The upstream .ua entry is a whole country zone, not a specific service.
    if ($entry -eq '.ua') { continue }
    if ($entry.Contains('/')) {
        $address = $null
        if ($entry -notmatch '^(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})$' -or
            -not [Net.IPAddress]::TryParse($Matches[1], [ref]$address) -or
            [int]$Matches[2] -notin (1..32)) { throw "Invalid IPv4 prefix: $entry" }
    } elseif ($entry -notmatch "^($label\.)+$label$" -or $entry.Length -gt 253) {
        throw "Invalid domain: $entry"
    }
    $skip = $false
    foreach ($domain in $direct) {
        if ($entry -eq $domain -or $entry.EndsWith(".$domain")) { $skip = $true; break }
    }
    if (-not $skip) { [void]$rules.Add($entry) }
}

$file = Join-Path $PSScriptRoot 'routes.txt'
$temp = Join-Path $PSScriptRoot ([IO.Path]::GetRandomFileName())
try {
    [IO.File]::WriteAllText($temp, ($rules -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
    [IO.File]::Move($temp, $file, $true)
} finally {
    if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
}
Write-Output ("Russia inside: {0}. Telegram: {1}. Published entries: {2}." -f $inside.Count, $telegram.Count, $rules.Count)
