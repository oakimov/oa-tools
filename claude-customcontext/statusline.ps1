#!/usr/bin/env pwsh
$inputJson = [Console]::In.ReadToEnd()
$inputJson | Out-File "$HOME/.claude/status.json"
try {
    $json = $inputJson | ConvertFrom-Json
} catch {
    Write-Output "[unknown] [ERROR]"
    exit
}

$modelId = if ($json.model.id) { $json.model.id } else { "" }
$model   = if ($json.model.display_name) { $json.model.display_name } else { "unknown" }

$knownSize = 200000
$configPath = Join-Path $HOME ".claude" "model-contexts.json"
if (Test-Path $configPath) {
    $modelMap = Get-Content $configPath | ConvertFrom-Json -AsHashtable
    if ($modelMap.ContainsKey($modelId)) {
        $knownSize = $modelMap[$modelId]
    } else {
        $keys = $modelMap.Keys | Where-Object { $_ -ne '*' } | Sort-Object -Property Length -Descending
        foreach ($key in $keys) {
            if ($modelId -like "*$key*") { $knownSize = $modelMap[$key]; break }
        }
    }
    if ($knownSize -eq 200000 -and $modelMap.ContainsKey('*')) {
        $knownSize = $modelMap['*']
    }
}

$nativeSize = [long]($json.context_window.context_window_size)
$usedTokens = [long]($json.context_window.current_usage.input_tokens) + [long]($json.context_window.current_usage.cache_creation_input_tokens) + [long]($json.context_window.current_usage.cache_read_input_tokens)
$usedPct    = [double]($json.context_window.used_percentage)

if ($nativeSize -gt 0 -and $nativeSize -eq $knownSize) {
    $pct = [math]::Min([math]::Floor($usedPct), 100)
} elseif ($usedTokens -gt 0) {
    $pct = [math]::Min([math]::Floor([double]$usedTokens * 100.0 / $knownSize), 100)
} else {
    $pct = [math]::Min([math]::Floor($usedPct), 100)
}

$barWidth = 10
$filled   = [math]::Min([math]::Max([math]::Floor($pct * $barWidth / 100), 0), $barWidth)
$empty    = $barWidth - $filled
$bar      = ("#" * $filled) + ("-" * $empty)

Write-Output "[$model] $bar $pct%"
