[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Quick,
    [switch]$SkipBackup,
    [switch]$Wait
)

$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))

function Read-SingleKeyChoice {
    param(
        [Parameter(Mandatory)] [string]$Prompt,
        [string]$Choices = 'YN'
    )
    Write-Host -NoNewline $Prompt
    while ($true) {
        $key = [Console]::ReadKey($true).KeyChar.ToString().ToUpperInvariant()
        if ($Choices.Contains($key)) {
            Write-Host $key
            return $key
        }
    }
}

function Invoke-Step {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [scriptblock]$Command,
        [switch]$Required
    )
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) {
            if ($Required) { throw "$Name failed with exit code $LASTEXITCODE." }
            $script:ResultCode = 1
        }
    }
    catch [System.Management.Automation.PipelineStoppedException] {
        throw
    }
    catch {
        if ($Required) { throw }
        Write-Host "$Name failed: $($_.Exception.Message)" -ForegroundColor Red
        $script:ResultCode = 1
    }
}

function Confirm-Cancel {
    $answer = Read-SingleKeyChoice -Prompt "`nStop Collect New? Press Y for Yes or N for No: "
    return $answer -eq 'Y'
}

function Start-PostProcessing {
    param(
        [Parameter(Mandatory)] [bool]$IdentityChanged,
        [Parameter(Mandatory)] [bool]$WaitForCompletion
    )
    $workerArgs = @('tools\identity_postprocess.py')
    if ($IdentityChanged) { $workerArgs += '--identity-changed' }

    if ($WaitForCompletion) {
        Write-Host 'Waiting for automatic post-processing because --wait was supplied.'
        & py -u @workerArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Post-processing failed with exit code $LASTEXITCODE."
        }
        return
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $launcher) { $launcher = Get-Command py -ErrorAction Stop }
    $arguments = @('-u') + $workerArgs
    $process = Start-Process -FilePath $launcher.Source -ArgumentList $arguments -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
    Write-Host "Automatic post-processing started in the background as PID $($process.Id)."
    Write-Host 'Progress is written to reports\identity-postprocess-latest.log and data\post-processing-status.json.'
}

$script:ResultCode = 0
$forceFlag = if ($Force) { '--force' } else { $null }
$quickFlag = if ($Quick) { '--quick' } else { $null }
$identityChanged = $false
$backgroundStarted = $false

