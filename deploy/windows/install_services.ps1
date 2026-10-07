#Requires -Version 5.1
<#
.SYNOPSIS
    Installs the bot (and optionally the web UI/API) as Windows services using WinSW.
.DESCRIPTION
    Run from an elevated PowerShell:  deploy\windows\install_services.ps1 -Instance myinstance [-Web]
    Services are named gyrobot-<Instance> and gyrobot-web-<Instance>. Their WinSW files are generated
    in <repo>\.winsw. Each service installs the instance's plugin libraries before it starts.
.PARAMETER Instance
    Environment name, i.e. .env.d\<Instance>.env
.PARAMETER Web
    Also install the web UI + REST API service.
.PARAMETER Credential
    Account to run the services as. Defaults to LocalSystem, which usually cannot see a per-user
    uv installation; prefer the account that owns the checkout.
.PARAMETER WinSwUrl
    WinSW executable to download if .winsw\WinSW.exe is missing. Needs v3 (for <prestart>).
.PARAMETER RenderOnly
    Only generate the files in .winsw; do not install or start anything.
.PARAMETER Uninstall
    Stop and remove the services and their generated files.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Instance,
    [switch]$Web,
    [pscredential]$Credential,
    [string]$WinSwUrl = 'https://github.com/winsw/winsw/releases/download/v3.0.0-alpha.11/WinSW-x64.exe',
    [switch]$RenderOnly,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$winsw = Join-Path $repo '.winsw'
$template = Get-Content (Join-Path $PSScriptRoot 'service.xml') -Raw
$services = @(@{ Id = "gyrobot-$Instance"; Name = 'Gyrobot chat bot'; Script = '__main__.py' })
if ($Web -or $Uninstall) {
    $services += @{ Id = "gyrobot-web-$Instance"; Name = 'Gyrobot web UI and REST API'; Script = 'run_webapp.py' }
}

if (-not $RenderOnly) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { throw 'Run this script from an elevated (administrator) PowerShell.' }
}

if ($Uninstall) {
    foreach ($svc in $services) {
        $exe = Join-Path $winsw "$($svc.Id).exe"
        if (Test-Path $exe) {
            & $exe stop 2>$null
            & $exe uninstall
            Remove-Item (Join-Path $winsw "$($svc.Id).*") -Force
        }
    }
    return
}

$uv = (Get-Command uv -ErrorAction Stop).Source
if (-not (Test-Path (Join-Path $repo ".env.d\$Instance.env"))) {
    Write-Warning ".env.d\$Instance.env does not exist yet."
}
New-Item -ItemType Directory -Force $winsw, (Join-Path $repo 'logs') | Out-Null

$template_exe = Join-Path $winsw 'WinSW.exe'
if (-not (Test-Path $template_exe)) {
    Write-Host "Downloading WinSW from $WinSwUrl"
    Invoke-WebRequest $WinSwUrl -OutFile $template_exe
}

function Format-Xml([string]$text) { [Security.SecurityElement]::Escape($text) }

foreach ($svc in $services) {
    $xml = $template.Replace('@ID@', $svc.Id).Replace('@NAME@', (Format-Xml "$($svc.Name) ($Instance)")).
        Replace('@SCRIPT@', $svc.Script).Replace('@INSTANCE@', (Format-Xml $Instance)).
        Replace('@UV@', (Format-Xml $uv)).Replace('@DIR@', (Format-Xml $repo))
    # WinSW pairs <name>.exe with <name>.xml
    $exe = Join-Path $winsw "$($svc.Id).exe"
    Copy-Item $template_exe $exe -Force
    Set-Content (Join-Path $winsw "$($svc.Id).xml") $xml -Encoding UTF8
    if ($RenderOnly) { continue }

    $arguments = @('install')
    if ($Credential) {
        $arguments += '--username', $Credential.UserName, '--password', $Credential.GetNetworkCredential().Password
    }
    & $exe @arguments
    & $exe start
    Write-Host "Installed and started $($svc.Id)"
}
