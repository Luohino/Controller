import 'package:shared_preferences/shared_preferences.dart';

// Runtime-configurable server URL.
// On first launch the user enters their Render URL in the setup screen.
// The value is persisted in SharedPreferences and read here.

const String _defaultUrl = "wss://YOUR_RENDER_APP_NAME.onrender.com/ws";

Future<String> getServerUrl() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.getString('server_url') ?? _defaultUrl;
}

Future<void> setServerUrl(String url) async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString('server_url', url);
}

// Keep a synchronous fallback for imports that expect a const.
// This is only used as a placeholder; runtime code should call getServerUrl().
const String SERVER_URL = _defaultUrl;
