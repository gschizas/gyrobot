# Runs the Alembic migrations of an instance as a database user that owns the tables (Windows twin of
# deploy/migrate.sh). Usage (from anywhere): deploy\windows\migrate.ps1
# Lists .env.d\*.env to pick the instance, then asks for the database user (default: postgres) and its
# password. The host, port and database come from the instance's env file; the password is passed
# through PGPASSWORD, so it needs no URL escaping, and it only lives in this process.
$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

$instances = @(Get-ChildItem '.env.d' -Filter '*.env' -File | ForEach-Object { $_.BaseName })
if ($instances.Count -eq 0) {
    throw 'No .env.d\*.env files found'
}
for ($i = 0; $i -lt $instances.Count; $i++) {
    Write-Host ("{0,3}) {1}" -f ($i + 1), $instances[$i])
}
$choice = 0
do {
    $answer = Read-Host "Instance [1-$($instances.Count)]"
} until ([int]::TryParse($answer, [ref]$choice) -and $choice -ge 1 -and $choice -le $instances.Count)
$envName = $instances[$choice - 1]

$dbUser = Read-Host 'Database user (must own the tables) [postgres]'
if (-not $dbUser) {
    $dbUser = 'postgres'
}
$securePassword = Read-Host "Password of $dbUser" -AsSecureString

try {
    $env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
    # Same connection as the instance, but as $dbUser and without a password.
    $env:MIGRATIONS_DATABASE_URL = (uv run python deploy\migration_url.py $envName $dbUser)
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not read the database URL'
    }

    Write-Host "Migrating $env:MIGRATIONS_DATABASE_URL"
    uv run alembic -x "env=$envName" upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw 'alembic upgrade failed'
    }
    uv run alembic -x "env=$envName" check
    if ($LASTEXITCODE -ne 0) {
        throw 'alembic check failed'
    }
}
finally {
    Remove-Item Env:PGPASSWORD, Env:MIGRATIONS_DATABASE_URL -ErrorAction SilentlyContinue
}
