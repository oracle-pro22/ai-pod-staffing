param([string]$Source)
$app = New-Object -ComObject PowerPoint.Application
$deck = $null
try {
  $deck = $app.Presentations.Open($Source, $true, $false, $false)
  Write-Output "SLIDE SIZE $($deck.PageSetup.SlideWidth) x $($deck.PageSetup.SlideHeight)"
  foreach ($slide in $deck.Slides) {
    Write-Output "SLIDE $($slide.SlideIndex) layout=$($slide.CustomLayout.Name)"
    foreach ($shape in $slide.Shapes) {
      $txt = ''
      try { if ($shape.HasTextFrame -and $shape.TextFrame.HasText) { $txt = $shape.TextFrame.TextRange.Text -replace "`r", ' | ' } } catch {}
      $font = ''
      try { $font = "$($shape.TextFrame.TextRange.Font.Name) $($shape.TextFrame.TextRange.Font.Size)" } catch {}
      Write-Output ("ID={0} NAME={1} XYWH={2},{3},{4},{5} FONT={6} TEXT={7}" -f $shape.Id,$shape.Name,$shape.Left,$shape.Top,$shape.Width,$shape.Height,$font,$txt)
    }
  }
} finally {
  if ($deck) { $deck.Close() }
  $app.Quit()
}