try {
    & py tools\identity_postprocess.py --check | Out-Null
    if ($LASTEXITCODE -eq 20) {
        throw 'Identity post-processing is already running. Wait for it to finish before starting Collect New again.'
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to check identity post-processing status (exit code $LASTEXITCODE)."
    }

    if ($SkipBackup) {
        Write-Host 'Backup skipped by --skip.' -ForegroundColor Yellow
    }
    else {
        $backup = Read-SingleKeyChoice -Prompt 'Create a database backup before continuing? Press Y for Yes or N for No: '
        if ($backup -eq 'Y') {
            Write-Host 'Creating pre-collection database backup...'
            Invoke-Step -Name 'Database backup' -Required -Command { & py tools\backup_database.py --keep 1 --reason 'collect-new' }
        }
        else {
            Write-Host 'Continuing without creating a database backup.'
        }
    }

    Invoke-Step -Name 'SQLite concurrency configuration' -Required -Command { & py tools\sqlite_concurrency.py }
    Invoke-Step -Name 'Workflow snapshot' -Required -Command { & py tools\workflow_cache.py snapshot collect-new-db database\bc_justice.db }
    Invoke-Step -Name 'Identity-input snapshot' -Required -Command { & py tools\identity_change_detector.py snapshot --name collect-new }

    $catalogueArgs = @('tools\sync_bc_catalogue.py', '--download', '--incremental', '--import', '--verbose')
    if ($forceFlag) { $catalogueArgs += $forceFlag }
    if ($quickFlag) { $catalogueArgs += $quickFlag }
    Invoke-Step -Name 'BC Data Catalogue collection' -Command { & py -u @catalogueArgs }
    Invoke-Step -Name 'Justice source collection' -Command { & py -u tools\collect_justice_sources.py all }
    Invoke-Step -Name 'CSO charge inbox/cache and appearance links' -Command { & py -u tools\cso_charge_pipeline.py all --cap 250 }
    Invoke-Step -Name 'Corrections oversight collection' -Command { & py -u tools\collect_corrections_oversight.py }
    Invoke-Step -Name 'Police data collection' -Command { & py -u tools\collect_police_data.py }

    $statcanArgs = @('tools\collect_statcan_crime.py')
    if ($forceFlag) { $statcanArgs += $forceFlag }
    if ($quickFlag) { $statcanArgs += $quickFlag }
    Invoke-Step -Name 'Statistics Canada collection' -Command { & py -u @statcanArgs }

    $runPostProcessing = $true
    & py tools\workflow_cache.py changed collect-new-db database\bc_justice.db
    if ($LASTEXITCODE -eq 10) { $runPostProcessing = $false }
    elseif ($LASTEXITCODE -ne 0) { throw "Database change detection failed with exit code $LASTEXITCODE." }

    & py tools\identity_change_detector.py changed --name collect-new
    if ($LASTEXITCODE -eq 0) { $identityChanged = $true }
    elseif ($LASTEXITCODE -eq 10) { $identityChanged = $false }
    else { throw "Identity change detection failed with exit code $LASTEXITCODE." }

    if ($Force) {
        $runPostProcessing = $true
        $identityChanged = $true
    }

    $requiredExports = @(
        'data\charts-summary.json',
        'data\search-cases.json',
        'data\search-people.json',
        'data\collection-summary.json'
    )
    $missingExports = @($requiredExports | Where-Object { -not (Test-Path $_) })
    $missingIdentityExports = @(
        'data\search-people.json',
        'data\person-profiles.json',
        'data\repeat-offenders.json'
    ) | Where-Object { -not (Test-Path $_) }

    $chartsNeedRefresh = $false
    if (Test-Path 'data\charts-summary.json') {
        try {
            $chartSnapshot = Get-Content 'data\charts-summary.json' -Raw | ConvertFrom-Json
            $chartCount = @($chartSnapshot.courtActivity).Count + @($chartSnapshot.verifiedOutcomes).Count + @($chartSnapshot.crimeSeverity).Count
            if ($chartCount -eq 0) { $chartsNeedRefresh = $true }
        }
        catch { $chartsNeedRefresh = $true }
    }
    else { $chartsNeedRefresh = $true }

    if ($missingExports.Count -gt 0 -or $chartsNeedRefresh) {
        $runPostProcessing = $true
        Write-Host 'Dashboard or chart snapshots are missing/empty; rebuilding exports even though the database may be unchanged.'
    }
    if (@($missingIdentityExports).Count -gt 0) {
        $identityChanged = $true
        $runPostProcessing = $true
        Write-Host 'Identity snapshots are missing; the person identity build is required.'
    }

    if (-not $runPostProcessing) {
        Write-Host 'No database or snapshot changes detected; identity and advanced post-processing are not required.'
    }
    else {
        Write-Host 'Publishing initial dashboard snapshots...'
        Invoke-Step -Name 'Initial dashboard export' -Command { & py tools\data_pipeline.py export }
    }

    if ($script:ResultCode -eq 0) {
        if ($runPostProcessing) {
            & py tools\collection_summary.py collected 0
            & py tools\collection_alerts.py collected
            Write-Host "`nCollection is complete." -ForegroundColor Green
            if ($identityChanged) {
                Write-Host 'Next: Build person identities...'
            }
            else {
                Write-Host 'Identity-related data did not change; person identity building is skipped.'
                Write-Host 'Next: Refresh non-identity advanced features and final exports...'
            }
            Start-PostProcessing -IdentityChanged $identityChanged -WaitForCompletion ([bool]$Wait)
            $backgroundStarted = -not $Wait
            if ($Wait) {
                Write-Host 'All processing is complete.' -ForegroundColor Green
            }
        }
        else {
            & py tools\collection_summary.py success 0
            & py tools\collection_alerts.py success
            Write-Host "`nCollection is complete. No post-processing was required." -ForegroundColor Green
        }
    }
    else {
        & py tools\collection_summary.py failed 1
        & py tools\collection_alerts.py failed
        Write-Host "`nCollection finished with errors. Open the dashboard collection summary."
    }
}
catch [System.Management.Automation.PipelineStoppedException] {
    if (Confirm-Cancel) {
        Write-Host 'Collection cancelled.'
        exit 130
    }
    Write-Host 'Cancellation declined. Run Collect New again to continue safely.'
    exit 1
}
catch {
    Write-Host "Collection stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

if ($backgroundStarted) {
    Write-Host 'Collect New can now close while post-processing continues automatically.'
}
Write-Host -NoNewline 'Press any key to close...'
[void][Console]::ReadKey($true)
Write-Host
exit $script:ResultCode
