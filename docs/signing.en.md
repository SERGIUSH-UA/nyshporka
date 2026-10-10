# Licences, signing and privacy

## Code signing policy

**One artefact** is signed — the Windows installer
`nyshporka-<версія>-setup.exe` from the [releases page][rel]. The wheel and the `sdist` on
PyPI are not signed with Authenticode: there, integrity is guaranteed by the index itself and by
[Trusted Publishing][tp] via OIDC, with no long-lived tokens.

**What is signed and by whom.** The file is built only in GitHub Actions
(`.github/workflows/release.yml`, job `windows-setup`), from a `v*` tag, after
the quality gates and the check for private data. There is no manual build on anyone's machine in
the chain. The project is run by one person, so the Author, Reviewer and Approver roles
coincide; each signature is confirmed separately, by hand.

**How you can check:**

```powershell
(Get-AuthenticodeSignature .\nyshporka-setup.exe).Status   # Valid
```

Next to the installer in the release there is a `.sha256` file — you can use it to verify
the download independently of the signature.

> Free code signing provided by [SignPath.io](https://about.signpath.io),
> certificate by [SignPath Foundation](https://signpath.org)

⚠ **At the moment the application has been submitted, and releases are not signed yet.** Until then Windows
shows “Windows protected your PC” — this is expected for a program that few people have
downloaded so far. The signature will remove the “Unknown publisher” label, but the warning itself
will only go away once reputation builds up: Microsoft has withdrawn instant
trust for certificates, EV ones included.

[rel]: https://github.com/SERGIUSH-UA/nyshporka/releases
[tp]: https://docs.pypi.org/trusted-publishers/

## Privacy

Nyshporka is a local application: there is no telemetry, there are no accounts,
your research is not uploaded anywhere, and the application goes online only when
you ask it to with a command. The full list of where and why is in
[`PRIVACY.md`](https://github.com/SERGIUSH-UA/nyshporka/blob/main/PRIVACY.md).

## Licence

[AGPL-3.0-or-later](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE).

Copyleft here is not a matter of mood but a requirement of the dependency tree: `Unidecode` —
a core dependency (name normalisation, `utils/text.py`) — is under **GPL-2.0-or-later**.
AGPL-3.0 is compatible with it and stricter, and the application works through a browser, which is exactly
the case AGPL covers.

⚠ The `strhub` package contains the `models/abinet` submodule under a non-commercial
USTC licence. Nyshporka uses **only PARSeq** from it (Apache-2.0).

**Model weights are separate, under [CC BY-SA 4.0](https://github.com/SERGIUSH-UA/nyshporka/blob/main/LICENSE-MODELS.md).** They are not
in the package, they come in a separate release, and AGPL has no
defined “corresponding source code” for binary weights — so it would protect nothing, yet
it would put off those who want to use them honestly. The terms are the same in spirit: free,
including commercially, with attribution, and fine-tuned weights stay open.
