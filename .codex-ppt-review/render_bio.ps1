param([string]$Source, [string]$OutDir)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path
$app = New-Object -ComObject PowerPoint.Application
$deck = $null
try {
  $deck = $app.Presentations.Open($Source, $true, $false, $false)
  for ($i = 1; $i -le $deck.Slides.Count; $i++) {
    $deck.Slides.Item($i).Export((Join-Path $OutDir "slide$i.png"), 'PNG', 1600, 900)
  }
  Write-Output "Rendered $($deck.Slides.Count) slides to $OutDir"
} finally {
  if ($deck) { $deck.Close() }
  $app.Quit()
}
