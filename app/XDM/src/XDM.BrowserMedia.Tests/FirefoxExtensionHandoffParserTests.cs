using System.Text.Json;
using XDM.BrowserIntegration;

namespace XDM.BrowserMedia.Tests;

public sealed class FirefoxExtensionHandoffParserTests
{
    [Fact]
    public void ParsesCanonicalAddV1WithoutChangingItsWireContract()
    {
        string uri = BuildUri("add", new Dictionary<string, string>
        {
            ["v"] = "1",
            ["url"] = "https://cdn.example.test/file.mp4",
            ["page"] = "https://example.test/watch/1",
            ["title"] = "Example video",
            ["filename"] = "example.mp4",
            ["mime"] = "video/mp4"
        });

        Assert.True(FirefoxExtensionHandoffParser.TryParse(uri, out FirefoxExtensionHandoff? handoff, out string error), error);
        BrowserCaptureRequest request = Assert.Single(handoff!.Requests);
        Assert.Equal("https://cdn.example.test/file.mp4", request.Url.AbsoluteUri);
        Assert.Equal("https://example.test/watch/1", request.SourcePage);
        Assert.Equal("example.mp4", request.FileName);
        Assert.Equal("video/mp4", request.MimeType);
        Assert.Equal("context", request.Operation);
        Assert.Equal("Firefox", request.Browser);
        Assert.True(request.BypassRules);
    }

    [Fact]
    public void CaptureV3CannotSmuggleCredentialBearingNavigationIntoDesktop()
    {
        string uri = BuildUri("capture", new Dictionary<string, string>
        {
            ["v"] = "3",
            ["url"] = "https://cdn.example.test/master.m3u8?signature=signed-secret",
            ["headers"] = "Cookie: sid=secret\nAuthorization: Bearer secret",
            ["finalHeaders"] = "Cookie: sid=secret\nAuthorization: Bearer secret"
        });
        Assert.False(FirefoxExtensionHandoffParser.TryParse(uri, out _, out string error));
        Assert.Contains("paired Android app", error, StringComparison.Ordinal);
    }

    [Fact]
    public void CaptureV3CandidateBatchIsRejectedBeforeReadingNestedRequestCredentials()
    {
        string uri = BuildUri("capture", new Dictionary<string, string>
        {
            ["v"] = "3",
            ["url"] = "https://cdn.example.test/master.m3u8",
            ["sid"] = "session_12345678",
            ["candidates"] = "[{\"url\":\"https://cdn.example.test/variant.m3u8?token=secret\"}]"
        });
        Assert.False(FirefoxExtensionHandoffParser.TryParse(uri, out _, out string error));
        Assert.Contains("paired Android app", error, StringComparison.Ordinal);
    }

    [Fact]
    public void AnyLegacyCaptureV3IsRejectedWithoutTrustingSessionIdentity()
    {
        string uri = BuildUri("capture", new Dictionary<string, string>
        {
            ["v"] = "3",
            ["url"] = "https://cdn.example.test/master.m3u8",
            ["candidates"] = "[]"
        });
        Assert.False(FirefoxExtensionHandoffParser.TryParse(uri, out _, out string error));
        Assert.Contains("paired Android app", error, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("xdmdownload://capture?v=2&url=https%3A%2F%2Fexample.test%2Fvideo.mp4")]
    [InlineData("xdmdownload://capture?v=3&v=3&url=https%3A%2F%2Fexample.test%2Fvideo.mp4")]
    [InlineData("xdmdownload://capture?v=3&url=ftp%3A%2F%2Fexample.test%2Fvideo.mp4")]
    [InlineData("xdmdownload://capture?v=3&url=https%3A%2F%2Fuser%3Apass%40example.test%2Fvideo.mp4")]
    [InlineData("https://example.test/video.mp4")]
    public void RejectsUnsupportedOrAmbiguousEnvelopes(string uri)
    {
        Assert.False(FirefoxExtensionHandoffParser.TryParse(uri, out _, out string error));
        Assert.NotEmpty(error);
    }

    [Fact]
    public void FindsCanonicalProtocolArgumentAmongNormalDesktopArguments()
    {
        string uri = "xdmdownload://add?v=1&url=https%3A%2F%2Fexample.test%2Ffile.zip";

        Assert.Equal(uri, FirefoxExtensionHandoffParser.FindHandoffArgument(["--minimized", uri, "--other"]));
        Assert.Null(FirefoxExtensionHandoffParser.FindHandoffArgument(["--minimized", "https://example.test"]));
    }

    private static string BuildUri(string action, IReadOnlyDictionary<string, string> parameters)
        => $"xdmdownload://{action}?" + string.Join(
            "&",
            parameters.Select(pair => $"{Uri.EscapeDataString(pair.Key)}={Uri.EscapeDataString(pair.Value)}"));
}
