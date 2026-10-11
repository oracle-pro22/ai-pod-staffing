param([string]$Source, [string]$Output)
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
$deck = $null
function ShapeById($slide, [int]$id) {
  foreach ($shape in $slide.Shapes) { if ($shape.Id -eq $id) { return $shape } }
  throw "Shape ID $id not found"
}
function SetPara($shape, [int]$number, [string]$value) {
  $shape.TextFrame.TextRange.Paragraphs($number).Text = $value
}
function SetFiveLines($shape, [string[]]$lines) {
  $shape.TextFrame.TextRange.Text = ($lines -join "`r")
  for ($i = 1; $i -le $lines.Count; $i++) {
    $paragraph = $shape.TextFrame.TextRange.Paragraphs($i)
    $paragraph.Font.Bold = $(if ($i -eq 1) { -1 } else { 0 })
    $paragraph.Font.Size = 10
  }
}
try {
  $deck = $app.Presentations.Open($Source, $false, $false, $false)
  $slide = $deck.Slides.Item(1)

  (ShapeById $slide 4).TextFrame.TextRange.Text = 'Shamish Chandra Maikoti'
  (ShapeById $slide 5).TextFrame.TextRange.Text = 'Associate Consultant'
  (ShapeById $slide 2).TextFrame.TextRange.Text = 'Associate Consultant working on AI Pod Staffing, a Next.js and Oracle application for staffing requests and AI-assisted POD recommendations.'

  $experience = ShapeById $slide 3
  SetPara $experience 1 'AI Pod Staffing connects staffing requests with skills, availability and capacity'
  SetPara $experience 2 'A Supervisor and two OCI Generative AI agents prepare POD options for Captain review'

  $technology = ShapeById $slide 8
  $technology.TextFrame.TextRange.Text = "Next.js, React, TypeScript`rPython`rOracle AI Database 26ai`rOCI Generative AI"
  for ($i = 1; $i -le $technology.TextFrame.TextRange.Paragraphs().Count; $i++) {
    $technology.TextFrame.TextRange.Paragraphs($i).ParagraphFormat.Bullet.Visible = -1
  }

  $project = ShapeById $slide 10
  SetFiveLines $project @(
    'AI Pod Staffing',
    '1. Captains submit requests with dates, effort, deliverables, required skills and team size',
    '2. Rules check role, skill evidence, availability, capacity and capability coverage',
    '3. The Supervisor delegates request evidence review to an Analyst and validated option selection to a Planner',
    '4. Captains compare alternatives, choose the exact POD and approve or reject it; Oracle records assignments'
  )

  $eligibility = ShapeById $slide 6
  SetFiveLines $eligibility @(
    'GPU Accelerated AI Camera Analytics on OCI',
    '1. Project Intern, 28 Jan–17 Jul 2026; contributed to an OCI GPU camera analytics proof of concept',
    '2. Used Python, PyTorch, Hugging Face, CUDA, RT-DETR and CLIP for detection and classification',
    '3. Used OCI Queue between CPU stream processing and GPU inference; supported role, zone, time and confidence rules',
    '4. Documented the architecture and co-authored the Oracle AI & Data Science blog (7 Jul 2026)'
  )
  $eligibility.ActionSettings(1).Hyperlink.Address = 'https://blogs.oracle.com/ai-and-datascience/gpu-accelerated-ai-camera-analytics-on-oci'

  $recommendations = ShapeById $slide 7
  $recommendations.TextFrame.TextRange.Text = ''

  $decision = ShapeById $slide 11
  $decision.TextFrame.TextRange.Text = ''
  $deck.Slides.Item(2).Delete()

  $targetDir = Split-Path -Parent $Output
  New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
  $deck.SaveAs($Output, 24)
  Write-Output "Saved $Output"
} finally {
  if ($deck) { $deck.Close() }
  $app.Quit()
}
