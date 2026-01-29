# Backfill Monitor - PowerShell version
# Monitors resolution checker progress, restarts if stuck

$progressFile = "D:\docker\polymarket-dashboard\data\backfill_progress.json"
$stallThreshold = 300  # 5 minutes
$lastChecked = 0
$lastChangeTime = Get-Date

Write-Host "[$(Get-Date)] Starting backfill monitor..."

while ($true) {
    try {
        if (Test-Path $progressFile) {
            $progress = Get-Content $progressFile | ConvertFrom-Json
            $checked = $progress.checked
            $total = $progress.total
            $pct = [math]::Round($progress.pct, 1)
            $resolved = $progress.resolved
            
            Write-Host "[$(Get-Date)] Progress: $checked/$total ($pct%) - $resolved resolved"
            
            # Check for stall
            if ($checked -gt $lastChecked) {
                $lastChecked = $checked
                $lastChangeTime = Get-Date
            } else {
                $stallTime = ((Get-Date) - $lastChangeTime).TotalSeconds
                if ($stallTime -gt $stallThreshold) {
                    Write-Host "[$(Get-Date)] STALLED! Restarting..."
                    wsl -d Ubuntu-24.04 -- docker restart polymarket-dashboard-resolution-1
                    $lastChangeTime = Get-Date
                }
            }
            
            # Check if complete
            if ($checked -ge $total -and $total -gt 0) {
                Write-Host "[$(Get-Date)] BACKFILL COMPLETE!"
                break
            }
        } else {
            Write-Host "[$(Get-Date)] Waiting for progress file..."
        }
    } catch {
        Write-Host "[$(Get-Date)] Error: $_"
    }
    
    Start-Sleep -Seconds 30
}
