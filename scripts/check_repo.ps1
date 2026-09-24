$ErrorActionPreference = 'Stop'

$requiredPaths = @(
    'README.md',
    'TEAM.md',
    'CONTRIBUTING.md',
    '使用指南.md',
    '题目分析报告.md',
    '术语表格.md',
    'docs',
    'team',
    'analysis',
    'questions',
    'src',
    'scripts',
    'results',
    'figures',
    'paper'
)

$missing = @()
foreach ($path in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        $missing += $path
    }
}

if ($missing.Count -gt 0) {
    Write-Error ('缺少仓库路径: ' + ($missing -join ', '))
    exit 1
}

if (-not (Test-Path -LiteralPath 'questions\Data')) {
    Write-Error '未发现 questions\Data；请确认原始数据已放入题目目录。'
    exit 1
}

Write-Output '仓库结构检查通过。'
Write-Output '提示：题目分析、模型合同、竞赛规则和正式结果仍需由队伍完成并核对。'
