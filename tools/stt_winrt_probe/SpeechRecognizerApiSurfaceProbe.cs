using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using Windows.Media.Capture;
using Windows.Media.SpeechRecognition;

internal static class SpeechRecognizerApiSurfaceProbe
{
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    private static readonly string[] InputTerms =
    {
        "audio", "capture", "device", "input", "microphone", "source", "stream"
    };

    private static int Main()
    {
        Console.OutputEncoding = new UTF8Encoding(false);

        Type recognizerType = typeof(SpeechRecognizer);
        Type captureSettingsType = typeof(MediaCaptureInitializationSettings);
        string[] constructors = recognizerType.GetConstructors()
            .Select(FormatMethod).OrderBy(value => value).ToArray();
        string[] properties = recognizerType.GetProperties()
            .Select(property => string.Format("{0} {1} {2}",
                property.CanWrite ? "read-write" : "read-only",
                FriendlyName(property.PropertyType), property.Name))
            .OrderBy(value => value).ToArray();
        string[] methods = recognizerType.GetMethods(BindingFlags.Instance | BindingFlags.Public |
                                                       BindingFlags.DeclaredOnly)
            .Select(FormatMethod).OrderBy(value => value).ToArray();
        string[] inputCandidates = recognizerType.GetMembers(BindingFlags.Instance |
                                                               BindingFlags.Public |
                                                               BindingFlags.DeclaredOnly)
            .Where(member => InputTerms.Any(term =>
                member.Name.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0))
            .Select(member => member.MemberType + " " + member.Name)
            .OrderBy(value => value).ToArray();

        PropertyInfo mediaCaptureAudioDeviceId = captureSettingsType.GetProperty("AudioDeviceId");
        bool recognizerHasWritableInputMember = recognizerType.GetProperties()
            .Any(property => property.CanWrite && InputTerms.Any(term =>
                property.Name.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0));
        bool recognizerHasInputParameter = recognizerType.GetConstructors()
            .Cast<MethodBase>()
            .Concat(recognizerType.GetMethods(BindingFlags.Instance | BindingFlags.Public |
                                               BindingFlags.DeclaredOnly))
            .SelectMany(method => method.GetParameters())
            .Any(parameter => InputTerms.Any(term =>
                parameter.Name.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0 ||
                FriendlyName(parameter.ParameterType).IndexOf(term,
                    StringComparison.OrdinalIgnoreCase) >= 0));

        Dictionary<string, object> result = new Dictionary<string, object>
        {
            { "ok", true },
            { "probe", "speech_recognizer_api_surface" },
            { "speech_recognizer_type", recognizerType.FullName },
            { "constructors", constructors },
            { "properties", properties },
            { "methods", methods },
            { "input_candidate_members", inputCandidates },
            { "recognizer_has_writable_input_member", recognizerHasWritableInputMember },
            { "recognizer_has_input_parameter", recognizerHasInputParameter },
            { "media_capture_has_audio_device_id", mediaCaptureAudioDeviceId != null &&
                                                    mediaCaptureAudioDeviceId.CanWrite },
            { "explicit_endpoint_binding_supported",
                recognizerHasWritableInputMember || recognizerHasInputParameter },
        };
        Console.Out.Write(Json.Serialize(result));
        return 0;
    }

    private static string FormatMethod(MethodBase method)
    {
        MethodInfo info = method as MethodInfo;
        string returnType = info == null ? "constructor" : FriendlyName(info.ReturnType);
        string parameters = string.Join(", ", method.GetParameters().Select(parameter =>
            FriendlyName(parameter.ParameterType) + " " + parameter.Name));
        return string.Format("{0} {1}({2})", returnType, method.Name, parameters);
    }

    private static string FriendlyName(Type type)
    {
        return type == null ? "" : (type.FullName ?? type.Name);
    }
}
