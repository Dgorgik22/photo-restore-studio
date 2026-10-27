# Alpha Lite single-file setup

`PhotoRestoreStudio-0.25-alpha-lite-Setup.exe` is a small Windows Forms installer,
not a second copy of the photo processing runtime. It downloads the existing four
release archives from GitHub, or reuses checksum-valid archives beside itself.
The embedded release.json pins archive sizes, SHA-256 values and five model hashes.
No account, API token or publisher machine configuration is embedded.

Build on Windows with .NET Framework 4.8:

```powershell
.\installer\build_setup.ps1
```

The build uses the system C# compiler and existing application icon. No external
packaging tools, Python environment or administrator rights are required.
The release payload archives must already be present in the release directory.

Installation uses a separate staging folder, rejects traversal/links, validates
model hashes and commits only to a new destination. Cancellation removes owned
staging files. Downloads use a marked, locked cache and HTTP Range resume; only
owned cached archives are removed after success. User-supplied adjacent archives
and existing installations are never overwritten or deleted.

NTFS LZX compression is optional at the filesystem level and does not change
model weights. Unsupported filesystems remain usable with larger disk usage.
Long-path handling is enabled within the application, without changing Windows settings.
See [Microsoft's path support documentation](https://learn.microsoft.com/en-us/dotnet/framework/migration-guide/retargeting/4.6.x).

InstallerTests.cs covers offline reuse, download resume, Range fallback, corrupt
files, cancellation and rollback, path safety, long paths and RUS/EN rendering.
The real-install test extracts the actual public payload and verifies model hashes.
Photo Restore Studio itself is unchanged by this installer.
