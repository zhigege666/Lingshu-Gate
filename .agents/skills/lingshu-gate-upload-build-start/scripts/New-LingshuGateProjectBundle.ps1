#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'This script requires PowerShell 7 or later because it uses [IO.Path]::GetRelativePath to produce repeatable ZIP paths. Run it with pwsh.'
}

$ErrorActionPreference = 'Stop'
$maximumFileCount = 3000
$maximumZipBytes = 50MB
$maximumSourceBytes = 200MB
$excludedDirectories = @('.git', 'node_modules', '.venv', 'venv', 'dist', 'build', 'target', '__pycache__')
$excludedFileNames = @()
$excludedExtensions = @()
$forbiddenSecretFileNames = @(
    '.env', '.npmrc', '.pypirc', '.netrc', '_netrc', '.git-credentials',
    'id_rsa', 'id_ed25519', 'settings.xml', 'gradle.properties',
    'credentials', 'credentials.json', 'secrets.json', 'secrets.yaml', 'secrets.yml'
)
$forbiddenSecretExtensions = @('.pem', '.key', '.pfx', '.p12', '.jks', '.keystore', '.kdbx', '.der')
$forbiddenSecretDirectories = @('.ssh', '.gnupg', '.aws')
$entryMarkers = @('package.json', 'pyproject.toml', 'requirements.txt', 'Dockerfile')
$forbiddenContentPatterns = @(
    [PSCustomObject]@{
        Name = 'PEM private key content'
        Regex = [regex]::new('-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')
    },
    [PSCustomObject]@{
        Name = 'Bearer Token'
        Regex = [regex]::new('(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}')
    },
    [PSCustomObject]@{
        Name = 'AWS Access Key'
        Regex = [regex]::new('\bAKIA[0-9A-Z]{16}\b')
    },
    [PSCustomObject]@{
        Name = 'GitHub Token'
        Regex = [regex]::new('\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b')
    },
    [PSCustomObject]@{
        Name = 'API token with sk prefix'
        Regex = [regex]::new('\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b')
    }
)
$genericCredentialPattern = [regex]::new(
    '(?i)\b(?<name>api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|secret)\b["'']?\s*[:=]\s*["'']?(?<value>[A-Za-z0-9+/=_\-.]{12,})'
)
$placeholderPattern = [regex]::new(
    '(?i)(example|placeholder|change[-_]?me|dummy|sample|test[-_]?only|x{4,}|your[-_]?|replace[-_]?me|not[-_]?a[-_]?secret)'
)

