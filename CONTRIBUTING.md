# Contributing - project-workflow

## Local Checks

```bash
make quality
make warnings
make compose-ready
```

On Windows without `make`:

```powershell
pwsh -File scripts/quality.ps1 quality
pwsh -File scripts/quality.ps1 warnings
pwsh -File scripts/quality.ps1 compose-ready
```

## License and Contribution Rights

This project is proprietary source-available, not open source. A PR is accepted only if the contributor grants FerrPOINT an irrevocable, worldwide, perpetual, royalty-free, sublicensable, transferable right to use, reproduce, modify, distribute, relicense, commercialize, and sell the contribution as part of the software or related products and services.

If you do not agree to this grant of rights, do not submit a PR, patch, documentation change, design, review suggestion, or other contribution.
