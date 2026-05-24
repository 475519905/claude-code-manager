param(
  [int]$Port = 0,
  [string[]]$Queries = @(),
  [switch]$SkipRaw,
  [string]$Exe = "",
  [string]$WebDir = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
$RepoName = Split-Path $RepoRoot -Leaf
$Kind = if ($RepoName -match "claude") { "claude" } else { "codex" }
if ($Port -eq 0) { $Port = if ($Kind -eq "codex") { 8766 } else { 8765 } }
if (-not $Exe) { $Exe = Join-Path $ScriptDir "build\conv_manager_cpp.exe" }
if (-not $WebDir) { $WebDir = Join-Path $RepoRoot "web" }
if ($Queries.Count -eq 0) {
  $Queries = if ($Kind -eq "codex") { @("codex", "error", "git") } else { @("claude", "error", "git") }
}
$Queries += "nf_$([guid]::NewGuid().ToString('N'))"

function Wait-Server {
  param([string]$Base)
  for ($i = 0; $i -lt 80; $i++) {
    try {
      Invoke-RestMethod "$Base/api/settings" -TimeoutSec 2 | Out-Null
      return
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  throw "server did not become ready"
}

function Measure-Call {
  param([scriptblock]$Call)
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $value = & $Call
  $sw.Stop()
  [pscustomobject]@{ ms = $sw.ElapsedMilliseconds; value = $value }
}

$out = Join-Path $ScriptDir "benchmark.out.log"
$err = Join-Path $ScriptDir "benchmark.err.log"
Remove-Item -LiteralPath $out,$err -ErrorAction SilentlyContinue

$process = Start-Process -FilePath $Exe `
  -ArgumentList @("--no-open", "--port", [string]$Port, "--web", $WebDir) `
  -WorkingDirectory $RepoRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $out `
  -RedirectStandardError $err `
  -PassThru

try {
  $base = "http://127.0.0.1:$Port"
  Wait-Server $base

  $sessionsCall = Measure-Call { Invoke-RestMethod "$base/api/sessions" -TimeoutSec 300 }
  Start-Sleep -Milliseconds 500
  $stats = Invoke-RestMethod "$base/api/search-index-stats" -TimeoutSec 30

  $searches = @()
  foreach ($q in $Queries) {
    $encoded = [uri]::EscapeDataString($q)
    $indexed = Measure-Call { Invoke-RestMethod "$base/api/search?q=$encoded" -TimeoutSec 300 }
    $item = [ordered]@{
      query = $q
      indexedMs = $indexed.ms
      indexedSearched = $indexed.value.searched
      total = $indexed.value.total
      results = $indexed.value.results.Count
    }
    if (-not $SkipRaw) {
      $raw = Measure-Call { Invoke-RestMethod "$base/api/search?q=$encoded&raw=1" -TimeoutSec 300 }
      $item.rawMs = $raw.ms
      $item.rawResults = $raw.value.results.Count
      $item.sameResultCount = ($raw.value.results.Count -eq $indexed.value.results.Count)
    }
    $searches += [pscustomobject]$item
  }

  [pscustomobject]@{
    kind = $Kind
    port = $Port
    sessionsMs = $sessionsCall.ms
    sessions = $sessionsCall.value.sessions.Count
    projects = $sessionsCall.value.projects.Count
    indexStats = $stats
    searches = $searches
  } | ConvertTo-Json -Depth 8
} finally {
  if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
  if (Test-Path $err) {
    $stderr = Get-Content $err -Raw
    if ($null -ne $stderr -and $stderr.Trim()) { Write-Warning $stderr }
  }
}
