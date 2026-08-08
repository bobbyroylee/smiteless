using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Windows.Globalization;
using Windows.Media.Devices;
using Windows.Media.SpeechRecognition;

internal static class SmitelessSttProbe
{
    private const int AppModelErrorNoPackage = 15700;
    private const int ErrorInsufficientBuffer = 122;
    private const int SpeechPrivacyPolicyNotAccepted = unchecked((int)0x80045509);
    private const string HelperVersion = "0.2";

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetCurrentPackageFullName(ref int packageFullNameLength,
                                                         StringBuilder packageFullName);

    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    private static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        try
        {
            string command = args.Length > 0 ? args[0].Trim().ToLowerInvariant() : "readiness";
            string culture = args.Length > 1 ? NormalizeCulture(args[1]) : "pt-BR";
            Dictionary<string, object> value;
            if (command == "readiness")
            {
                value = Readiness(culture);
            }
            else if (command == "recognize")
            {
                int timeoutMs = args.Length > 2 ? ParseTimeout(args[2]) : 12000;
                value = Recognize(culture, timeoutMs).GetAwaiter().GetResult();
            }
            else
            {
                value = Failure("invalid_command", command);
            }
            Emit(value);
            return value.ContainsKey("ok") && Convert.ToBoolean(value["ok"]) ? 0 : 2;
        }
        catch (Exception exc)
        {
            Emit(Failure("probe_error", Compact(exc.Message)));
            return 2;
        }
    }

    private static Dictionary<string, object> Readiness(string culture)
    {
        string packageFullName;
        bool packaged = TryGetPackageFullName(out packageFullName);
        string[] topicLanguages = SpeechRecognizer.SupportedTopicLanguages
            .Select(language => language.LanguageTag).OrderBy(value => value).ToArray();
        string[] grammarLanguages = SpeechRecognizer.SupportedGrammarLanguages
            .Select(language => language.LanguageTag).OrderBy(value => value).ToArray();
        string systemLanguage = SpeechRecognizer.SystemSpeechLanguage == null
            ? "" : SpeechRecognizer.SystemSpeechLanguage.LanguageTag;
        bool topicSupported = topicLanguages.Any(value => CultureEquals(value, culture));
        bool grammarSupported = grammarLanguages.Any(value => CultureEquals(value, culture));
        string defaultCaptureId = MediaDevice.GetDefaultAudioCaptureId(AudioDeviceRole.Default) ?? "";
        return Success(new Dictionary<string, object>
        {
            { "command", "readiness" },
            { "backend", "windows_media_speech" },
            { "helper_version", HelperVersion },
            { "culture", culture },
            { "package_identity", packaged },
            { "package_full_name", packaged ? packageFullName : "" },
            { "system_speech_language", systemLanguage },
            { "supported_topic_languages", topicLanguages },
            { "supported_grammar_languages", grammarLanguages },
            { "topic_supported", topicSupported },
            { "grammar_supported", grammarSupported },
            { "capture_mode", "windows_default" },
            { "default_capture_id", defaultCaptureId },
            { "default_capture_available", !String.IsNullOrWhiteSpace(defaultCaptureId) },
            { "explicit_endpoint_binding", false },
            { "capture_started", false },
        });
    }

    private static async Task<Dictionary<string, object>> Recognize(string culture, int timeoutMs)
    {
        string packageFullName;
        if (!TryGetPackageFullName(out packageFullName))
        {
            return Failure("missing_package_identity", "Windows speech recognition requires package identity.");
        }
        if (!SpeechRecognizer.SupportedTopicLanguages.Any(value => CultureEquals(value.LanguageTag, culture)))
        {
            return Failure("missing_culture", culture);
        }

        try
        {
            using (CancellationTokenSource cancellation = new CancellationTokenSource(timeoutMs))
            using (SpeechRecognizer recognizer = new SpeechRecognizer(new Language(culture)))
            {
                recognizer.Timeouts.InitialSilenceTimeout = TimeSpan.FromMilliseconds(Math.Min(5000, timeoutMs));
                recognizer.Timeouts.EndSilenceTimeout = TimeSpan.FromMilliseconds(900);
                recognizer.Timeouts.BabbleTimeout = TimeSpan.FromMilliseconds(3000);
                recognizer.Constraints.Add(new SpeechRecognitionTopicConstraint(
                    SpeechRecognitionScenario.Dictation, "smiteless_dictation"));

                SpeechRecognitionCompilationResult compiled;
                try
                {
                    compiled = await recognizer.CompileConstraintsAsync().AsTask(cancellation.Token);
                }
                catch (OperationCanceledException)
                {
                    return Failure("timeout", "Constraint compilation timed out.");
                }
                if (compiled.Status != SpeechRecognitionResultStatus.Success)
                {
                    return Failure(MapStatus(compiled.Status), compiled.Status.ToString());
                }

                if (string.Equals(Environment.GetEnvironmentVariable("SMITELESS_STT_PROBE_CUE"),
                                  "1", StringComparison.Ordinal))
                {
                    Console.Beep(880, 250);
                }

                SpeechRecognitionResult result;
                try
                {
                    result = await recognizer.RecognizeAsync().AsTask(cancellation.Token);
                }
                catch (OperationCanceledException)
                {
                    return Failure("timeout", "Recognition timed out or was cancelled.");
                }

                if (result == null || result.Status != SpeechRecognitionResultStatus.Success)
                {
                    SpeechRecognitionResultStatus status = result == null
                        ? SpeechRecognitionResultStatus.Unknown : result.Status;
                    return Failure(MapStatus(status), status.ToString());
                }

                string confidenceLevel = result.Confidence.ToString();
                IReadOnlyList<SpeechRecognitionResult> alternateResults = result.GetAlternates(3);
                List<Dictionary<string, object>> alternates = alternateResults == null
                    ? new List<Dictionary<string, object>>()
                    : alternateResults.Select(alternate => new Dictionary<string, object>
                      {
                          { "text", CompactText(alternate.Text) },
                          { "confidence_level", alternate.Confidence.ToString() },
                          { "raw_confidence", alternate.RawConfidence },
                      }).ToList();
                Dictionary<string, object> payload = new Dictionary<string, object>
                {
                    { "command", "recognize" },
                    { "backend", "windows_media_speech" },
                    { "helper_version", HelperVersion },
                    { "culture", culture },
                    { "package_identity", true },
                    { "text", CompactText(result.Text) },
                    { "confidence_level", confidenceLevel },
                    { "raw_confidence", result.RawConfidence },
                    { "alternates", alternates },
                };
                if (result.Confidence == SpeechRecognitionConfidence.Low ||
                    result.Confidence == SpeechRecognitionConfidence.Rejected)
                {
                    payload["ok"] = false;
                    payload["error"] = "low_confidence";
                    return payload;
                }
                return Success(payload);
            }
        }
        catch (UnauthorizedAccessException exc)
        {
            return Failure("permission_denied", Compact(exc.Message));
        }
        catch (COMException exc)
        {
            if (exc.HResult == SpeechPrivacyPolicyNotAccepted ||
                exc.Message.IndexOf("privacy policy", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return Failure("online_speech_disabled",
                    "Windows Online speech recognition must be enabled before dictation.");
            }
            return Failure("recognition_error", Compact(exc.Message));
        }
    }

    private static bool TryGetPackageFullName(out string packageFullName)
    {
        int length = 0;
        int status = GetCurrentPackageFullName(ref length, null);
        if (status == AppModelErrorNoPackage)
        {
            packageFullName = "";
            return false;
        }
        if (status != ErrorInsufficientBuffer || length <= 0)
        {
            packageFullName = "";
            return false;
        }
        StringBuilder value = new StringBuilder(length);
        status = GetCurrentPackageFullName(ref length, value);
        packageFullName = status == 0 ? value.ToString() : "";
        return status == 0;
    }

    private static Dictionary<string, object> Success(Dictionary<string, object> value)
    {
        value["ok"] = true;
        return value;
    }

    private static Dictionary<string, object> Failure(string error, string message)
    {
        return new Dictionary<string, object>
        {
            { "ok", false },
            { "error", error },
            { "message", Compact(message) },
            { "backend", "windows_media_speech" },
            { "helper_version", HelperVersion },
        };
    }

    private static string MapStatus(SpeechRecognitionResultStatus status)
    {
        switch (status)
        {
            case SpeechRecognitionResultStatus.TopicLanguageNotSupported: return "missing_culture";
            case SpeechRecognitionResultStatus.NetworkFailure: return "network_unavailable";
            case SpeechRecognitionResultStatus.MicrophoneUnavailable: return "microphone_unavailable";
            case SpeechRecognitionResultStatus.AudioQualityFailure: return "audio_quality";
            case SpeechRecognitionResultStatus.UserCanceled: return "cancelled";
            case SpeechRecognitionResultStatus.TimeoutExceeded:
            case SpeechRecognitionResultStatus.PauseLimitExceeded: return "no_speech";
            case SpeechRecognitionResultStatus.GrammarLanguageMismatch:
            case SpeechRecognitionResultStatus.GrammarCompilationFailure: return "recognition_error";
            default: return "recognition_error";
        }
    }

    private static int ParseTimeout(string value)
    {
        int parsed;
        return int.TryParse(value, out parsed) ? Math.Max(1000, Math.Min(20000, parsed)) : 12000;
    }

    private static string NormalizeCulture(string value)
    {
        string compact = (value ?? "").Trim().Replace('_', '-');
        if (compact.Equals("pt-br", StringComparison.OrdinalIgnoreCase)) return "pt-BR";
        if (compact.Equals("en", StringComparison.OrdinalIgnoreCase) ||
            compact.Equals("en-us", StringComparison.OrdinalIgnoreCase)) return "en-US";
        return compact;
    }

    private static bool CultureEquals(string left, string right)
    {
        return string.Equals(left, right, StringComparison.OrdinalIgnoreCase);
    }

    private static string CompactText(string value)
    {
        return string.Join(" ", (value ?? "").Split((char[])null,
            StringSplitOptions.RemoveEmptyEntries));
    }

    private static string Compact(string value)
    {
        string compact = CompactText(value);
        return compact.Length <= 300 ? compact : compact.Substring(0, 300);
    }

    private static void Emit(Dictionary<string, object> value)
    {
        Console.Out.Write(Json.Serialize(value));
    }
}
