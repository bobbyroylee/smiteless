# Smiteless modern Windows STT probe

This isolated development probe tests the supported Windows desktop speech path without changing
the Smiteless runtime or installer. It uses `Windows.Media.SpeechRecognition` through a small C#
helper and preserves the intended one-child/one-JSON contract.

## Safety boundary

The default build compiles the helper and runs only `readiness`. Readiness enumerates language and
package-identity metadata; it sets `capture_started=false` and does not compile a dictation
constraint or open the microphone.

`-Pack` additionally creates an unsigned sparse MSIX ready for an explicit signing gate. It does
not install or trust a certificate, sign/register the package, update the production installer,
or capture audio.

```powershell
powershell -ExecutionPolicy Bypass -File tools\stt_winrt_probe\build-probe.ps1
powershell -ExecutionPolicy Bypass -File tools\stt_winrt_probe\build-probe.ps1 -Pack
```

Build outputs are written under `build\stt-probe`. The helper uses the installed 64-bit .NET
Framework compiler plus Windows SDK metadata so the spike does not require installing a .NET SDK.
The build emits two binaries from the same source: `SmitelessSttProbe.Unpackaged.exe` proves
readiness without identity, while `SmitelessSttProbe.exe` embeds the matching identity metadata
and is the executable referenced by the sparse package.

The build also compiles and runs `SpeechRecognizerApiSurfaceProbe.exe`. This metadata-only probe
compares the public `SpeechRecognizer` surface with `MediaCaptureInitializationSettings` without
opening an audio device. On the validated Windows SDK/runtime, `SpeechRecognizer` has only its
default and language constructors, has no writable input member or audio/device/stream parameter,
and reports `explicit_endpoint_binding_supported=false`. `MediaCaptureInitializationSettings`
does expose writable `AudioDeviceId`, but `SpeechRecognizer` has no public API that accepts that
`MediaCapture` instance or its stream. Consequently endpoint enumeration alone cannot implement
the required Smiteless microphone selector on this backend.

## JSON contract

`SmitelessSttProbe.exe readiness pt-BR` emits one UTF-8 JSON object containing:

- backend and helper version;
- current package identity (if any);
- system speech language;
- supported topic and grammar language lists;
- requested-locale support;
- `capture_mode=windows_default`, current default capture availability and its diagnostic ID;
- `explicit_endpoint_binding=false`;
- `capture_started=false`.

`SmitelessSttProbe.exe recognize pt-BR 12000` is implemented for the later manual gate. It refuses
to proceed without package identity. When enabled by a registered sparse package, it compiles a
dictation constraint and captures one bounded utterance with categorical WinRT confidence.
If Windows Online speech recognition is disabled or its privacy policy has not been accepted, the
helper returns `online_speech_disabled` before microphone capture.
For the manual spike only, `SMITELESS_STT_PROBE_CUE=1` emits a short beep after constraint
compilation and immediately before `RecognizeAsync`, providing an exact speaking cue without
persisting audio.

## Default microphone contract

Smiteless supports only the capture endpoint currently selected as the Windows default. The
helper obtains that endpoint through `MediaDevice.GetDefaultAudioCaptureId` for readiness but does
not accept an endpoint argument for recognition. The application does not persist a microphone ID
or expose a device selector. Users change the input through Windows Sound settings, and the next
readiness/recognition call follows the Windows default.

## Identity alignment

These fields must remain identical in both manifests and in the signing certificate:

| Field | Value |
|---|---|
| package name | `Smiteless.SttProbe` |
| publisher | `CN=Smiteless Development` |
| application id | `SttProbe` |
| executable | `SmitelessSttProbe.exe` |

`Package.appxmanifest` declares `uap10:RuntimeBehavior="win32App"`,
`uap10:TrustLevel="mediumIL"`, external content, the restricted `runFullTrust` and
`unvirtualizedResources` capabilities, and the `microphone` device capability. The embedded
Win32 manifest carries the matching MSIX identity metadata.

## Reserved manual gate

Do not run these steps without explicit approval:

1. replace the development publisher with the subject of an approved signing certificate;
2. sign `Smiteless.SttProbe.msix` with SignTool;
3. trust the public development certificate in the store required by AppX deployment;
4. register it using `Add-AppxPackage -ExternalLocation <absolute build\stt-probe path>`;
5. rerun readiness and require `package_identity=true` plus `pt-BR` in
   `supported_topic_languages`;
6. run one short `recognize` command and inspect transcript/cancellation/error behavior;
7. remove the development package/certificate and confirm unpackaged readiness again.

On the validated Windows 11 environment, a self-signed package was valid in the current-user
signature context but AppX deployment still returned `CERT_E_UNTRUSTEDROOT`; the deployment
service requires machine-context trust. The official unsigned-package publisher OID was also
rejected for this sparse/external-location package. Therefore the next development gate requires
explicit administrator approval for temporary `LocalMachine\TrustedPeople` trust, or a production
certificate already trusted by the machine. `-AllowUnsigned` is not a viable fallback here.

Production integration must additionally handle stable external paths, package version upgrades,
publisher/signature trust, registration rollback and uninstall cleanup. This probe deliberately
does none of those operations.

## Production build and installer integration

The production build uses a separate, certificate-gated path and never copies the development
identity into the installer. The certificate must already be valid, trusted, carry the Code
Signing EKU and expose its private key from `CurrentUser\My` or `LocalMachine\My`. The build
derives the MSIX publisher from that certificate subject, generates matching helper and package
manifests, signs `Smiteless.Stt.msix`, and stages the external content at the frozen
`app\stt` path:

```powershell
powershell -ExecutionPolicy Bypass -File dist\build.ps1 `
  -SttCertificateThumbprint <thumbprint> `
  -SttCertificateStore CurrentUser `
  -RequireSttPackage
```

`-RequireSttPackage` fails before cleaning/building when no thumbprint is supplied. The release
script always enables this gate, so a voice-enabled release cannot silently omit the signed
package. An ordinary development build may omit the thumbprint; it stages only the package
lifecycle script and the frozen app reports `helper_unavailable`.

The installer validates the MSIX signature, publisher and version before registering
`Smiteless.Stt` with the stable `app\stt` external location. Upgrades back up the prior external
directory and restore its signed package if registration fails. Uninstall removes the exact
package before deleting its external files. Neither production script creates, imports or trusts
a certificate on the user's machine.

`trust-development-certificate.ps1` is reserved for the approved elevated manual gate. It imports
only a seven-day self-signed Code Signing certificate with the exact development subject into
`LocalMachine\TrustedPeople`, and removal requires the exact SHA-1 thumbprint and subject. It does
not create private keys, sign packages or register applications.

## Sources

- [Speech recognition in Windows apps](https://learn.microsoft.com/en-us/windows/apps/develop/input/speech-recognition)
- [Specify the speech recognizer language](https://learn.microsoft.com/en-us/windows/apps/develop/input/specify-the-speech-recognizer-language)
- [Grant package identity manually](https://learn.microsoft.com/en-gb/windows/apps/desktop/modernize/grant-identity-to-nonpackaged-apps)
- [Set speech recognition timeouts](https://learn.microsoft.com/en-us/windows/apps/develop/input/set-speech-recognition-timeouts)