$projectInputItem = Get-Item -LiteralPath $ProjectRoot -Force
if (-not $projectInputItem.PSIsContainer) {
    throw "ProjectRoot must be a directory: $($projectInputItem.FullName)"
}
if (($projectInputItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'ProjectRoot must not be a symbolic link or reparse point.'
}
$resolvedProjectRoot = (Resolve-Path -LiteralPath $projectInputItem.FullName).Path
$projectItem = Get-Item -LiteralPath $resolvedProjectRoot -Force
if (-not $projectItem.PSIsContainer) {
    throw "Resolved ProjectRoot must be a directory: $resolvedProjectRoot"
}
if (($projectItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'Resolved ProjectRoot must not be a symbolic link or reparse point.'
}
$linkedItem = Get-ChildItem -LiteralPath $resolvedProjectRoot -Recurse -Force |
    Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 } |
    Select-Object -First 1
if ($null -ne $linkedItem) {
    throw "The project contains a symbolic link or reparse point: $($linkedItem.FullName)"
}

$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
$outputFileName = [IO.Path]::GetFileName($outputFullPath)
if ([string]::IsNullOrWhiteSpace($outputFileName) -or
    -not $outputFileName.EndsWith('.zip', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputPath must name a .zip file.'
}
$outputDirectory = [IO.Path]::GetDirectoryName($outputFullPath)
if ([string]::IsNullOrWhiteSpace($outputDirectory)) {
    throw 'OutputPath must include a valid directory.'
}
$projectPrefix = $resolvedProjectRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if ($outputFullPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputPath must be outside ProjectRoot so an existing ZIP cannot be packaged recursively.'
}

function Get-ForbiddenSecretReason {
    param([string]$RelativePath)

    $normalizedPath = $RelativePath.Replace('\', '/').ToLowerInvariant()
    $segments = $normalizedPath -split '/'
    $name = $segments[-1]
    if ($name -like '.env*') {
        return 'environment file'
    }
    if ($forbiddenSecretFileNames -contains $name) {
        return "sensitive filename $name"
    }
    if ($forbiddenSecretExtensions -contains [IO.Path]::GetExtension($name).ToLowerInvariant()) {
        return "sensitive certificate or key extension $([IO.Path]::GetExtension($name))"
    }
    foreach ($segment in $segments) {
        if ($forbiddenSecretDirectories -contains $segment) {
            return "sensitive credential directory $segment"
        }
    }
    if ($normalizedPath.EndsWith('/.docker/config.json') -or $normalizedPath -eq '.docker/config.json') {
        return 'Docker authentication file'
    }
    return $null
}

function Test-ExcludedRelativePath {
    param([string]$RelativePath)

    $segments = $RelativePath -split '[\\/]'
    foreach ($segment in $segments) {
        if ($excludedDirectories -contains $segment) {
            return $true
        }
    }
    $name = $segments[-1]
    if ($excludedFileNames -contains $name) {
        return $true
    }
    return $excludedExtensions -contains [IO.Path]::GetExtension($name).ToLowerInvariant()
}

function Get-SafeArchivePath {
    param([string]$RelativePath)

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        throw 'Packaging refused: found an empty relative path.'
    }
    foreach ($character in $RelativePath.ToCharArray()) {
        if ([char]::IsControl($character)) {
            throw 'Packaging refused: a path contains a control character that cannot be reviewed safely.'
        }
    }
    if ([IO.Path]::DirectorySeparatorChar -ne [char]'\' -and $RelativePath.Contains('\')) {
        throw "Packaging refused: a path contains a backslash that is ambiguous in ZIP archives: $RelativePath"
    }

    $archivePath = $RelativePath.Replace([IO.Path]::DirectorySeparatorChar, [char]'/')
    $segments = $archivePath -split '/'
    if ($archivePath.StartsWith('/') -or $segments -contains '' -or
        $segments -contains '.' -or $segments -contains '..') {
        throw "Packaging refused: found an unsafe archive path: $RelativePath"
    }
    return $archivePath
}

function Find-SecretContentReason {
    param(
        [Parameter(Mandatory = $true)]
        [IO.Stream]$Stream
    )

    $buffer = [byte[]]::new(64KB)
    $tail = ''
    while (($read = $Stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
        # Tokens generally use ASCII; UTF-8 replacement characters do not hide these high-confidence patterns.
        $text = $tail + [Text.Encoding]::UTF8.GetString($buffer, 0, $read)
        foreach ($pattern in $forbiddenContentPatterns) {
            if ($pattern.Regex.IsMatch($text)) {
                $Stream.Position = 0
                return $pattern.Name
            }
        }
        foreach ($match in $genericCredentialPattern.Matches($text)) {
            $value = $match.Groups['value'].Value
            if (-not $placeholderPattern.IsMatch($value)) {
                $Stream.Position = 0
                return "possible plaintext credential field $($match.Groups['name'].Value)"
            }
        }
        $tail = if ($text.Length -gt 512) { $text.Substring($text.Length - 512) } else { $text }
    }
    $Stream.Position = 0
    return $null
}

function Get-StreamSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [IO.Stream]$Stream
    )

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha256.ComputeHash($Stream)
    }
    finally {
        $sha256.Dispose()
        $Stream.Position = 0
    }
    return ([BitConverter]::ToString($hashBytes)).Replace('-', '').ToLowerInvariant()
}

$allProjectFiles = @(Get-ChildItem -LiteralPath $resolvedProjectRoot -File -Recurse -Force)
foreach ($projectFile in $allProjectFiles) {
    if (($projectFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "The project contains a symbolic link or reparse point: $($projectFile.FullName)"
    }
    $relativePath = [IO.Path]::GetRelativePath($resolvedProjectRoot, $projectFile.FullName)
    $archivePath = Get-SafeArchivePath -RelativePath $relativePath
    $secretReason = Get-ForbiddenSecretReason -RelativePath $archivePath
    if ($null -ne $secretReason) {
        throw "Packaging refused: found $secretReason at $archivePath. Move it outside the project root or use a credential-free delivery directory."
    }
}

$fileByArchivePath = [System.Collections.Generic.Dictionary[string, System.IO.FileInfo]]::new(
    [StringComparer]::Ordinal
)
foreach ($projectFile in $allProjectFiles) {
    $relativePath = [IO.Path]::GetRelativePath($resolvedProjectRoot, $projectFile.FullName)
    $archivePath = Get-SafeArchivePath -RelativePath $relativePath
    if (-not (Test-ExcludedRelativePath -RelativePath $archivePath) -and
        $projectFile.FullName -ne $outputFullPath) {
        if (-not $fileByArchivePath.TryAdd($archivePath, $projectFile)) {
            throw "Packaging refused: multiple files map to the same archive path: $archivePath"
        }
    }
}
$archivePaths = [string[]]$fileByArchivePath.Keys
[Array]::Sort($archivePaths, [StringComparer]::Ordinal)
$files = @(
    foreach ($archivePath in $archivePaths) {
        [PSCustomObject]@{
            File = $fileByArchivePath[$archivePath]
            RelativePath = $archivePath
        }
    }
)

if ($files.Count -eq 0) {
    throw 'The project has no files eligible for packaging.'
}
if ($files.Count -gt $maximumFileCount) {
    throw "File count $($files.Count) exceeds the Lingshu Gate limit of $maximumFileCount."
}

$sourceBytes = ($files | ForEach-Object { [long]$_.File.Length } | Measure-Object -Sum).Sum

if ([long]$sourceBytes -gt $maximumSourceBytes) {
    throw "Total source size $sourceBytes exceeds the Lingshu Gate extraction limit of $maximumSourceBytes."
}

Add-Type -AssemblyName System.IO.Compression
if (Test-Path -LiteralPath $outputFullPath) {
    throw "OutputPath already exists; refusing to overwrite it: $outputFullPath"
}

$systemTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$snapshotRoot = [IO.Path]::Combine(
    $systemTempRoot,
    'lingshu-gate-bundle-' + [Guid]::NewGuid().ToString('N')
)
$snapshotPrefix = $snapshotRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$outputCreatedByThisRun = $false
$bundleCompleted = $false
$snapshotRecords = @()
$snapshotSourceBytes = [long]0

try {
    [IO.Directory]::CreateDirectory($snapshotRoot) | Out-Null

    # Scan delivery content and copy it to a system-temporary snapshot before creating the output directory and ZIP. Human review follows the emitted manifest.
    foreach ($item in $files) {
        $currentItem = Get-Item -LiteralPath $item.File.FullName -Force
        $currentFullPath = [IO.Path]::GetFullPath($currentItem.FullName)
        if (-not $currentFullPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "File escaped ProjectRoot before packaging: $($item.RelativePath)"
        }
        if (($currentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "File became a symbolic link or reparse point before packaging: $($item.RelativePath)"
        }

        $snapshotPath = [IO.Path]::GetFullPath(
            [IO.Path]::Combine($snapshotRoot, $item.RelativePath.Replace('/', [IO.Path]::DirectorySeparatorChar))
        )
        if (-not $snapshotPath.StartsWith($snapshotPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Snapshot path escaped its root: $($item.RelativePath)"
        }
        $snapshotDirectory = [IO.Path]::GetDirectoryName($snapshotPath)
        [IO.Directory]::CreateDirectory($snapshotDirectory) | Out-Null

        $inputStream = [IO.File]::Open(
            $currentFullPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        try {
            $secretReason = Find-SecretContentReason -Stream $inputStream
            if ($null -ne $secretReason) {
                throw "Packaging refused: found $secretReason in $($item.RelativePath). Remove the real secret and review the file manifest manually."
            }
            $contentSha256 = Get-StreamSha256 -Stream $inputStream
            $snapshotStream = [IO.File]::Open(
                $snapshotPath,
                [IO.FileMode]::CreateNew,
                [IO.FileAccess]::Write,
                [IO.FileShare]::None
            )
            try {
                $inputStream.CopyTo($snapshotStream)
            }
            finally {
                $snapshotStream.Dispose()
            }
        }
        finally {
            $inputStream.Dispose()
        }

        $snapshotLength = [long](Get-Item -LiteralPath $snapshotPath).Length
        $snapshotSourceBytes += $snapshotLength
        if ($snapshotSourceBytes -gt $maximumSourceBytes) {
            throw "Snapshot source size $snapshotSourceBytes exceeds the Lingshu Gate extraction limit of $maximumSourceBytes."
        }

        $snapshotRecords += [PSCustomObject]@{
            RelativePath = $item.RelativePath
            SnapshotPath = $snapshotPath
            ContentSha256 = $contentSha256
        }
    }

    [IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
    $fileStream = [IO.File]::Open(
        $outputFullPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
    )
    $outputCreatedByThisRun = $true
    try {
        $archive = [IO.Compression.ZipArchive]::new($fileStream, [IO.Compression.ZipArchiveMode]::Create, $true)
        try {
            foreach ($item in $snapshotRecords) {
                $entry = $archive.CreateEntry($item.RelativePath, [IO.Compression.CompressionLevel]::Optimal)
                $entry.LastWriteTime = [DateTimeOffset]::new(2000, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
                $entry.ExternalAttributes = 0
                $inputStream = [IO.File]::OpenRead($item.SnapshotPath)
                $entryStream = $entry.Open()
                try {
                    $inputStream.CopyTo($entryStream)
                }
                finally {
                    $entryStream.Dispose()
                    $inputStream.Dispose()
                }
            }
        }
        finally {
            $archive.Dispose()
        }
    }
    finally {
        $fileStream.Dispose()
    }

    $zipItem = Get-Item -LiteralPath $outputFullPath
    if ($zipItem.Length -gt $maximumZipBytes) {
        throw "ZIP size $($zipItem.Length) exceeds the Lingshu Gate limit of $maximumZipBytes."
    }

    $markers = @(
        foreach ($marker in $entryMarkers) {
            if ($snapshotRecords.RelativePath -contains $marker) {
                $marker
            }
        }
    )
    $hash = (Get-FileHash -LiteralPath $outputFullPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $fileListMaterial = (($snapshotRecords | ForEach-Object {
        "$($_.RelativePath)`0$($_.ContentSha256)"
    }) -join "`n")
    $fileListBytes = [Text.Encoding]::UTF8.GetBytes($fileListMaterial)
    $fileListHashBytes = [Security.Cryptography.SHA256]::HashData($fileListBytes)
    $fileListSha256 = ([BitConverter]::ToString($fileListHashBytes)).Replace('-', '').ToLowerInvariant()
    $bundleCompleted = $true

    [PSCustomObject]@{
        project_root = $resolvedProjectRoot
        output_path = $outputFullPath
        file_count = $snapshotRecords.Count
        source_size_bytes = $snapshotSourceBytes
        zip_size_bytes = $zipItem.Length
        sha256 = $hash
        file_list_sha256 = $fileListSha256
        included_files = @($snapshotRecords.RelativePath)
        entry_markers = $markers
        excluded_directories = $excludedDirectories
        rejected_secret_file_names = $forbiddenSecretFileNames
        rejected_secret_extensions = $forbiddenSecretExtensions
        content_secret_scan = 'Heuristic high-confidence patterns only; this cannot prove that unknown or obfuscated secrets are absent. Review included_files manually before upload.'
    } | ConvertTo-Json -Depth 5
}
catch {
    if ($outputCreatedByThisRun -and (Test-Path -LiteralPath $outputFullPath)) {
        Remove-Item -LiteralPath $outputFullPath -Force
    }
    throw
}
finally {
    if (-not $bundleCompleted -and $outputCreatedByThisRun -and (Test-Path -LiteralPath $outputFullPath)) {
        Remove-Item -LiteralPath $outputFullPath -Force
    }
    $resolvedSnapshotRoot = [IO.Path]::GetFullPath($snapshotRoot)
    if (-not $resolvedSnapshotRoot.StartsWith($systemTempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The temporary snapshot cleanup path escaped the system temporary directory.'
    }
    if (Test-Path -LiteralPath $resolvedSnapshotRoot) {
        Remove-Item -LiteralPath $resolvedSnapshotRoot -Recurse -Force
    }
}
